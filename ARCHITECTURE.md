# Vera — Lab analyzer support agent · architecture

## North star

The hackathon's premise: **retrieval used to be the bottleneck; Moss made it
<10 ms, so it's effectively free.** We pick a domain where free retrieval doesn't
just speed up Q&A — it changes the *shape* of the product. A halted blood
analyzer isn't answered with one fact; it's *worked* through an ordered,
branching procedure, with grounding re-fetched at every step. That's only
sane when retrieval is free.

## The one idea that drives everything

**This is a stateful procedure-execution engine, not flat fact-retrieval.**

A support-billing bot answers each turn independently ("what's my balance?" →
look up → quote → done). A broken analyzer is the opposite: a fault code triggers
an ordered remediation procedure with gates ("did it clear? Y/N → different next
step"), safety interlocks, and a terminal decision — *resolved* or *escalate*.
The agent isn't answering questions; it's **driving a state machine through a
tech's gloved hands.** Everything below follows from that.

## The loop

```
        ┌──────────────────────── LiveKit room (local-first target) ─────────────────────┐
tech ──▶ Deepgram STT ──▶ [turn node] ──▶ brain ──▶ Minimax/Cartesia TTS ──▶ tech
audio        │               │             │
       (interim hyp.)   inject grounded    │   tools:
             │          step + state       │    read_instrument   ◀ EXACT device state (anti-hallucination)
             ▼               ▲             │    lookup_symptom     ◀ free-text symptom → fault code
   ┌──────── Moss (<10ms) ──┤             │    search_procedures  ◀ manual grounding
   │  knowledge (procedures +│            │    start_remediation  ─┐
   │   safety interlocks)    │            │    advance_step       ─┤ the state machine
   │  memory (per-instrument │            ▼    escalate_to_service ┘ ◀ dossier (the fallback)
   │   maintenance log)      │  live "Moss" panel ◀── moss_context msgs
   └─────────────────────────┘     ┌──── in-call STATE (RemediationSession) ────┐
                                    │ fault_code, step_idx, attempts[], outcomes │
                                    └────────────────────────────────────────────┘
```

## Single source of truth: `knowledge.json`

`knowledge.json` is read by **two** consumers and they must never drift:

- `create_index.py` ships each entry's `id`/`text`/`metadata` to the Moss
  `knowledge` index → powers `search_procedures`, `lookup_symptom`, and the live
  grounding panel.
- `agent.py` loads the same entries' `fault_code`/`severity`/`steps`/`safety`
  into the `PROCEDURES` registry → drives the deterministic step-walker.

So Moss is the *semantic* layer (symptom→code, grounding, the speed story) and
`PROCEDURES` is the *deterministic* layer (the exact ordered steps). One file,
no divergence.

## The anti-hallucination property (the trust property)

Codes, part numbers, reagent lots, torque specs, QC values come **only** from
`read_instrument` (device telemetry, the system of record) or the procedure text
— never from the LLM's memory. The LLM may *phrase* them, but the values are
code-supplied. Handing a tech a wrong part number is a real failure, so this is
load-bearing, not a flourish. Demo it explicitly.

## The safety gate (the judgment property)

`start_remediation` queries severity before walking. Service-only faults
(**E-707** sealed pneumatics, **E-808** laser/optics, **E-901** mainboard) never
enter a fix flow — the agent refuses to coach opening the instrument and routes
straight to escalation. *Refusing the unsafe fix and producing a clean dossier is
arguably a stronger judge moment than a successful one* — it shows the agent
knows its limits.

## How "retrieval is free" is woven in (procedure-flavored)

| Free-retrieval move | Absurd at 200 ms, trivial at <10 ms |
|---|---|
| **Warm at session start** | `load_index` on both indexes so step one is instant |
| **Read the instrument before greeting** | the tech's first words are met with "I see your HX-220, fault E-101" |
| **Re-ground at every step transition** | an N-step procedure = N retrievals, each quoting the exact spec |
| **Symptom→code reverse lookup** | free-text "it's not aspirating" → candidate codes (`lookup_symptom`) |
| **Per-instrument history recall** | "last time E-101 hit this serial, reseating the probe fixed it" |

## Index design

| Index | Lifetime | Source | Filter |
|---|---|---|---|
| `knowledge` | static | HX-220 fault-code procedures + safety docs (`knowledge.json`; real service PDFs via **Unsiloed** as a drop-in) | — |
| `memory` | per-instrument, cross-session | written at runtime on resolve/escalate | `device_id == serial` |
| instrument telemetry | live | `read_instrument` (mock now → device API / LIS) | by serial |

Per-instrument memory turns the agent into a living maintenance log: each
resolved fault is written back, so the next call on that serial starts smarter.
A `fleet` index (cross-site incidents — "3 sites hit E-101 after firmware 4.2")
is the obvious next index; still one `asyncio.gather`.

## Latency budget (the slide that wins)

| Stage | Budget | Note |
|---|---|---|
| Deepgram STT (final) | ~150–300 ms | LiveKit Inference |
| **Moss retrieval** | **<10 ms** | re-run every step — still ~1–2% of budget |
| LLM time-to-first-token | ~75–300 ms | brain |
| TTS time-to-first-byte | ~100–200 ms | streaming |
| **Total to first audio** | **well under 1 s** | feels human, hands-free |

## The brain: why local + a two-brain split

Local-first isn't a stretch goal here — a HIPAA lab on a locked-down hospital
network with proprietary service data **requires** it. That's the case for
**MiniMax M2.7** (diagnostic reasoning) as the brain and Moss's on-device
retrieval.

The non-obvious refinement: **reasoning models and voice latency fight.** M2.7's
strength is thinking, which blows the <300 ms first-token budget. So route by
turn type:

- **Fast model** for the conversational loop ("did the flag clear?", "open the
  reagent door") — 90% of turns, must be instant.
- **M2.7** only for the hard work: ambiguous symptom→code triage and dossier
  synthesis — invoked while the tech is physically doing a step, so a 1–2 s think
  is invisible.

A gateway (**TrueFoundry**) sits here for routing, fallback, and cost/obs. The
current build runs everything on LiveKit Inference so it demos out of the box;
`src/agent.py` marks the brain and TTS swap points.

## Sponsor map

| Sponsor | Role | Required? |
|---|---|---|
| **LiveKit** | transport + agent framework + Inference | core |
| **Moss** | retrieval everywhere — grounding, symptom map, per-instrument memory (the hero) | core |
| **Deepgram** | STT (via LiveKit Inference) | core |
| **Minimax** | M2.7 diagnostic brain + expressive TTS (the local-first story) | core (voice + brain) |
| **Unsiloed** | parse real service-manual PDFs → `knowledge` index | high-value add |
| **TrueFoundry** | gateway for two-brain routing, fallback, observability | prize add |
| **AWS** | deploy the agent worker | optional |

## Build order

**Core demo (done):**
1. ✅ Fault-code procedure corpus + safety docs (`knowledge.json`).
2. ✅ `RemediationSession` state machine + tools + safety gate (`agent.py`).
3. ✅ `read_instrument` telemetry (exact-value grounding) + per-instrument memory.
4. ✅ Offline test suite (retrieval, state machine, safety gate, escalation).
5. ✅ Frontend rebrand + live Moss panel reused.

**Differentiators (in ROI order):**
6. **Unsiloed** ingestion: a real analyzer service PDF → `knowledge`, live.
7. **MiniMax** TTS + **M2.7** brain swap (the local-first pitch made real).
8. **Two-brain routing** behind TrueFoundry (fast loop + M2.7 triage/dossier).
9. **Speculative retrieval** on interim transcripts (prefetch the "if this fails"
   branch while the tech performs the current step).
10. **Fleet index** for cross-site incident intelligence.

## What stays from the starter

The LiveKit spine, the Moss client + index pattern, per-scope `memory` isolation
(now by `device_id`), and `_publish_moss_context` → `useMossContextEvents` live
panel. We extended the architecture (added state + a safety gate + telemetry);
we did not replace the spine.
