<div align="center">

# When Ruby asks for pizza, she gets pizza.

### Ruby's Red Rover · v2 — the agent layer

<br>

> **🏆 Built today (April 29, 2026) at [Build YC's Next Unicorn — AWS Builder Loft, San Francisco](https://lu.ma/buildycnext).**
>
> A live, voice-driven, peer-to-peer-trust-gated ordering agent — built and shipped in a single session.
> Three real-people grants, two cloned voices, one agent loop, one phone that actually rings.

<br>

[![Built at AWS Builder Loft 2026](https://img.shields.io/badge/Built_at-AWS_Builder_Loft_2026-FF9900?style=for-the-badge&labelColor=1a1a1a)](https://lu.ma/buildycnext)
&nbsp;
[![Powered by Claude Agent SDK](https://img.shields.io/badge/Powered_by-Claude_Agent_SDK-d97757?style=for-the-badge&labelColor=1a1a1a)](https://www.anthropic.com)
&nbsp;
[![Trust Layer Bolo](https://img.shields.io/badge/Trust_Layer-Bolo-7c5cfc?style=for-the-badge&labelColor=1a1a1a)](https://bolospot.com)

<br>

**[▶ Watch Ruby order pizza](#the-demo)** &nbsp;·&nbsp; **[🏗️ Architecture](#how-it-works)** &nbsp;·&nbsp; **[🔧 Run it](#run-it-yourself)** &nbsp;·&nbsp; **[← v1: emotion detection](../README.md)**

</div>

---

## v1 saw Ruby. v2 lets Ruby act.

Ruby's Red Rover v1 won Google DeepMind's Best Multi-Modal at RoboHacks 2026 by being the first emotion system that reads Ruby correctly — distinguishing spasticity from anger, stimming from distress.

But seeing isn't enough. Ruby has things she wants to do. Order food. Call grandma. Pick a movie. Today, every off-the-shelf voice agent fails her on the first word.

**v2 closes that loop.** Ruby speaks. The agent hears her — really hears her. It checks what mom has approved. It picks up the phone. It gets it done.

---

## The demo

Ruby says, *"I want pizza."*

Her agent — running on MARS, orchestrated by Claude — does this in 12 seconds:

| Step | What happens |
|------|--------------|
| 1 | **Hears Ruby.** Gemini 2.5 Flash with CP-aware prompting parses her speech where Whisper and Siri fail. |
| 2 | **Asks one follow-up.** *"What kind, Ruby?"* — TTS plays back through MARS. Ruby says *"pepperoni."* |
| 3 | **Checks Bolo.** Has @mom granted @ruby `mars:order_food`? ✓ &nbsp; Payment? ✓ &nbsp; Vendors? `[dominos, papa_johns, folinos]` &nbsp; Cap? `$25/order` &nbsp; Diet? `no_tree_nuts` |
| 4 | **Picks Folino's.** Local. In-budget. No tree nuts on the order. Mom-approved. |
| 5 | **Picks up the phone.** Vapi dials Folino's. The agent speaks in **Chantal on the Radio's** voice — a working broadcaster, friend of the family, who granted Ruby permission (via Bolo) to use her voice for outbound calls. *"Hi, this is Chantal on the Radio calling to place an order for Ruby Cossette…"* |
| 6 | **Closes the loop.** *"Pepperoni from Folino's, $18.50, ETA 35 minutes."* MARS tells Ruby. Mom gets a notification. The audit log is written to Bolo. |

In a YC-room demo, step 5 is the moment the phone literally rings on stage.

> **The two voices.** Ruby's own voice — cloned with her family's consent, used only for the live demo — drives the input side, so judges can ask the agent to handle anything she might say, not just our pre-recorded lines. The DJ's donated voice carries Ruby's words into the world. We represent Ruby; we don't impersonate her. The DJ chose to give a voice to someone the world rarely slows down for. That choice is the demo.

---

## Why every layer carries weight

This isn't a wrapper. Each layer in the stack solves a real problem that would block the demo without it.

```
┌──────────────────────────────────────────────────────┐
│   Ruby (CP voice)                                    │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│   🎤 Voice In  ·  Gemini 2.5 Flash + CP-aware prompt │
│   reuses the v1 emotion-detection playbook           │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│   🧠 Orchestrator  ·  Claude Agent SDK               │
│   plans, asks clarifying questions, dispatches tools │
└──────────┬─────────────┬──────────────┬──────────────┘
           ▼             ▼              ▼
   ┌─────────────┐ ┌──────────┐ ┌──────────────────┐
   │ Bolo MCP    │ │ TTS      │ │ Vapi outbound    │
   │ grants /    │ │ Eleven-  │ │ live phone call  │
   │ trust /     │ │ Labs     │ │ to a real vendor │
   │ payment     │ │          │ │                  │
   └─────────────┘ └──────────┘ └──────────────────┘
```

### 🎤 The voice layer — *because Ruby is the user*

Off-the-shelf ASR (Whisper, native Siri, Alexa) drops or misreads ~40% of Ruby's words. Gemini 2.5 Flash audio is the only model we've found that handles non-standard articulation gracefully *and* tolerates pauses, breath, and motor variability without timing out.

The prompt layer — the same CP-aware reasoning template we use for emotion detection in v1 — explicitly instructs the model: *slow speech is not low confidence; pauses are not silences; unclear articulation is not gibberish — ask for clarification, don't guess.* When confidence drops below threshold, the agent asks a one-word follow-up rather than fabricating intent. That's the feature, not the bug.

### 🛡️ The trust layer — *because mom doesn't trust agents, mom trusts Ruby*

Built on [Bolo](https://github.com/alisoncossette/bolospot) — the trust protocol for the agent economy.

Bolo's grants are **peer-to-peer between people**, not platform-mediated. Two grants power this demo — one from Ruby's mom, one from her friend Chantal:

```
@mom ──grants──▶ @ruby                     ← parent → adult-child support
                  │
                  ├─ widget: mars
                  └─ scopes:
                      · actions:order_food
                      · actions:place_call
                      · payment:charge
                      · payment:max_per_order:25
                      · vendors:allowlist:dominos,papa_johns,folinos
                      · dietary:no_tree_nuts
                      · communications:notify_mom

@chantal ──grants──▶ @ruby                 ← friend → friend voice donation
                  │
                  ├─ widget: voice
                  └─ scopes:
                      · outbound_calls:true
                      · platform:elevenlabs
                      · elevenlabs_voice_id:vAfuZdld…YOBC
                      · context: "Donated by Chantal on the Radio."
```

Chantal's grant is the part most agent platforms cannot represent. **Bolo doesn't just permission tasks — it permissions identity, voice, and media as first-class peer-to-peer transactions.** When Ruby's agent dials Folino's, it doesn't reach for a hardcoded voice ID; it queries Bolo for an active grant from @chantal, pulls the voice metadata, and uses it. Revoke the grant → revoke the voice. That's a new product surface, and it ships in this demo.

This matters because:
- **The grant survives agent changes.** If Ruby switches from Claude to Gemini next week, mom's grant still holds. Mom granted Ruby, not the agent.
- **Permissions are revocable** in real time, by mom, from her phone.
- **Every action is auditable** — who acted, on whose behalf, with whose grant, through which agent. Full provenance, written to Bolo.
- **Adults with disabilities get *more* agency, not less** — within boundaries they and their family have agreed to together.

The Bolo MCP server exposes `lookup_handle`, `get_grants`, and `request_action` to the agent loop directly. Today the agent calls them as tools. Tomorrow any agent can.

#### *Bolo isn't OAuth for agents. It's the technical implementation of Supported Decision Making.*

Ruby is 20. She's an adult. Under the old legal model — **guardianship** — her mom would hold legal authority *over* Ruby, and Ruby would lose capacity to act for herself. Under **Supported Decision Making** (the modern human-rights framework, codified in [UN CRPD Article 12](https://www.un.org/development/desa/disabilities/convention-on-the-rights-of-persons-with-disabilities/article-12-equal-recognition-before-the-law.html) and now in law in Texas, DC, Indiana, and growing), Ruby retains legal capacity. Her mom is a *designated supporter* who structures the boundaries that help Ruby exercise her own authority safely.

Bolo's grants are exactly that — implemented in software:

- Mom doesn't act *for* Ruby. Mom and Ruby agree on scopes; Ruby acts.
- Permissions are revocable, auditable, and can grow as trust does.
- The agent is the tool. The authority is Ruby's.

No other agent platform on the market implements this. The default agent stack treats user authority as binary (root or nothing) or as platform-mediated (the platform owns the relationship). Bolo treats authority as **relational, scoped, and revocable** — because that's how human autonomy actually works for adults with disabilities. And for the rest of us, eventually, too.

### 🧠 The orchestrator — *because reasoning is the work*

Claude Agent SDK runs the loop: parse intent, ask follow-ups when uncertain, fan out tool calls (Bolo, vendor lookup, payment, dietary), narrate every step to the UI panel, recover gracefully when a tool fails. The reasoning trace streams to the demo screen so the room sees the thinking, not just the result.

We chose Claude here because the workshop today is about the Agent SDK, and because reasoning quality is the bottleneck on assistive AI — the gap between *technically correct* and *emotionally correct* is where Ruby lives.

### 📞 The action layer — *because the world is not an API*

Folino's doesn't have a REST endpoint. They have a phone. Vapi gives the agent an outbound voice that can dial a real number, hold a real conversation, take a real order, and confirm a real ETA — in 30 seconds, with a voice that actually sounds like a person.

That voice is on loan. A working radio broadcaster — a friend — donated her voice to Ruby for the parts of the world that don't slow down enough to listen. The clone is used only when Ruby's agent acts on her behalf, with full consent and revocation. The voice is a gift; the agency is Ruby's.

Phone calls are the long tail of physical-world action. Most "agentic" demos stop at "I would have called…" — this one rings.

---

## Run it yourself

> Tested on Windows 11 + Python 3.12. Requires `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (Gemini), `BOLO_API_KEY`, `VAPI_API_KEY`, `ELEVENLABS_API_KEY`.

```bash
cd agent
cp .env.example .env          # then fill in your keys
pip install -e .
python -m server.main         # FastAPI on :8000, WebSocket panel on /ws

# in your browser:
open http://localhost:8000
```

The web panel shows live agent reasoning, Bolo grant checks, and the live phone-call status. Click **▶ Ruby speaks** to fire a recorded clip into the pipeline.

```
agent/
├── server/
│   ├── main.py              # FastAPI + WebSocket
│   ├── orchestrator.py      # Claude Agent SDK loop
│   ├── tools/
│   │   ├── bolo.py          # Bolo MCP client → grant checks
│   │   ├── voice_in.py      # Gemini 2.5 audio (CP-aware)
│   │   ├── voice_out.py     # ElevenLabs TTS
│   │   └── phone.py         # Vapi outbound call
│   └── prompts/
│       └── cp_aware.md
├── web/
│   └── index.html           # live reasoning panel
├── clips/                   # Ruby's voice clips (gitignored)
└── README.md                # you are here
```

---

## What's next

This is skill #1. Nine more are queued:

| # | Skill | What unlocks |
|---|-------|--------------|
| 1 | **Order food** ✓ | *Today.* Ruby eats when Ruby is hungry. |
| 2 | Call grandma | Voice-initiated outbound calls to anyone in Ruby's contact list. |
| 3 | Schedule a ride | Lyft/Uber on Ruby's behalf, with mom's allowlist of destinations. |
| 4 | Pick a movie | Disney+ / Netflix navigation by voice, no remote required. |
| 5 | Tell mom I'm sad | Sentiment-aware escalation through Bolo. |
| 6 | Read me a book | Ladybug Robotics integration. |
| 7 | Order from a school list | Reorder Ruby's favorites with one phrase. |
| 8 | Make a video for grandma | Capture, edit, send via Bolo grant. |
| 9 | Practice talking | Speech therapy mode, calibrated to Ruby's baseline. |
| 10 | Anything mom adds | Bolo widget extensibility. |

Each new skill is a tool wired into the same agent loop. Same trust layer. Same voice front door. The agent doesn't get bigger — Ruby's world does.

---

## Credits

**Built by:** Alison Cossette · for Ruby

**Voice gift:** Chantal — radio DJ, friend of Ruby's family, for giving Ruby a voice that travels at the speed of the world.

**On the shoulders of:**
- [Anthropic](https://anthropic.com) — Claude Agent SDK
- [Google DeepMind](https://deepmind.google) — Gemini 2.5 Flash, and the v1 RoboHacks recognition
- [Innate](https://innate.ai) — MARS robot platform
- [Bolo](https://bolospot.com) — peer-to-peer trust for the agent economy
- [Vapi](https://vapi.ai) — outbound voice agents that actually ring
- [ElevenLabs](https://elevenlabs.io) — TTS that sounds like a person

**Built at:** [Build YC's Next Unicorn — AWS Builder Loft, San Francisco](https://lu.ma/buildycnext) · April 29, 2026

**For:** Ruby. Always Ruby.

---

<div align="center">

*Ruby knows what she wants. We just had to build the rest.*

</div>
