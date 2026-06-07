"""Shared work-order store — a tiny JSON-file-backed log of maintenance tickets.

Mira opens work orders from two places: the voice agent (`create_work_order` in
`agent.py`) and the iMessage text channel (`/api/answer` in `upload_server.py`).
Neither used to persist anything, so there was nothing for the dashboard to show.

This module gives both a single, dependency-free place to record a ticket and to
list them back. Records are appended to `agent-py/work_orders.json` (newest read
first), so a work order opened over the phone shows up in the same list as one
opened over text. Good enough for the demo; swap for a real DB when needed.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = Path(os.getenv("WORK_ORDERS_PATH", str(AGENT_DIR / "work_orders.json")))

# Writes from the agent and the web server can interleave; guard the file.
_lock = threading.Lock()


def new_id() -> str:
    """Mint a work-order id, e.g. `WO-3F9A1C`."""
    return f"WO-{uuid.uuid4().hex[:6].upper()}"


def _read() -> list[dict]:
    try:
        with STORE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_work_order(
    *,
    wo_id: str,
    summary: str,
    urgency: str = "routine",
    channel: str = "voice",
    tenant_id: str | None = None,
    unit: str | None = None,
) -> dict:
    """Append a work order and return the stored record.

    Args:
        wo_id: The ticket id (use `new_id()` if you don't already have one).
        summary: Short description of the issue and its location.
        urgency: "routine" (default) or "emergency".
        channel: Where it came from — "voice" or "text".
        tenant_id: Resident id, when known.
        unit: Unit/apartment, when known.
    """
    record = {
        "id": wo_id,
        "summary": summary.strip(),
        "urgency": "emergency" if urgency.strip().lower() == "emergency" else "routine",
        "channel": channel,
        "tenant_id": tenant_id,
        "unit": unit,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        orders = _read()
        orders.append(record)
        try:
            with STORE_PATH.open("w", encoding="utf-8") as handle:
                json.dump(orders, handle, indent=2)
        except OSError:
            pass
    return record


def list_work_orders() -> list[dict]:
    """Return every work order, newest first."""
    with _lock:
        orders = _read()
    orders.sort(key=lambda o: o.get("created_at") or "", reverse=True)
    return orders
