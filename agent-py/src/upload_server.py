"""Document upload platform — ingest docs into the Moss `knowledge` index.

A tiny self-contained web app: drag-drop a PDF / text / markdown file and it is
parsed, chunked, and added to the same Moss `knowledge` index the voice agent
searches. So you can "bring your own docs" (a lease, a property handbook, a
service manual) and the agent can ground on them immediately — no redeploy.

Run from the repo root:

    pnpm moss:upload            # -> http://localhost:8080

Needs MOSS_PROJECT_ID / MOSS_PROJECT_KEY in agent-py/.env.local (same as the
agent). The `knowledge` index must already exist (run `pnpm moss:index` once).

PDF text is extracted with pypdf (fine for text-based PDFs). For messy/scanned
PDFs, swap in Unsiloed parsing at the marked point.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import uuid
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from moss import DocumentInfo, MossClient, QueryOptions
from pypdf import PdfReader

AGENT_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_PATH = AGENT_DIR / "knowledge.json"
load_dotenv(AGENT_DIR / ".env.local")

KNOWLEDGE_INDEX = os.getenv("MOSS_INDEX_NAME", "knowledge")
MEMORY_INDEX = os.getenv("MOSS_MEMORY_INDEX_NAME", "memory")
DEFAULT_TENANT_ID = "tenant_1"
UPLOAD_PORT = int(os.getenv("UPLOAD_PORT", "8080"))
# Target chunk size (characters). Chunks split on paragraph/sentence boundaries.
CHUNK_CHARS = int(os.getenv("UPLOAD_CHUNK_CHARS", "1100"))

# Qwen (same brain as the voice agent) for the iMessage text channel.
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")

# Property-manager emergency alerts (outbound iMessage via the Spectrum service).
ESCALATE_URL = os.getenv("ESCALATE_URL", "http://localhost:8787/send")
ESCALATE_SHARED_SECRET = os.getenv("ESCALATE_SHARED_SECRET")
PM_PHONE = os.getenv("PM_PHONE") or os.getenv("SERVICE_DESK_PHONE")


async def _alert_pm(body: str) -> bool:
    """Notify the property manager via the Spectrum send service. Best-effort:
    returns False if no PM number is set or the send is blocked/unreachable."""
    if not PM_PHONE:
        return False
    headers = {"x-escalate-secret": ESCALATE_SHARED_SECRET} if ESCALATE_SHARED_SECRET else {}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                ESCALATE_URL, json={"to": PM_PHONE, "body": body}, headers=headers, timeout=20.0
            )
        return r.status_code == 200
    except Exception:
        return False

app = FastAPI(title="Mira Knowledge Service")
# Allow the dashboard (Next dev on any localhost port) to read/upload.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_moss = MossClient(os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY"))

# In-memory record of docs uploaded this session (the seeded knowledge.json docs
# are listed separately). Lets the KB view show what's been added live.
_uploaded: list[dict] = []


def _extract_text(filename: str, raw: bytes) -> str:
    """Pull plain text from an uploaded file (pdf / txt / md)."""
    name = filename.lower()
    if name.endswith(".pdf"):
        # --- Unsiloed swap point: replace this block with an Unsiloed parse for
        #     messy/scanned PDFs (layout-aware, tables, OCR). ---
        reader = PdfReader(io.BytesIO(raw))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    # txt / md / anything decodable as text
    return raw.decode("utf-8", errors="replace")


def _chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split text into ~size-char chunks on paragraph, then sentence, boundaries."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}" if buf else para
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= size:
            buf = para
            continue
        # Paragraph itself too long — split on sentence boundaries.
        sentence = ""
        for piece in re.split(r"(?<=[.!?])\s+", para):
            if len(sentence) + len(piece) + 1 <= size:
                sentence = f"{sentence} {piece}".strip()
            else:
                if sentence:
                    chunks.append(sentence)
                sentence = piece
        if sentence:
            buf = sentence
    if buf:
        chunks.append(buf)
    return chunks


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE


@app.post("/api/ingest")
async def ingest(files: list[UploadFile] = File(...)) -> JSONResponse:  # noqa: B008 - FastAPI dependency default
    if not os.getenv("MOSS_PROJECT_ID") or not os.getenv("MOSS_PROJECT_KEY"):
        return JSONResponse(
            {"ok": False, "error": "Moss not configured in agent-py/.env.local"},
            status_code=503,
        )

    results: list[dict] = []
    total_chunks = 0
    for upload in files:
        raw = await upload.read()
        try:
            text = _extract_text(upload.filename or "file", raw)
        except Exception as exc:
            results.append({"file": upload.filename, "ok": False, "error": str(exc)})
            continue

        chunks = _chunk(text)
        if not chunks:
            results.append(
                {"file": upload.filename, "ok": False, "error": "no text extracted"}
            )
            continue

        source = upload.filename or "upload"
        batch_id = uuid.uuid4().hex[:8]
        docs = [
            DocumentInfo(
                id=f"{source}-{batch_id}-{i}",
                text=chunk,
                metadata={"source": source, "category": "uploaded"},
            )
            for i, chunk in enumerate(chunks)
        ]
        try:
            await _moss.add_docs(KNOWLEDGE_INDEX, docs)
            await _moss.load_index(KNOWLEDGE_INDEX)
        except Exception as exc:
            results.append({"file": source, "ok": False, "error": str(exc)})
            continue

        total_chunks += len(docs)
        _uploaded.append({"source": source, "chunks": len(docs)})
        results.append({"file": source, "ok": True, "chunks": len(docs)})

    return JSONResponse(
        {
            "ok": True,
            "index": KNOWLEDGE_INDEX,
            "total_chunks": total_chunks,
            "files": results,
        }
    )


@app.get("/api/kb")
async def kb() -> JSONResponse:
    """List what's in the knowledge base: the seeded docs (from knowledge.json)
    plus anything uploaded this session. Used by the dashboard Knowledge view.
    """
    seeded: list[dict] = []
    try:
        with KNOWLEDGE_PATH.open("r", encoding="utf-8") as handle:
            for entry in json.load(handle):
                if not isinstance(entry, dict):
                    continue
                meta = entry.get("metadata") or {}
                text = (entry.get("text") or "").strip()
                seeded.append(
                    {
                        "id": entry.get("id"),
                        "category": meta.get("category", "general"),
                        "topic": meta.get("topic", ""),
                        "preview": text[:240],
                    }
                )
    except (OSError, json.JSONDecodeError):
        pass

    return JSONResponse(
        {
            "ok": True,
            "index": KNOWLEDGE_INDEX,
            "seeded": seeded,
            "uploaded": _uploaded,
            "counts": {"seeded": len(seeded), "uploaded": len(_uploaded)},
        }
    )


# Step 1 — classify intent only (no facts/amounts, so JSON formatting is safe).
_CLASSIFY_SYS = (
    "Classify a resident's text message to a property manager. Decide if they are "
    "REPORTING A MAINTENANCE ISSUE (something broken or not working: a leak, no heat "
    "or AC, an appliance, plumbing, electrical, a lock, pests, etc.) or just ASKING A "
    "QUESTION. Respond with ONLY a JSON object, no markdown:\n"
    '{"is_maintenance": true or false, "issue": "<short description, or empty>", '
    '"urgency": "emergency" or "routine", "ack": "<one short, warm acknowledgement '
    'sentence — no facts, no ticket number>"}\n'
    "Emergency = a major leak or flooding, no heat in cold weather, a gas smell, no "
    "power, or a lockout."
)

# Step 2 — answer a question, grounded. Kept separate from classification so the
# model stays faithful to the retrieved figures (it hallucinates when also asked
# to format JSON).
_REPLY_SYS = (
    "You are Mira, a resident-support assistant for a property-management company, "
    "replying over text. Use the conversation so far together with the context "
    "below. For policy facts, quote any amounts, fees, dates, and numbers EXACTLY "
    "as written in the context — never approximate, round, or substitute a typical "
    "figure. If a specific phone number, email address, or link is NOT written in "
    "the context, do NOT make one up — instead tell the resident to reply here or "
    "use the resident portal. Never invent names or amounts either. For things "
    "established earlier in the conversation (like a work order number the resident "
    "was given), use that. If neither covers it, say you're not sure and to contact "
    "the office. Keep it to 1-3 plain-text sentences."
)


def _parse_json_object(text: str) -> dict | None:
    """Best-effort parse of a JSON object from an LLM reply (strips code fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return None
    with contextlib.suppress(json.JSONDecodeError):
        obj = json.loads(t[start : end + 1])
        return obj if isinstance(obj, dict) else None
    return None


@app.post("/api/answer")
async def answer(payload: dict = Body(...)) -> JSONResponse:  # noqa: B008 - FastAPI body
    """Answer a resident's text, grounded in the Moss knowledge base. Detects
    maintenance issues and creates a work-order ticket. Used by the iMessage
    channel (dummy-moss) so texting Mira matches the voice agent."""
    question = (payload.get("question") or "").strip()
    tenant_id = (payload.get("tenant_id") or DEFAULT_TENANT_ID).strip()
    if not question:
        return JSONResponse({"ok": False, "error": "no question"}, status_code=400)

    # Prior turns of THIS conversation (so follow-ups like "what was my work
    # order number?" resolve even many turns later). Capped to the recent window.
    history: list[dict] = []
    for m in (payload.get("history") or [])[-16:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
            content = (m.get("content") or "").strip()
            if content:
                history.append({"role": m["role"], "content": content})

    # Grounding from Moss: the lease/handbook (knowledge) PLUS this resident's
    # memory (scoped by tenant_id) — the same retrieval the voice agent uses, so
    # call and text share one grounded brain.
    context = ""
    try:
        kb = await _moss.query(KNOWLEDGE_INDEX, question, QueryOptions(top_k=3))
        snippets = [(getattr(d, "text", "") or "").strip() for d in (kb.docs or [])]
        context = "\n\n".join(s for s in snippets if s)
    except Exception:
        pass
    try:
        mem = await _moss.query(
            MEMORY_INDEX,
            question,
            QueryOptions(
                top_k=5,
                filter={"field": "tenant_id", "condition": {"$eq": tenant_id}},
            ),
        )
        facts = [(getattr(d, "text", "") or "").strip() for d in (mem.docs or [])]
        facts = [f for f in facts if f]
        if facts:
            context += "\n\nWhat we already know about this resident:\n" + "\n".join(facts)
    except Exception:
        pass

    # Without a Qwen key, fall back to the top retrieved snippet.
    if not QWEN_API_KEY:
        ans = (
            context.split(". ", 1)[-1][:300]
            if context
            else "I'm not set up to answer that right now — please contact the office."
        )
        return JSONResponse({"ok": True, "messages": [ans]})

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    # Step 1: classify intent (cheap, JSON, no facts).
    try:
        cls = await client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYS},
                *history,
                {"role": "user", "content": question},
            ],
            max_tokens=120,
            temperature=0,
        )
        parsed = _parse_json_object(cls.choices[0].message.content.strip()) or {}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=502)

    if parsed.get("is_maintenance"):
        wo = f"WO-{uuid.uuid4().hex[:6].upper()}"
        issue = (parsed.get("issue") or "your maintenance issue").strip()
        ack = (parsed.get("ack") or "Thanks for letting me know — I'm on it.").strip()
        emergency = str(parsed.get("urgency", "routine")).lower() == "emergency"

        # Message 1: acknowledgement. Message 2: the ticket (sent separately).
        if emergency:
            pm_sent = await _alert_pm(
                f"EMERGENCY at the property — {issue}. Work order {wo}, reported via Mira "
                "just now. Please dispatch immediately."
            )
            pm_line = (
                "I've alerted the property manager."
                if pm_sent
                else "I'm escalating this to the property manager."
            )
            ticket = (
                f"I've logged emergency work order {wo} for {issue}. A technician is being "
                f"dispatched right now — {pm_line} If anyone is in danger or you smell gas, "
                "call 911 first."
            )
        else:
            ticket = (
                f"I've logged work order {wo} for {issue}. The property manager has been "
                "notified and a technician will be scheduled within two to three business "
                "days. Reply here with any details or photos."
            )

        return JSONResponse(
            {
                "ok": True,
                "messages": [ack, ticket],
                "work_order": wo,
                "is_maintenance": True,
                "emergency": emergency,
            }
        )

    # Step 2: it's a question — answer it, grounded and faithful to the context.
    try:
        ans = await client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": f"{_REPLY_SYS}\n\nContext:\n{context}"},
                *history,
                {"role": "user", "content": question},
            ],
            max_tokens=200,
            temperature=0,
        )
        reply = ans.choices[0].message.content.strip()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=502)

    return JSONResponse({"ok": True, "messages": [reply], "is_maintenance": False})


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Moss Document Uploader</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
         background:#0b0d10; color:#e6e8eb; margin:0; display:flex;
         min-height:100vh; align-items:center; justify-content:center; }
  .card { width:min(560px,92vw); background:#14171c; border:1px solid #232830;
          border-radius:16px; padding:28px; box-shadow:0 8px 40px rgba(0,0,0,.4); }
  h1 { font-size:18px; margin:0 0 4px; }
  p.sub { color:#9aa3ad; margin:0 0 20px; font-size:13px; }
  #drop { border:2px dashed #2c333d; border-radius:12px; padding:38px 16px;
          text-align:center; cursor:pointer; transition:border-color .15s, background .15s; }
  #drop.hover { border-color:#1fd5f9; background:#0f1b1f; }
  #drop strong { color:#1fd5f9; }
  .muted { color:#6b747e; font-size:12px; }
  #out { margin-top:18px; font-size:13px; }
  .row { display:flex; justify-content:space-between; padding:8px 12px; border-radius:8px;
         background:#0f1216; border:1px solid #232830; margin-top:8px; }
  .ok { color:#46d39a; } .err { color:#ff6b6b; }
  input[type=file]{ display:none; }
</style>
</head>
<body>
  <div class="card">
    <h1>Moss Document Uploader</h1>
    <p class="sub">Drop a PDF, text, or markdown file. It's parsed, chunked, and added to the
       <code>knowledge</code> index — searchable by the agent immediately.</p>
    <label id="drop" for="file">
      <div>Drag &amp; drop, or <strong>click to choose</strong></div>
      <div class="muted">.pdf · .txt · .md — multiple allowed</div>
    </label>
    <input id="file" type="file" multiple accept=".pdf,.txt,.md,.markdown,text/plain" />
    <div id="out"></div>
  </div>
<script>
  const drop = document.getElementById('drop');
  const input = document.getElementById('file');
  const out = document.getElementById('out');
  ['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('hover'); }));
  ['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('hover'); }));
  drop.addEventListener('drop', ev => { if (ev.dataTransfer.files.length) upload(ev.dataTransfer.files); });
  input.addEventListener('change', () => { if (input.files.length) upload(input.files); });

  async function upload(files) {
    out.innerHTML = '<div class="muted">Uploading & indexing…</div>';
    const fd = new FormData();
    for (const f of files) fd.append('files', f);
    try {
      const res = await fetch('/api/ingest', { method:'POST', body: fd });
      const data = await res.json();
      if (!data.ok) { out.innerHTML = '<div class="row err">'+(data.error||'failed')+'</div>'; return; }
      out.innerHTML = '<div class="muted">Added '+data.total_chunks+' chunks to “'+data.index+'”.</div>'
        + data.files.map(f => '<div class="row"><span>'+f.file+'</span><span class="'+(f.ok?'ok':'err')+'">'
          + (f.ok ? (f.chunks+' chunks') : f.error) + '</span></div>').join('');
    } catch (e) {
      out.innerHTML = '<div class="row err">'+e+'</div>';
    }
  }
</script>
</body>
</html>"""


def main() -> None:
    print(
        f"Document uploader on http://localhost:{UPLOAD_PORT}  (index: {KNOWLEDGE_INDEX})"
    )
    uvicorn.run(app, host="0.0.0.0", port=UPLOAD_PORT, log_level="warning")


if __name__ == "__main__":
    main()
