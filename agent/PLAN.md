# Ruby's Red Rover v2 — Day Plan & Status

**Event:** Build YC's Next Unicorn — AWS Builder Loft, San Francisco
**Date:** April 29, 2026
**Snapshot taken:** 16:10 EDT
**Goal for today:** A live demo that rings a real phone, gated by real peer-to-peer grants, in front of a YC room.

---

## The headline story

> Ruby (20, cerebral palsy) says out loud "I want pizza." A Claude-orchestrated agent hears her — in **her own cloned voice** — confirms three peer-to-peer Bolo grants (her mom's MARS scopes, her own voice consent, her DJ friend Chantal's donated voice), then dials Folino's via Vapi using **Chantal's cloned voice**. Order placed. Mom notified. Audit trail written to Bolo.

Two real cloned voices. Three real grants. One agent loop. The trust layer is the moat.

---

## Original plan (set this morning)

| # | Track | What |
|---|-------|------|
| 1 | **Audio prep** | Extract MP3s from 11 family `.MOV` clips → produce a clean ~60s training file for ElevenLabs IVC |
| 2 | **Voice cloning** | Clone Ruby's voice (input side) and Chantal's voice (outbound-call side) on ElevenLabs |
| 3 | **Story / README** | YC-room-grade README — story-first, technically credible |
| 4 | **Server** | FastAPI + WebSocket + Claude Agent SDK orchestrator with tool dispatch |
| 5 | **Tools** | `bolo` / `voice_in` / `voice_out` / `phone` / `clone_voice` — each with mock fallbacks |
| 6 | **Web panel** | Single-file dark UI: grant tiles, live reasoning log, mood ring, phone-status card |
| 7 | **Bolo wiring** | Voice IDs live INSIDE grants (peer-to-peer), tools resolve via grant lookup, not env |
| 8 | **Live end-to-end** | Boot the server, type a phrase, watch grants light up, hear the phone ring |
| 9 | **Pitch / demo polish** | Final language passes, demo dry-run, fallback paths if a service fails |

---

## Status — what's actually done

### ✅ Complete

- **Audio extraction.** All 11 `.MOV` clips → MP3 in `C:/Users/trico/Downloads/Mars and Ruby/audio/`.
- **Ruby training file.** `agent/clips/ruby_training.mp3` (3.1 MB, 6:45) — concatenated for ElevenLabs IVC.
- **Ruby voice clone done.** ElevenLabs voice ID `0Hcx2s5tOXWeuyUi9ScQ`, dropped into `agent/.env`.
- **Chantal voice clone done.** ElevenLabs voice ID `vAfuZdldSpxthmIQYOBC`, dropped into `agent/.env`.
- **README.md** at `agent/README.md` — story-led, YC-room voice, 200 lines, architecture diagram, run instructions, 10-skill roadmap.
- **Server scaffolded** — `server/main.py` (FastAPI + WebSocket + `/demo/play`), `server/orchestrator.py` (Claude Agent SDK loop with extended thinking, parallel grant fan-out, Vapi handoff), `server/prompts/cp_aware.md`.
- **Tools scaffolded with mock fallbacks** — `bolo.py`, `voice_in.py`, `voice_out.py`, `phone.py`, `clone_voice.py`. All five gracefully no-op when API keys are missing so the demo loop runs end-to-end.
- **Web panel** — `agent/web/index.html`, single file, dark theme, mood ring, **7 grant tiles** (one per peer-to-peer grant), live event log, phone-status card with pulse animation on `calling`.
- **Project metadata** — `pyproject.toml`, `.env.example`, `.gitignore` (verified to cover `.env`), `clips/README.md`.
- **Three Bolo grants modeled and wired** — voice IDs are resolved THROUGH grants, never directly from env:
  - `@ruby → @mars` widget=`voice` scope=`demo_input` — Ruby's self-consent for the live demo input.
  - `@mom → @ruby` widget=`mars` — 5 action scopes (`order_food`, `payment:charge`, `vendors:allowlist`, `dietary:no_tree_nuts`, `notify_mom`).
  - `@chantal → @ruby` widget=`voice` scope=`outbound_calls` — DJ's voice donation.
- **Parallel grant fan-out.** Orchestrator runs all 7 grant checks via `asyncio.gather`. Web panel lights tiles concurrently.
- **AST validates.** All four touched Python files parse clean (`bolo.py`, `clone_voice.py`, `phone.py`, `orchestrator.py`).

### 🟡 In progress / known partial

- **No live end-to-end run yet.** Server has not been booted. No real API calls made. The whole stack is currently exercising the mock paths only.
- **Dependencies not installed.** `httpx`, `fastapi`, `anthropic`, `google-generativeai`, `elevenlabs`, etc. — pyproject is written but `pip install -e agent/` has not been run. (OneDrive file-locking interfered with the earlier whisper install — may bite again here.)
- **README still reflects the older framing.** Voice IDs as "config" — should be rewritten to feature the **three-grant architecture** as the central beat. The diagram needs Ruby's self-grant added as a third row.
- **Bolo backend not connected.** All grant lookups go to the in-process mock dict. The real Bolo API in `calendar project/apps/api` is reachable but the agent isn't pointed at it yet (needs `BOLO_API_KEY` and the API server running on `:3000`).

### 🔴 Blocked / not started

- **API keys missing** in `agent/.env`:
  - `ANTHROPIC_API_KEY` — required for the Claude orchestrator
  - `GOOGLE_API_KEY` — required for Gemini CP-aware transcription
  - `ELEVENLABS_API_KEY` — required for the actual TTS synthesis (Ruby + Chantal)
  - `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID`, `VAPI_TARGET_PHONE` — required for the phone to ring
- **Vapi phone setup** — need a Vapi phone number provisioned, AND a target phone number for the "Folino's" demo (almost certainly your phone).
- **Demo dry-run** — never executed. Risk that a Vapi config detail bites us at the worst moment.

---

## Run order to get to "phone rings on stage"

Ordered by minimum-blocking sequence. None of the later steps work until the earlier ones do.

| Step | Action | ETA | Blocked by |
|------|--------|-----|------------|
| 1 | `pip install -e agent/` (handle OneDrive locks: close VS Code, retry, or close OneDrive sync briefly) | 5 min | OneDrive |
| 2 | Drop `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY` into `agent/.env` | 2 min | you have these |
| 3 | Boot `python -m server.main`, hit `http://localhost:8000`, click ▶ Ruby speaks with all 4 keys mocked except ElevenLabs — confirm Ruby's voice synthesizes and grant tiles light up | 5 min | step 1, 2 |
| 4 | Provision Vapi phone number (or confirm existing one) → drop `VAPI_API_KEY` + `VAPI_PHONE_NUMBER_ID` + `VAPI_TARGET_PHONE` into `.env` | 15 min | Vapi account |
| 5 | Click ▶ again — phone should actually ring on `VAPI_TARGET_PHONE`. Verify Chantal's voice plays. | 5 min | step 4 |
| 6 | Update README to feature three-grant architecture as the central beat (replaces the "voice IDs as env config" framing) | 15 min | nothing |
| 7 | (Optional) Connect to real Bolo backend instead of the mock — only if calendar-project API is already running locally | 20 min | calendar project API up |
| 8 | Demo dry-run × 3. Confirm reconnect-on-WS-close, recovery from one tool failing, and what the panel does if Vapi rate-limits | 15 min | everything above |

**Critical path:** steps 1 → 2 → 3 → 4 → 5. Everything else is nice-to-have.

---

## Demo-readiness checklist

What "ready" looks like at curtain time:

- [ ] Server boots cleanly without warnings
- [ ] WebSocket connects, mood ring goes from gray → idle
- [ ] Type "I want pizza" → Ruby's voice synthesizes (audible)
- [ ] Voice-in card shows transcription + confidence bar
- [ ] All 7 grant tiles animate yellow → green within ~2s
- [ ] Phone status card pulses on `calling`
- [ ] **A real phone rings**
- [ ] Voice on the call is recognizably Chantal
- [ ] "Done" card shows order summary
- [ ] One judge gets to type a custom phrase ("order Chinese instead") and the loop still works
- [ ] Recovery story rehearsed for: ElevenLabs down, Vapi down, Anthropic rate-limited, network flakes

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| OneDrive file locks during `pip install` | Medium | Close VS Code + Claude Code, pause OneDrive sync, retry |
| Vapi voice cloning via ElevenLabs provider doesn't accept our voice IDs | Low-Medium | Test in step 5 dry-run; fallback to default Vapi voice with a hand-waved "this would be Chantal in production" |
| Anthropic rate limits during demo | Low | Pre-warm with one practice run before going on stage |
| The phone we set as `VAPI_TARGET_PHONE` rings during the wrong moment | Low | Set it to a number you control + put it on silent until the demo |
| README still framed wrong if a judge reads it | Medium | Step 6 before stage time |
| Live mic / projector issues | Always | Walk in early, test the projector |

---

## Decisions locked in (do not relitigate today)

- **Single agent skill in scope:** order pizza. The other 9 are roadmap, not code.
- **Folino's = the target phone.** Demo theatre. Ruby's actual favorite.
- **Voice cloning is for input AND output, both gated by Bolo grants.** The "voice IDs in env" framing is dead.
- **Mock paths are first-class.** Server must boot and the panel must light up even if every external API is broken.
- **No React, no build step.** Single HTML file, vanilla JS. Deliverable today, not next week.

---

*Last updated: 2026-04-29 16:10 EDT — keep this doc honest. Strike completed items as they ship.*
