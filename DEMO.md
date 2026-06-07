# Vera — the lab analyzer support agent that *gets the instrument back online* (powered by Moss)

**Track:** Support · **Built on:** LiveKit Agents + Moss + Photon (iMessage)
**Thesis of the hackathon:** voice is solved; retrieval was the bottleneck. **Moss removes it.**
So we make Moss the hero in a setting where retrieval *being free* changes the
product: a hands-free voice agent that walks a lab tech through fixing a halted
blood analyzer, grounding **every step** in the service manual in real time
(<10 ms) and **never inventing a fault code or part number** — then either gets
the box running or escalates with a complete dossier.

## What it is

Vera is a technical-support voice agent for the (fictional) **Helix HX-220
hematology analyzer**. A technician standing at a halted instrument — gloved
hands, busy — talks to it. On a live call it:

1. **Reads the instrument's real state** (`read_instrument`, stand-in for device
   telemetry) — active fault code, error log, reagent levels, last QC, firmware —
   and quotes those figures **exactly**, never estimated.
2. **Triages the fault**: a code goes straight to its procedure; a free-text
   symptom ("it's not drawing sample") is mapped to candidate codes via Moss
   (`lookup_symptom`).
3. **Walks the documented fix one step at a time** (`start_remediation` →
   `advance_step`), holding in-call state and grounding each instruction in the
   manual (`search_procedures` → `knowledge` index).
4. **Knows when to stop**: service-only faults (sealed pneumatics, the laser, the
   mainboard) are **refused at a safety gate** — it won't have you open the box.
5. **Resolves or escalates**: clears the fault and logs the fix to *this
   instrument's* history (`memory`, scoped by serial), or generates an
   **escalation dossier** (`escalate_to_service`) — every step tried + the live
   instrument state — and iMessages it to the field engineer (via Photon).
6. **Shows Moss working live** — every retrieval streams to the frontend panel
   with the chunk text, relevance score, and **latency in ms**.

Why it wins the track: it's a support agent that **instantly pulls docs *and*
device history** and *acts* — and it does it in a setting where voice (hands
busy) and local-first (HIPAA lab, proprietary service data, locked-down hospital
network) aren't nice-to-haves, they're requirements.

## The 90-second demo script

> Demo box (`MOCK_INSTRUMENTS["HX220-SN-4471"]`): Helix HX-220, firmware 4.2.1,
> active fault **E-101** (aspiration probe clog), reagents fine, last QC passed.

1. **Tech:** "Vera, the analyzer just halted."
   → Vera calls `read_instrument`: *"I see your HX-220, serial four-four-seven-one.
   It's showing fault E one zero one — an aspiration probe clog. Want to work it?"*
   (panel shows the instrument read)
2. **Tech:** "Yeah."
   → `start_remediation("E-101")` → Moss grounds the procedure in **single-digit ms**
   (watch the panel) → *"Safety first: gloves on, the probe area is a biohazard
   zone. Step one of six: put the analyzer in Standby. Tell me when that's done."*
3. **Tech** (after a couple steps): "Ran Probe Clean — the flag's gone."
   → `advance_step(..., fault_cleared=true)` → *"That cleared E one zero one —
   I've logged the fix to this analyzer's history. Run a QC before you load
   samples."* **The vendor service call just got deflected.**
4. **The escalation beat** (switch to `HX220-SN-4490`, active fault **E-707**):
   **Tech:** "This other one's showing E-707."
   → `start_remediation("E-707")` hits the **safety gate**: *"E seven oh seven is a
   sealed-system pneumatic fault — there's no operator fix and I won't have you
   open the instrument. Leave it in Standby."* → `escalate_to_service` → phone
   buzzes with the dossier → *"I've sent the field engineer the serial, firmware,
   the fault, and the current state — they'll arrive knowing exactly what's wrong."*

Punchline for judges: *"Every step on that call was grounded in the manual in
under ten milliseconds — and the one thing it refused to do is the thing that
keeps a tech safe. That's what retrieval being free buys you."*

## Run it

```bash
# from repo root (starter/)
pnpm setup                         # installs frontend + agent, copies .env files
lk app env -w agent-py             # LiveKit creds (or paste into agent-py/.env.local)
# paste MOSS_PROJECT_ID / MOSS_PROJECT_KEY into agent-py/.env.local
# (optional, for the iMessage send) paste PROJECT_ID / PROJECT_SECRET into
#   dummy-moss/.env, and SERVICE_DESK_PHONE / TECH_PHONE (or DEMO_PHONE) into
#   agent-py/.env.local
pnpm moss:index                    # builds the `knowledge` (procedures) + `memory` indexes
pnpm dev                           # agent + frontend on http://localhost:3000
```

Terminal-only smoke test (no frontend): `pnpm agent:py:console`.

## What we changed vs. the stock starter

| File | Change |
|---|---|
| `agent-py/knowledge.json` | Support KB → **HX-220 fault-code procedures** (E-101 … E-901) + safety/interlock docs. Each entry carries ordered `steps` so it's the single source for both Moss grounding and the in-call state machine. |
| `agent-py/src/agent.py` | Persona → Vera; added the `RemediationSession` state machine, `MOCK_INSTRUMENTS` telemetry, and tools `read_instrument`, `lookup_symptom`, `start_remediation`, `advance_step`, `escalate_to_service`, plus per-instrument `recall_history` / `remember_observation`. **Safety gate** refuses service-only faults. Kept the live `moss_context` panel intact. |
| `agent-py/src/create_index.py` | Memory seed scoped by `device_id` (per-instrument). |
| `agent-py/tests/test_moss.py` | Rewritten: covers retrieval, the state machine, the safety gate, escalation/dossier, and per-instrument memory (offline). |
| `frontend/` | App branding (Vera / Helix), panel header → "Service Manual · Moss Retrieval", welcome copy. |
| `dummy-moss/` | **New Spectrum (Photon) send service** — outbound iMessage on `localhost:8787/send`, scaffolded via `create-spectrum-project` and adapted into an HTTP send endpoint. |

**Messaging (Photon iMessage):** Photon's send path is TypeScript-only (no
Python/REST endpoint), so the Python agent POSTs `{to, body}` to the standalone
Spectrum send service (`dummy-moss/`), which sends it via the `spectrum-ts` SDK.
Vera iMessages the field engineer the escalation dossier and iMessages the tech a
resolution receipt; both degrade to reading the message aloud when Photon or a
recipient isn't configured.

## Why local-first is the spine here (not a stretch)

Aurora's on-prem mode was a talking point. For a HIPAA lab on a locked-down
hospital network, with proprietary instrument service data, **local is a hard
requirement** — which is exactly where MiniMax M2.7's diagnostic reasoning as the
brain and Moss's on-device retrieval shine. The current build runs on LiveKit
Inference so it demos out of the box; `src/agent.py` marks the **MiniMax M2.7
brain** and **MiniMax TTS** swap points, and the natural next step is a two-brain
split (a fast model for the turn-by-turn loop, M2.7 for triage + dossier
synthesis) behind a gateway. See `ARCHITECTURE.md`.

## Tests

```bash
cd agent-py
LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=devsecret LIVEKIT_URL=ws://localhost:7880 \
  uv run pytest tests/test_moss.py -q   # offline, no Moss/Photon creds needed
```
