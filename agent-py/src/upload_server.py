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

import io
import os
import re
import uuid
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from moss import DocumentInfo, MossClient
from pypdf import PdfReader

AGENT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(AGENT_DIR / ".env.local")

KNOWLEDGE_INDEX = os.getenv("MOSS_INDEX_NAME", "knowledge")
UPLOAD_PORT = int(os.getenv("UPLOAD_PORT", "8080"))
# Target chunk size (characters). Chunks split on paragraph/sentence boundaries.
CHUNK_CHARS = int(os.getenv("UPLOAD_CHUNK_CHARS", "1100"))

app = FastAPI(title="Moss Document Uploader")
_moss = MossClient(os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY"))


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
        results.append({"file": source, "ok": True, "chunks": len(docs)})

    return JSONResponse(
        {
            "ok": True,
            "index": KNOWLEDGE_INDEX,
            "total_chunks": total_chunks,
            "files": results,
        }
    )


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
