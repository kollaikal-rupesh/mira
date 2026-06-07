# Mira — demo script

Mira is an AI property manager residents can **call or text**. She answers from the building's real lease and handbook (grounded in Moss, <10 ms), remembers the resident, and resolves maintenance issues with a work-order ticket.

Run everything with `pnpm dev`, then open the dashboard at `localhost:3001`.

## 90-second run of show

**1. Ask on a call (grounding + speed)**
- Dashboard → **Call** → *"When is rent due, and what's the late fee?"*
- Mira answers from the lease. The **Call Logs** panel shows the Moss retrieval with the matched clause and latency in single-digit milliseconds.

**2. Bring your own docs (live KB)**
- **Knowledge** tab → drag-drop a property handbook PDF.
- Ask about it on the next turn — it's already searchable. No redeploy.

**3. Text the same assistant (second channel, one brain)**
- From a phone, text Mira: *"Can I sublet my apartment?"*
- She replies over iMessage, grounded in the same knowledge base as the call.

**4. Report a maintenance issue (it resolves, not deflects)**
- Text: *"There's water leaking under my kitchen sink."*
- Mira replies in two messages: an acknowledgement, then a **work-order ticket** (WO-######) with the next steps.

**5. Emergency (immediate, not a queue)**
- Text: *"I smell gas in my apartment."*
- Mira responds safety-first (call 911), logs an **emergency** work order with **immediate dispatch**, and escalates to the property manager — no 2–3 day wait.

## The one line for judges

> Every answer on that call and text was grounded in the building's real documents in under ten milliseconds. That's the only reason a voice agent can cite a lease mid-sentence — and it's what Moss makes possible.

## What's running

| Service | Port | What |
|---|---|---|
| Web dashboard | 3001 | Call · Call Logs · Knowledge |
| Voice agent | — | LiveKit worker (Deepgram → Qwen → MiniMax), grounded in Moss |
| iMessage | 8787 | Photon/Spectrum inbound + outbound |
| Doc uploader | 8080 | drag-drop PDFs → Moss index |
