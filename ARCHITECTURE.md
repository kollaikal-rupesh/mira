# Mira — architecture

Mira is one assistant reachable on two channels (voice + iMessage), both grounded in a single Moss knowledge base.

## The core idea

Grounding a live conversation means retrieving the right document *while the person is still talking*. At 200–500 ms (typical vector DBs) that breaks the turn, so voice agents ship ungrounded. Moss retrieves in **<10 ms**, so every turn can be grounded without a stutter. Everything else is built around that.

## The loop

```
   📞 Voice (WebRTC)                          💬 iMessage
        │                                          │
   LiveKit · ASR                           Photon / Spectrum
        │                                  inbound message loop
        │                                          │
        ▼                                          ▼
   Qwen (LLM)  ◀── grounded context ──┐     /api/answer (Moss + Qwen)
        │                              │            │
   MiniMax (TTS)                       │     reply (ack + ticket)
        │                              │            │
        └──────────────┬───────────────┴────────────┘
                        ▼
              ┌────────────────────────┐
              │   M O S S  (<10 ms)     │
              │  knowledge: lease +     │
              │   handbook (+ uploads)  │
              │  memory: per-resident   │
              └────────────────────────┘
```

## Components

- **`agent-py/`** — the LiveKit voice agent (`src/agent.py`): persona, tools, per-resident memory, work-order creation. Also hosts the document uploader + `/api/answer` (`src/upload_server.py`), the Moss-grounded brain shared with the text channel.
- **`messaging/`** — the Photon/Spectrum service: receives inbound iMessages, calls `/api/answer`, replies in-thread; also exposes an outbound `/send`.
- **`frontend/`** — the operator dashboard: live call, call logs (every Moss lookup + latency), and the knowledge browser/uploader.
- **`knowledge.json`** — the seed lease + handbook; the single source for the Moss `knowledge` index.

## Grounding & memory (Moss)

| Index | Contents | Scope |
|---|---|---|
| `knowledge` | lease + property handbook + any uploaded PDFs | shared |
| `memory` | facts and resolved issues | per resident (`tenant_id` filter) |

Every retrieval is published to the dashboard with its matched chunk, relevance score, and latency — so the speed is visible, not just claimed.

## Models (swappable)

Mira runs **Qwen** as the brain (LLM) and **MiniMax** for voice (TTS), with real-time transcription and transport handled by **LiveKit** (LiveKit Inference). Configure with `QWEN_*` / `MINIMAX_API_KEY` in `agent-py/.env.local`.

## Resolve, don't deflect

A maintenance message is classified (question vs. issue, routine vs. emergency). Issues open a work-order ticket; emergencies (leak, no heat, gas, lockout) get immediate dispatch and property-manager escalation rather than a multi-day queue.
