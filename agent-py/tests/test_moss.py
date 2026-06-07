"""Unit tests for the Mira resident-support agent's Moss-backed tools.

Deterministic unit tests that exercise the tool methods directly. They stub
`MossClient` via monkeypatch so they run with no Moss credentials and no network
access.
"""

import json

import pytest

import agent as agent_module
import work_orders as work_orders_module
from agent import Assistant

TENANT_ID = "tenant_42"


class _FakeDoc:
    def __init__(self, text: str, score=None, metadata=None) -> None:
        self.text = text
        self.score = score
        self.metadata = metadata


class _FakeSearchResult:
    def __init__(self, docs, time_taken_ms: float = 12.5) -> None:
        self.docs = docs
        self.time_taken_ms = time_taken_ms


class _FakeMossClient:
    """Records calls instead of contacting Moss. Substituted for `MossClient`."""

    def __init__(self, *args, **kwargs) -> None:
        self.load_index_calls: list[str] = []
        self.query_calls: list[tuple] = []
        self.add_docs_calls: list[tuple] = []
        self.query_result = _FakeSearchResult([])

    async def load_index(self, name, *args, **kwargs):
        self.load_index_calls.append(name)

    async def query(self, index, query, options=None):
        self.query_calls.append((index, query, options))
        return self.query_result

    async def add_docs(self, index, docs, options=None):
        self.add_docs_calls.append((index, docs, options))
        return None


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish_data(self, payload, reliable=None):
        self.published.append((payload, reliable))


class _FakeRoom:
    def __init__(self) -> None:
        self.local_participant = _FakePublisher()


@pytest.fixture
def stub_moss(monkeypatch):
    monkeypatch.setattr(agent_module, "MossClient", _FakeMossClient)


@pytest.fixture(autouse=True)
def isolate_work_orders(tmp_path, monkeypatch):
    """Point the work-order store at a throwaway file so tests don't write to
    the repo's work_orders.json."""
    monkeypatch.setattr(work_orders_module, "STORE_PATH", tmp_path / "work_orders.json")


# --- Grounding ----------------------------------------------------------------


async def test_search_knowledge_joins_text_and_publishes_context(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, tenant_id=TENANT_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc("Rent is due on the 1st.", score=0.9, metadata={"topic": "rent"}),
            _FakeDoc("Grace period through the 5th.", score=0.8),
        ],
        time_taken_ms=7.0,
    )

    result = await assistant.search_knowledge(None, "when is rent due?")

    assert result == "Rent is due on the 1st.\n\nGrace period through the 5th."
    index, query, options = assistant._moss.query_calls[0]
    assert index == agent_module.KNOWLEDGE_INDEX
    assert query == "when is rent due?"
    assert options.top_k == 3

    payload_bytes, reliable = room.local_participant.published[0]
    assert reliable is True
    data = json.loads(payload_bytes.decode("utf-8"))["data"]
    assert set(data) == {"query", "matches", "time_taken_ms", "timestamp"}
    assert data["time_taken_ms"] == 7.0
    assert data["matches"][0]["text"] == "Rent is due on the 1st."


async def test_search_knowledge_handles_no_results(stub_moss) -> None:
    assistant = Assistant(tenant_id=TENANT_ID)
    result = await assistant.search_knowledge(None, "anything")
    assert "couldn't find" in result.lower()


# --- Resident account of record (anti-hallucination) --------------------------


async def test_lookup_resident_quotes_exact_figures(stub_moss, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_module,
        "MOCK_TENANTS",
        {
            TENANT_ID: {
                "name": "Sam Carter",
                "unit": "Unit 2A, 10 Oak Ave",
                "monthly_rent": "1,850",
                "balance": "0.00",
                "rent_due": "the 1st",
                "lease_start": "March 1, 2025",
                "lease_end": "February 28, 2026",
                "deposit": "1,850",
                "status": "current, in good standing",
                "pets": "one cat on file",
            }
        },
    )
    assistant = Assistant(tenant_id=TENANT_ID)

    result = await assistant.lookup_resident(None)

    assert "Sam Carter" in result
    assert "1,850" in result
    assert "Unit 2A, 10 Oak Ave" in result
    assert "February 28, 2026" in result


async def test_lookup_resident_handles_unknown(stub_moss, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "MOCK_TENANTS", {})
    assistant = Assistant(tenant_id="nobody")
    result = await assistant.lookup_resident(None)
    assert "couldn't find an account" in result.lower()


# --- Per-resident memory ------------------------------------------------------


async def test_remember_fact_writes_with_tenant_metadata(stub_moss) -> None:
    assistant = Assistant(tenant_id=TENANT_ID)
    result = await assistant.remember_fact(None, "Prefers texts over calls.")
    assert isinstance(result, str) and result

    assert len(assistant._moss.add_docs_calls) == 1
    index, docs, _opts = assistant._moss.add_docs_calls[0]
    assert index == agent_module.MEMORY_INDEX
    assert docs[0].metadata == {"tenant_id": TENANT_ID}
    assert "Prefers texts" in docs[0].text
    assert docs[0].id.startswith(f"{TENANT_ID}-")


async def test_recall_facts_filters_by_tenant_id(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, tenant_id=TENANT_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc("They prefer texts over calls."),
            _FakeDoc("Reported a slow kitchen drain in May."),
        ]
    )

    result = await assistant.recall_facts(None, "contact preference")

    assert "prefer texts" in result
    index, _query, options = assistant._moss.query_calls[0]
    assert index == agent_module.MEMORY_INDEX
    assert options.top_k == 5
    assert options.filter == {
        "field": "tenant_id",
        "condition": {"$eq": TENANT_ID},
    }
    assert len(room.local_participant.published) == 1


# --- Resolve: work order + text ----------------------------------------------


async def test_create_work_order_degrades_without_recipient(
    stub_moss, monkeypatch
) -> None:
    for var in ("TENANT_PHONE", "DEMO_PHONE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        agent_module,
        "MOCK_TENANTS",
        {TENANT_ID: {"name": "Sam", "unit": "Unit 2A"}},
    )
    assistant = Assistant(tenant_id=TENANT_ID)

    result = await assistant.create_work_order(None, "Leaky kitchen faucet")

    # No recipient -> reads the work order number aloud, still logs it.
    assert "work order number" in result.lower()
    assert len(assistant._moss.add_docs_calls) == 1  # logged to memory
    _index, docs, _opts = assistant._moss.add_docs_calls[0]
    assert docs[0].metadata == {"tenant_id": TENANT_ID}
    assert "Leaky kitchen faucet" in docs[0].text


async def test_create_work_order_emergency_texts_via_bridge(
    stub_moss, monkeypatch
) -> None:
    monkeypatch.setenv("TENANT_PHONE", "+15552223333")
    monkeypatch.setenv("ESCALATE_URL", "http://localhost:8787/send")
    monkeypatch.setenv("ESCALATE_SHARED_SECRET", "s3cret")
    monkeypatch.setattr(
        agent_module,
        "MOCK_TENANTS",
        {TENANT_ID: {"name": "Sam", "unit": "Unit 2A, 10 Oak Ave"}},
    )

    sent: dict = {}

    class _FakeResponse:
        status_code = 200
        text = "ok"

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            sent["url"] = url
            sent["json"] = json
            sent["headers"] = headers
            return _FakeResponse()

    assistant = Assistant(tenant_id=TENANT_ID)
    monkeypatch.setattr(agent_module.httpx, "AsyncClient", _FakeAsyncClient)

    result = await assistant.create_work_order(
        None, "Water leaking from ceiling", urgency="emergency"
    )

    assert "emergency" in result.lower() or "dispatched" in result.lower()
    assert "texted" in result.lower()
    assert sent["url"].endswith("/send")
    assert sent["json"]["to"] == "+15552223333"
    assert "Water leaking from ceiling" in sent["json"]["body"]
    assert sent["headers"]["x-escalate-secret"] == "s3cret"


async def test_create_work_order_records_to_store(stub_moss, monkeypatch) -> None:
    for var in ("TENANT_PHONE", "DEMO_PHONE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        agent_module,
        "MOCK_TENANTS",
        {TENANT_ID: {"name": "Sam", "unit": "Unit 2A"}},
    )
    assistant = Assistant(tenant_id=TENANT_ID)

    await assistant.create_work_order(None, "Broken dishwasher", urgency="routine")

    orders = work_orders_module.list_work_orders()
    assert len(orders) == 1
    order = orders[0]
    assert order["summary"] == "Broken dishwasher"
    assert order["urgency"] == "routine"
    assert order["channel"] == "voice"
    assert order["tenant_id"] == TENANT_ID
    assert order["unit"] == "Unit 2A"
    assert order["id"].startswith("WO-")
    assert order["status"] == "open"
