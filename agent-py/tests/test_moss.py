"""Unit tests for the lab-support agent's Moss-backed tools and state machine.

Unlike the LLM-judged evals in `test_agent.py`, these are deterministic unit
tests that exercise the tool methods directly. They stub `MossClient` via
monkeypatch so they run with no Moss credentials and no network access — the
live, credentialed behavior is validated separately.
"""

import json

import pytest

import agent as agent_module
from agent import Assistant, RemediationSession

DEVICE_ID = "HX220-SN-TEST"


class _FakeDoc:
    """Stand-in for a Moss query-result document (`.text/.score/.metadata`)."""

    def __init__(self, text: str, score=None, metadata=None) -> None:
        self.text = text
        self.score = score
        self.metadata = metadata


class _FakeSearchResult:
    """Stand-in for a Moss `SearchResult` (`.docs/.time_taken_ms`)."""

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
    """Replace the agent's `MossClient` with the recording fake."""
    monkeypatch.setattr(agent_module, "MossClient", _FakeMossClient)


# --- A small, deterministic procedure registry independent of the corpus ------

FIXTURE_PROCEDURES = {
    "E101": {
        "fault_code": "E-101",
        "description": "Aspiration probe clog",
        "severity": "operator",
        "steps": [
            "Put the analyzer in Standby.",
            "Run Probe Clean.",
            "Run a Background Check.",
        ],
        "safety": "Wear gloves; the probe area is a biohazard zone.",
    },
    "E707": {
        "fault_code": "E-707",
        "description": "Vacuum pump failure",
        "severity": "service",
        "steps": [],
        "safety": "Service-only. Do not open the instrument.",
    },
}


@pytest.fixture
def stub_procedures(monkeypatch):
    monkeypatch.setattr(agent_module, "PROCEDURES", FIXTURE_PROCEDURES)


# --- Retrieval / grounding ----------------------------------------------------


async def test_search_procedures_joins_text_and_publishes_context(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, device_id=DEVICE_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc("Run Probe Clean.", score=0.9, metadata={"fault_code": "E-101"}),
            _FakeDoc("Inspect the probe tip.", score=0.8),
        ],
        time_taken_ms=7.0,
    )

    result = await assistant.search_procedures(None, "probe clog")

    assert result == "Run Probe Clean.\n\nInspect the probe tip."
    index, query, options = assistant._moss.query_calls[0]
    assert index == agent_module.KNOWLEDGE_INDEX
    assert query == "probe clog"
    assert options.top_k == 3

    payload_bytes, reliable = room.local_participant.published[0]
    assert reliable is True
    data = json.loads(payload_bytes.decode("utf-8"))["data"]
    assert set(data) == {"query", "matches", "time_taken_ms", "timestamp"}
    assert data["time_taken_ms"] == 7.0
    assert data["matches"][0]["text"] == "Run Probe Clean."


async def test_lookup_symptom_returns_candidate_codes(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, device_id=DEVICE_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc(
                "Fault E-101 — Aspiration probe clog. Sample not aspirated.",
                metadata={"fault_code": "E-101"},
            ),
            _FakeDoc(
                "Fault E-312 — Sheath pressure out of range. Unstable counts.",
                metadata={"fault_code": "E-312"},
            ),
        ]
    )

    result = await assistant.lookup_symptom(None, "it's not drawing sample")

    assert "E-101" in result
    assert "E-312" in result
    # Queried the knowledge index and surfaced the panel.
    assert assistant._moss.query_calls[0][0] == agent_module.KNOWLEDGE_INDEX
    assert len(room.local_participant.published) == 1


async def test_read_instrument_quotes_exact_state(stub_moss, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_module,
        "MOCK_INSTRUMENTS",
        {
            DEVICE_ID: {
                "model": "Helix HX-220 hematology analyzer",
                "serial": DEVICE_ID,
                "firmware": "4.2.1",
                "active_fault_code": "E-101",
                "active_fault_desc": "Aspiration probe clog or clot detected",
                "recent_errors": "E-101 at 09:14",
                "reagent_levels": "diluent 62 percent",
                "last_qc": "Level 2 passed at 07:30",
                "temperature": "37.0 degrees Celsius",
                "status": "Halted",
            }
        },
    )
    assistant = Assistant(device_id=DEVICE_ID)

    result = await assistant.read_instrument(None)

    # Exact values, never invented.
    assert "E-101" in result
    assert "4.2.1" in result
    assert "diluent 62 percent" in result
    assert "37.0 degrees Celsius" in result


async def test_read_instrument_handles_unknown_device(stub_moss, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "MOCK_INSTRUMENTS", {})
    assistant = Assistant(device_id="nobody")
    result = await assistant.read_instrument(None)
    assert "couldn't reach" in result.lower()


# --- State machine: start / advance / safety gate -----------------------------


async def test_start_remediation_returns_first_step(stub_moss, stub_procedures) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, device_id=DEVICE_ID)

    result = await assistant.start_remediation(None, "e 101")  # loose code formatting

    assert assistant._session is not None
    assert assistant._session.fault_code == "E-101"
    assert assistant._session.step_idx == 0
    assert "Step one of 3" in result
    assert "Standby" in result
    assert "biohazard" in result.lower()  # safety note spoken first


async def test_start_remediation_refuses_service_only_fault(
    stub_moss, stub_procedures
) -> None:
    """The safety gate: a service-only fault never enters a fix flow."""
    assistant = Assistant(device_id=DEVICE_ID)

    result = await assistant.start_remediation(None, "E-707")

    assert "field-service-only" in result.lower() or "service-only" in result.lower()
    assert "escalat" in result.lower()
    # Session exists but carries no steps to walk.
    assert assistant._session is not None
    assert assistant._session.steps == []


async def test_start_remediation_unknown_code_escalates(
    stub_moss, stub_procedures
) -> None:
    assistant = Assistant(device_id=DEVICE_ID)
    result = await assistant.start_remediation(None, "E-999")
    assert assistant._session is None
    assert "don't have a documented" in result.lower()
    assert "escalat" in result.lower()


async def test_advance_step_walks_then_resolves(
    stub_moss, stub_procedures, monkeypatch
) -> None:
    # No recipient configured -> the resolution receipt path makes no network call.
    for var in ("SERVICE_DESK_PHONE", "TECH_PHONE", "DEMO_PHONE"):
        monkeypatch.delenv(var, raising=False)
    assistant = Assistant(device_id=DEVICE_ID)
    await assistant.start_remediation(None, "E-101")

    # Step 1 done, not cleared -> advance to step 2.
    r2 = await assistant.advance_step(None, "Done, it's in Standby.")
    assert "Step 2 of 3" in r2
    assert assistant._session.step_idx == 1

    # Step 2 clears the fault.
    r3 = await assistant.advance_step(
        None, "Probe Clean ran, no more flag.", fault_cleared=True
    )
    assert assistant._session.resolved is True
    assert "cleared" in r3.lower()
    # Resolution was logged to the per-instrument memory index.
    assert len(assistant._moss.add_docs_calls) == 1
    _index, docs, _opts = assistant._moss.add_docs_calls[0]
    assert docs[0].metadata == {"device_id": DEVICE_ID}


async def test_advance_step_exhausts_then_signals_escalation(
    stub_moss, stub_procedures
) -> None:
    assistant = Assistant(device_id=DEVICE_ID)
    await assistant.start_remediation(None, "E-101")  # 3 steps

    await assistant.advance_step(None, "done")  # -> step 2
    await assistant.advance_step(None, "done")  # -> step 3
    final = await assistant.advance_step(None, "still flagging")  # past last step

    assert "still flagging" in final.lower()
    assert "escalat" in final.lower()
    assert len(assistant._session.attempts) == 3


async def test_advance_step_without_session_guides_user(stub_moss) -> None:
    assistant = Assistant(device_id=DEVICE_ID)
    result = await assistant.advance_step(None, "I did something")
    assert "haven't started" in result.lower()


# --- Escalation dossier -------------------------------------------------------


async def test_escalate_builds_dossier_and_degrades_without_recipient(
    stub_moss, monkeypatch
) -> None:
    # No recipient configured -> the bridge isn't called and escalate degrades.
    for var in ("SERVICE_DESK_PHONE", "TECH_PHONE", "DEMO_PHONE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        agent_module,
        "MOCK_INSTRUMENTS",
        {DEVICE_ID: {"model": "Helix HX-220", "serial": DEVICE_ID, "firmware": "4.2.1"}},
    )
    assistant = Assistant(device_id=DEVICE_ID)
    assistant._session = RemediationSession(
        fault_code="E-101",
        description="probe clog",
        severity="operator",
        steps=["a", "b"],
        safety="gloves",
        attempts=[{"step_number": 1, "step": "a", "outcome": "no change"}],
    )

    result = await assistant.escalate_to_service(None)

    # Without a recipient it prepares (does not claim to send) and reads a summary.
    assert "prepared" in result.lower()
    assert "E-101" in result
    assert assistant._session.escalated is True

    # The dossier itself carries the attempted steps and instrument identity.
    dossier = assistant._build_dossier(agent_module._instrument_for(DEVICE_ID))
    assert "E-101" in dossier
    assert "Steps attempted" in dossier
    assert DEVICE_ID in dossier


async def test_escalate_sends_dossier_via_imessage_bridge(stub_moss, monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_DESK_PHONE", "+15552223333")
    monkeypatch.setenv("ESCALATE_URL", "http://localhost:3000/api/escalate")
    monkeypatch.setenv("ESCALATE_SHARED_SECRET", "s3cret")
    monkeypatch.setattr(
        agent_module,
        "MOCK_INSTRUMENTS",
        {DEVICE_ID: {"model": "Helix HX-220", "serial": DEVICE_ID, "firmware": "4.2.1"}},
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

    assistant = Assistant(device_id=DEVICE_ID)
    assistant._session = RemediationSession(
        fault_code="E-707",
        description="pump failure",
        severity="service",
        steps=[],
        safety="service only",
    )
    monkeypatch.setattr(agent_module.httpx, "AsyncClient", _FakeAsyncClient)

    result = await assistant.escalate_to_service(None)

    # POSTs the dossier to the Next.js iMessage bridge with the recipient + secret.
    assert "messaged" in result.lower()
    assert sent["url"].endswith("/api/escalate")
    assert sent["json"]["to"] == "+15552223333"
    assert "E-707" in sent["json"]["body"]
    assert sent["headers"]["x-escalate-secret"] == "s3cret"


# --- Per-instrument memory ----------------------------------------------------


async def test_remember_observation_writes_with_device_metadata(stub_moss) -> None:
    assistant = Assistant(device_id=DEVICE_ID)
    result = await assistant.remember_observation(
        None, "Probe clogs weekly on this box."
    )
    assert isinstance(result, str) and result

    assert len(assistant._moss.add_docs_calls) == 1
    index, docs, _opts = assistant._moss.add_docs_calls[0]
    assert index == agent_module.MEMORY_INDEX
    assert docs[0].metadata == {"device_id": DEVICE_ID}
    assert "Probe clogs weekly" in docs[0].text
    assert docs[0].id.startswith(f"{DEVICE_ID}-")


async def test_recall_history_filters_by_device_id(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, device_id=DEVICE_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc("2026-05-01: E-101 cleared by reseating the probe."),
            _FakeDoc("2026-04-12: replaced diluent pack."),
        ]
    )

    result = await assistant.recall_history(None, "probe issues")

    assert "reseating the probe" in result
    index, _query, options = assistant._moss.query_calls[0]
    assert index == agent_module.MEMORY_INDEX
    assert options.top_k == 5
    assert options.filter == {
        "field": "device_id",
        "condition": {"$eq": DEVICE_ID},
    }
    assert len(room.local_participant.published) == 1
