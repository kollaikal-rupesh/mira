<div align="center">

# 🏠 Mira

### The AI property manager your residents can **call _or_ text**

**One brain. Two channels. No hold music, no portal, no 9‑to‑5.**

`LiveKit` · `Moss` · `Qwen` · `MiniMax` · `Photon` · `Deepgram`

</div>

---

> **Voice was solved. Retrieval was the bottleneck. [Moss](https://usemoss.dev) removed it.**
> Mira is what you build the moment grounding a *live* conversation becomes free.

## The 10‑second pitch

A resident **calls** Mira or **texts** her. Same assistant, same brain, same knowledge. She answers rent, lease, and maintenance questions **grounded in the building's real documents**, remembers the resident across conversations, and actually **resolves** the issue — opening a maintenance work order and escalating emergencies on the spot.

## Why this couldn't exist until now

Grounding a **voice** conversation means fetching the right lease clause *mid‑sentence*. Every vector DB adds 200–500 ms — enough to break the turn, so most voice agents ship ungrounded and hallucinate. **Moss retrieves in <10 ms**, so Mira grounds **every single turn** without a stutter. That one fact is the entire product.

```
Retrieval latency budget:  ████████████████████  ~1 second to first word
Moss's slice of it:        ▏ <10 ms  (≈1%)  ← no longer the bottleneck
```

## What Mira does

- 📞 **Call her** — real‑time voice over LiveKit (Qwen brain · MiniMax voice · Deepgram ears), grounded in Moss, replies in well under a second.
- 💬 **Text her** — iMessage via Photon: *"When's rent due?" "Can I sublet?" "Deposit back?"* → grounded answers, same KB.
- 📄 **Knows your building** — every answer cited from the **actual lease + handbook**. Drag‑drop a PDF and it's searchable instantly.
- 🔧 **Resolves, doesn't deflect** — detects a maintenance issue, opens a **work‑order ticket**, confirms by text.
- 🚨 **Emergencies** — a leak or gas smell triggers **immediate dispatch** + property‑manager escalation, not a 3‑day queue.
- 🧠 **Remembers** — per‑resident memory that carries across calls *and* texts.

## One brain, two channels

```
        📞 Voice (web / WebRTC)                 💬 iMessage
                │                                    │
          LiveKit Agents                      Photon · Spectrum
        Deepgram → Qwen → MiniMax              inbound → reply
                │                                    │
                └───────────────┬────────────────────┘
                                ▼
                   ┌─────────────────────────┐
                   │   M O S S   (<10 ms)     │   ← the hero
                   │  lease · handbook · law  │     grounds every turn
                   │  per‑resident memory     │
                   └─────────────────────────┘
                                │
              answers · work‑order tickets · escalation
```

## Under the hood

| Layer | Tech | Role |
|---|---|---|
| **Retrieval** | **Moss** 🟢 | The hero. <10 ms grounding on the real lease/handbook — the only reason a voice agent can cite documents mid‑sentence. |
| **Voice transport + agents** | **LiveKit** | Real‑time WebRTC, turn detection, the agent runtime. |
| **Brain** | **Qwen** (Alibaba) | The reasoning LLM, via its OpenAI‑compatible endpoint. |
| **Voice** | **MiniMax** | Expressive, low‑latency TTS (`speech‑02‑turbo`). |
| **Ears** | **Deepgram** | Streaming STT (`nova‑3`) via LiveKit Inference. |
| **Messaging** | **Photon / Spectrum** | Native iMessage — residents text Mira and get Moss‑grounded replies. |

> Models are **env‑toggled**: drop the keys and the same agent falls back to LiveKit Inference (Gemini Flash + Cartesia) with zero code changes.

## The dashboard

A clean operator console (`localhost:3001`):
- **Call** — talk to Mira live.
- **Call Logs** — every knowledge lookup Mira made, with the document she grounded on, relevance score, and **Moss latency in ms**.
- **Knowledge** — browse the lease/handbook and **drag‑drop new documents** straight into the Moss index.

## See it in 90 seconds

1. **Open `localhost:3001` → Call** → *"When is rent due?"* — Mira answers from the lease; the panel shows the Moss hit in single‑digit ms.
2. **Knowledge tab** → drop in a property handbook PDF → ask about it on the next call. **Bring‑your‑own‑docs, no redeploy.**
3. **Text the line** → *"There's water leaking under my sink"* → Mira opens **work order WO‑###** and confirms by text.
4. **Emergency** → *"I smell gas"* → immediate dispatch + property‑manager escalation, with a safety‑first reply.

## Quickstart

```bash
pnpm setup            # install all apps + copy .env files
# fill in: LiveKit + Moss (required); Qwen + MiniMax + Photon (optional, for the full stack)
pnpm moss:index       # build the knowledge + memory indexes
pnpm dev              # voice agent + web dashboard + iMessage service
pnpm moss:upload      # (optional) the drag‑drop document uploader → :8080
```

Only **two** credentials are required to run — **LiveKit** and **Moss**. Everything else (STT/LLM/TTS) runs through LiveKit Inference with no extra keys until you opt into Qwen/MiniMax/Photon.

## Repo layout

```
├── agent-py/          # Python voice agent (LiveKit) + Moss tools + the doc/answer service
│   ├── src/agent.py            # Mira: persona, tools, per‑resident memory, work orders
│   ├── src/upload_server.py    # KB uploader + /api/answer (Moss‑grounded text brain)
│   └── knowledge.json          # lease + property handbook (single source of truth)
├── messaging/        # Photon (Spectrum) iMessage service — inbound Q&A + outbound
├── frontend/          # Next.js operator dashboard (Call · Call Logs · Knowledge)
└── DEMO.md · ARCHITECTURE.md   # the story and the design
```

---

<div align="center">

**Mira** — call it or text it. It already read the lease.

*Built on LiveKit · Moss · Qwen · MiniMax · Photon · Deepgram*

</div>
