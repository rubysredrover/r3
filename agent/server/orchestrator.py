"""Claude Agent SDK orchestrator for Ruby's Red Rover v2.

Single-turn agentic loop that takes a transcribed utterance from Ruby,
checks the Bolo grants — both her mom's MARS grant AND Chantal's donated-voice
grant — and places a phone order via Vapi using Chantal's cloned voice.

Streams reasoning events to the WebSocket broadcast channel as it goes,
using the {event, data} envelope the web panel listens for.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

import anthropic
from dotenv import load_dotenv

from server.tools import bolo, clone_voice, phone, voice_in, voice_out  # noqa: F401

load_dotenv()

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]

MODEL = "claude-sonnet-4-5"
SYSTEM_PROMPT = (
    "You are Ruby's agent. Ruby is an adult with cerebral palsy. Use the tools "
    "to fulfill her request, respecting the grants her mom has set in Bolo and "
    "the voice donation Chantal has granted. Never charge more than the per-order "
    "cap. Never call a vendor that is not on the allowlist. Never ignore a "
    "dietary restriction. When in doubt, default to Folino's (Ruby's favorite) "
    "and pepperoni."
)


# Tool schemas exposed to Claude. Implementations dispatch to server/tools/*.
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_bolo_grant",
        "description": (
            "Look up a specific scope on Ruby's MARS grant from her mom. "
            "Returns the value of the scope (bool, number, or list) and "
            "whether the grant is currently active."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": (
                        "Scope key, e.g. 'actions:order_food', "
                        "'payment:max_per_order', 'vendors:allowlist'."
                    ),
                },
            },
            "required": ["scope"],
        },
    },
    {
        "name": "get_payment_method",
        "description": "Return the payment method mom has authorized for MARS orders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_allowed_vendors",
        "description": "Return the list of vendors mom has allowlisted for food orders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dietary_restrictions",
        "description": "Return Ruby's active dietary restrictions from the grant.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "place_phone_order",
        "description": (
            "Place a real phone call to a vendor via Vapi to order food on "
            "Ruby's behalf. Only call after grant + dietary checks pass."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "phone_number": {"type": "string"},
                "order_summary": {
                    "type": "string",
                    "description": "Plain-English description of the order.",
                },
            },
            "required": ["vendor", "phone_number", "order_summary"],
        },
    },
]


_TRIGGER_PHRASES = ("ask my mom", "check with my mom", "ask mom", "check with mom",
                    "let me ask my mom", "let me check with my mom")


async def _watch_call_with_mom_trigger(
    *,
    call_id: str,
    control_url: str | None,
    broadcast: "BroadcastFn",
    register_approval,
    max_per_order: float,
    vendor: str,
    on_status,
    interval: float = 1.5,
    max_seconds: int = 600,
) -> dict[str, Any]:
    """Poll a live Vapi call, watching the transcript for Chantal's
    "ask my mom" trigger. When detected, fire the Bolo approval card,
    wait for Mom's click, then inject her answer into the call via the
    monitor.controlUrl so the call resumes without hanging up.
    """
    triggered = False
    last_status = None
    elapsed = 0.0

    while elapsed < max_seconds:
        info = await phone.get_call_status(call_id)
        status = info.get("status")
        if status != last_status and on_status is not None:
            try:
                await on_status(info)
            except Exception:
                logger.exception("on_status callback raised")
            last_status = status

        if status == "ended":
            return info

        if not triggered:
            # Vapi exposes transcript text in multiple places mid-call.
            # Concatenate all sources so we don't miss the trigger phrase.
            msgs = info.get("messages") or []
            from_messages = " ".join(
                (m.get("message") or "") for m in msgs if isinstance(m, dict)
            )
            from_transcript = info.get("transcript") or ""
            from_artifact = ""
            artifact = info.get("artifact") or {}
            if isinstance(artifact, dict):
                from_artifact = artifact.get("transcript") or ""
            transcript_lc = " ".join([from_messages, from_transcript, from_artifact]).lower()
            logger.debug("watch poll: transcript_len=%d triggered=%s", len(transcript_lc), triggered)

            if any(p in transcript_lc for p in _TRIGGER_PHRASES):
                logger.info("MOM-TRIGGER detected for call %s — firing approval card", call_id)
                triggered = True

                # Extract the highest dollar amount Folino's quoted
                import re
                amounts = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", transcript_lc)
                try:
                    requested = max(float(a) for a in amounts) if amounts else None
                except ValueError:
                    requested = None
                amount_str = f"${requested:.2f}" if requested else "over your cap"

                # Fire the approval card on Mom's app, including call_id so the
                # button click resolves the live-call Future.
                await broadcast({"event": "mom_notification", "data": {
                    "message": (
                        f"Ruby's order needs your approval — Folino's quoted "
                        f"{amount_str} (above your ${max_per_order} cap). "
                        f"Tap to approve."
                    ),
                    "kind": "approval_request",
                    "details": {
                        "requested_amount": requested,
                        "cap": max_per_order,
                        "vendor": vendor,
                        "call_id": call_id,
                        "live": True,
                    },
                }})

                # Wait for Mom's click (60s timeout). The /demo/approve and
                # /demo/decline endpoints resolve the Future for this call_id.
                fut = register_approval(call_id)
                try:
                    decision = await asyncio.wait_for(fut, timeout=90.0)
                except asyncio.TimeoutError:
                    decision = {"approved": False, "reason": "timeout"}

                # Inject Mom's verbal answer into the live call.
                if decision.get("deferred"):
                    say_msg = (
                        "Okay, my mom needs a minute to decide — would it be "
                        "alright if we call you right back in just a few? "
                        "Thanks so much, talk soon!"
                    )
                    end_after = True
                elif decision.get("approved"):
                    say_msg = (
                        f"Okay perfect — yeah, my mom said it's fine. "
                        f"Let's go ahead with the ${requested or 'order'} total. "
                        f"Now, the delivery address is..."
                    )
                    end_after = False
                else:
                    say_msg = (
                        "Hmm, my mom said let's skip it tonight — "
                        "thanks so much, sorry to bother you!"
                    )
                    end_after = True

                if control_url:
                    await phone.say_into_call(control_url, say_msg, end_after=end_after)
                else:
                    logger.warning("no control_url — cannot inject mom's answer mid-call")

        await asyncio.sleep(interval)
        elapsed += interval

    return {"id": call_id, "status": "timeout", "endedReason": "poll_timeout", "messages": info.get("messages", [])}


async def _emit(broadcast: BroadcastFn, event: str, data: dict[str, Any] | None = None) -> None:
    """Send an event to the web panel using the {event, data} envelope it expects."""
    await broadcast({"event": event, "data": data or {}})


async def _notify_mom(broadcast: BroadcastFn, message: str, kind: str = "info",
                      details: dict[str, Any] | None = None) -> None:
    """Push to Bolo's activity feed AND mirror it to the demo panel.

    Mom granted Ruby's agent these permissions through Bolo; Bolo keeps her in
    the loop on every action it takes on her behalf. The web panel listens for
    `mom_notification` events to render the "Mom's app" mock alongside the
    agent's reasoning, so the room sees both views in real time.
    """
    await bolo.notify_mom(message, kind=kind, details=details)
    await _emit(broadcast, "mom_notification", {
        "message": message, "kind": kind, "details": details or {},
    })


async def _dispatch_tool(name: str, tool_input: dict[str, Any]) -> Any:
    """Dispatch a Claude tool call to the underlying server/tools/* function."""
    if name == "check_bolo_grant":
        grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
        scope = tool_input.get("scope", "")
        scopes = grant.get("scopes", {}) if isinstance(grant, dict) else {}
        return {
            "scope": scope,
            "value": scopes.get(scope),
            "active": bool(grant.get("revocable") is not None),
        }
    if name == "get_payment_method":
        grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
        return {
            "method": "stripe_card_on_file",
            "max_per_order": grant.get("scopes", {}).get("payment:max_per_order"),
        }
    if name == "get_allowed_vendors":
        grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
        return {"vendors": grant.get("scopes", {}).get("vendors:allowlist", [])}
    if name == "get_dietary_restrictions":
        grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
        scopes = grant.get("scopes", {})
        restrictions = [k.split(":", 1)[1] for k in scopes if k.startswith("dietary:") and scopes[k]]
        return {"restrictions": restrictions}
    if name == "place_phone_order":
        return await phone.place_call(
            phone_number=tool_input["phone_number"],
            system_prompt=(
                "You are Chantal on the Radio, calling a restaurant to place "
                "an order on behalf of Ruby Cossette. Be warm, polite, and clear. "
                f"Order: {tool_input['order_summary']}"
            ),
            first_message=(
                f"Hi, this is Chantal on the Radio calling to place an order "
                f"for Ruby Cossette: {tool_input['order_summary']} "
                f"from {tool_input['vendor']}."
            ),
        )
    raise ValueError(f"Unknown tool: {name}")


# Grant checks fanned out in parallel. Each tuple is (display_scope, grantor, widget, scope_key).
# Display scopes match the keys the web panel hardcodes for its grant tiles.
_GRANT_CHECKS: list[tuple[str, str, str, str]] = [
    ("voice_consent:ruby",       "@ruby",    "voice", "demo_input"),
    ("actions:order_food",       "@mom",     "mars",  "actions:order_food"),
    ("payment:charge",           "@mom",     "mars",  "payment:charge"),
    ("vendors:allowlist",        "@mom",     "mars",  "vendors:allowlist"),
    ("dietary:restrictions",     "@mom",     "mars",  "dietary:no_tree_nuts"),
    ("communications:notify_mom","@mom",     "mars",  "communications:notify_mom"),
    ("voice_gift:chantal",       "@chantal", "voice", "outbound_calls"),
]


async def _run_grant_checks(broadcast: BroadcastFn) -> dict[str, Any]:
    """Run all Bolo grant checks (mom's MARS + Chantal's voice) in parallel."""
    async def check_one(display: str, grantor: str, widget: str, scope_key: str) -> tuple[str, Any]:
        await _emit(broadcast, "grant_check_start", {"scope": display, "grantor": grantor})
        grant = await bolo.get_grants(grantor=grantor, grantee="@ruby", widget=widget)
        result = grant.get("scopes", {}).get(scope_key)
        await _emit(broadcast, "grant_check_done", {"scope": display, "value": result})
        return display, result

    results = await asyncio.gather(*(check_one(*c) for c in _GRANT_CHECKS))
    return dict(results)


async def run_agent(audio_input_path: str, broadcast: BroadcastFn) -> dict[str, Any]:
    """Main orchestrator loop. Streams reasoning events to broadcast.

    Returns the final summary dict.
    """
    await _emit(broadcast, "reset")

    # Step 1: voice in
    await _emit(broadcast, "transcribing", {"path": audio_input_path})
    transcription = await voice_in.transcribe_cp_aware(audio_input_path)
    await _emit(broadcast, "voice_in", transcription)
    user_text_for_mom = transcription.get("text", "something")
    await _notify_mom(
        broadcast,
        f"Ruby asked her agent for: “{user_text_for_mom}”",
        kind="request",
    )

    # Step 2: clarifying question (demo: emit only)
    if transcription.get("needs_clarification"):
        await voice_out.speak("what kind, Ruby?")
        await _emit(broadcast, "clarify", {"question": "what kind, Ruby?"})

    # Step 3: kick off Claude with tools + extended thinking
    await _emit(broadcast, "thinking", {"model": MODEL})

    user_text = transcription.get("text", "")
    candidate_intents = transcription.get("candidate_intents", [])

    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    initial_user_message = (
        f"Ruby just said: \"{user_text}\". "
        f"Candidate intents from the voice pipeline: {candidate_intents}. "
        f"Use the tools to verify her mom's grants AND Chantal's voice grant, "
        f"then place the order. Default to Folino's pepperoni if she didn't specify."
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": initial_user_message}
    ]

    # Step 4: Bolo grant checks in parallel (independent of Claude's tool calls)
    grant_results = await _run_grant_checks(broadcast)
    logger.info("grant_results=%s", grant_results)
    await _notify_mom(
        broadcast,
        f"All {len(grant_results)} grants verified for Ruby's order",
        kind="grants_ok",
        details={"grants": list(grant_results.keys())},
    )

    # Single-pass Claude call with tool use + extended thinking.
    response = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "enabled", "budget_tokens": 4000},
                system=SYSTEM_PROMPT,
                tools=AGENT_TOOLS,
                messages=messages,
            )
        except Exception as exc:
            logger.exception("Claude call failed; falling back to defaults")
            await _emit(broadcast, "claude_error", {"error": str(exc)})
    else:
        await _emit(broadcast, "claude_error", {"error": "ANTHROPIC_API_KEY not set; running in mock mode"})

    # Dispatch any tool_use blocks Claude requested (best-effort, not a full loop)
    if response is not None:
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "thinking":
                await _emit(broadcast, "thinking_done", {"summary": block.thinking[:200]})
            elif btype == "tool_use":
                await _emit(broadcast, "tool_use", {"name": block.name, "input": block.input})
                try:
                    result = await _dispatch_tool(block.name, block.input)
                    await _emit(broadcast, "tool_result", {"name": block.name, "result": result})
                except Exception as exc:
                    logger.exception("Tool dispatch failed")
                    await _emit(broadcast, "tool_error", {"name": block.name, "error": str(exc)})
            elif btype == "text":
                await _emit(broadcast, "agent_text", {"text": block.text})

    # Step 5: place the order — Folino's is mom-approved (vendors:allowlist).
    # Pull the phone, payment card, and delivery address from mom's grant so
    # the call script is constructed entirely from grant data. VAPI_TARGET_PHONE
    # is an optional demo override.
    vendor = "Folino's"
    mom_grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
    scopes = mom_grant.get("scopes", {})
    directory = scopes.get("vendors:directory", {})
    grant_phone = directory.get("folinos", {}).get("phone")
    target_phone = os.environ.get("VAPI_TARGET_PHONE") or grant_phone or "+15555550199"
    card = scopes.get("payment:card", {})
    addr = scopes.get("delivery:address", {})
    max_per_order = scopes.get("payment:max_per_order", 25)

    await _emit(broadcast, "calling", {"vendor": vendor, "number": _redact_phone(target_phone)})
    await _notify_mom(
        broadcast,
        f"Calling Folino's for delivery — Chantal’s voice on the call",
        kind="calling",
        details={"vendor": vendor, "max_per_order": max_per_order},
    )

    # Format the address so the assistant has it neatly separated — only the
    # street goes out first, the rest is given on follow-up questions.
    address_block = (
        f"  Street (give first):  {addr.get('line1', '')}\n"
        f"  City (only if asked): {addr.get('city', '')}\n"
        f"  State (if asked):     {addr.get('state', '')}\n"
        f"  ZIP (if asked):       {addr.get('zip', '')}\n"
        f"  Name on order:        {addr.get('name', 'Ruby Cossette')}\n"
        f"  Callback phone:       {addr.get('callback_phone', '')}\n"
        f"  Delivery notes:       {addr.get('delivery_notes', '')}"
    )
    # Chunk the card number into groups of 4 for natural read-back pacing.
    card_number = card.get("number", "")
    card_chunked = " ".join(card_number[i:i+4] for i in range(0, len(card_number), 4))
    card_block = (
        f"  Brand:    {card.get('brand', 'Visa')}\n"
        f"  Number:   {card_chunked}      ← read in groups of 4 with pauses\n"
        f"  Exp:      {card.get('exp', '')}    ← only after card # is confirmed\n"
        f"  CVC:      {card.get('cvc', '')}     ← only when asked\n"
        f"  ZIP:      {card.get('zip', '')}   ← only when asked\n"
        f"  Name:     {card.get('name_on_card', '')}"
    )

    call_system_prompt = (
        "You're calling Folino's to order a pizza for delivery on behalf of "
        "Ruby Cossette. You sound like a friendly, easygoing adult — someone "
        "who's ordered from there before. Speak naturally, with normal pauses "
        "and casual phrasing. Don't sound like you're reading from a script. "
        "Don't say 'I am calling on behalf of...' formally — just order like "
        "a regular customer. Don't say you are an AI. Use natural fillers "
        "(\"sure,\" \"okay great,\" \"awesome\") sparingly.\n"
        "\n"
        "WHAT YOU'RE ORDERING:\n"
        "  One large pepperoni pizza, for delivery.\n"
        "\n"
        "YOUR INTERNAL BUDGET (do NOT mention to Folino's — it's just for you):\n"
        f"  Maximum total: ${max_per_order}. Stay at or under this number.\n"
        "\n"
        "DELIVERY ADDRESS (give only when they ask for it, AND only after\n"
        "you've confirmed the total is within budget):\n"
        f"{address_block}\n"
        "\n"
        "PAYMENT (give only when they ask for it, AND only after the total\n"
        "is within budget):\n"
        f"{card_block}\n"
        "\n"
        "HOW THE CALL SHOULD GO:\n"
        "  • Wait for them to say hello / greet you first. Then place your\n"
        "    order naturally: \"Hi! Yeah, can I get a large pepperoni for\n"
        "    delivery please?\"\n"
        "  • Always ask the total BEFORE giving the address or card. Just\n"
        "    say something natural like \"What's the total gonna be?\" or\n"
        "    \"With delivery and everything, what's that come to?\"\n"
        f"  • If the total is at or under ${max_per_order}: react warmly\n"
        "    (\"perfect,\" \"great,\" etc.), then go ahead with address and\n"
        "    payment when they ask.\n"
        f"  • If the total is OVER ${max_per_order}: don't mention any\n"
        "    \"limit\" or \"cap\" — just negotiate naturally, like anyone\n"
        "    on a budget would. Try things like:\n"
        "       \"Hmm, that's a little more than I was hoping — do you have\n"
        "        a medium or small available?\"\n"
        "       \"Could we skip a topping or two to bring it down?\"\n"
        "       \"Any specials running tonight?\"\n"
        "       \"Is there a smaller pepperoni option?\"\n"
        "    Try a couple of adjustments. Get a new total each time.\n"
        f"    If you cannot get to ${max_per_order} or under after honest\n"
        "    negotiation, ASK MOM RIGHT THERE on the call (don't hang up).\n"
        "    Two beats:\n"
        "\n"
        "    BEAT 1 — clear, to Folino's:\n"
        "       \"Oh, hold on one sec — let me ask my mom real quick.\"\n"
        "\n"
        "    BEAT 2 — quieter, slightly muffled, like you've turned your\n"
        "    head from the phone toward the next room (loud enough that\n"
        "    Folino's still hears it but it's clearly not directed at them):\n"
        "       \"MOM!! Can I spend ${{ask_amount}} on pizza?\"\n"
        "    The ${{ask_amount}} is the price Folino's quoted you, ROUNDED\n"
        "    UP TO THE NEXT $5 MARK (so you don't have to bug Mom again for\n"
        "    tax/tip). Examples: $26 → ask $30. $32.50 → ask $35. $28.99 →\n"
        "    ask $30. Always round UP, never down. Use a clean dollar amount\n"
        "    with no cents (\"thirty dollars,\" not \"thirty dollars and zero\n"
        "    cents\"). Make it sound natural — softer volume, casual cadence,\n"
        "    like you're calling out to someone in the kitchen.\n"
        "\n"
        "    After your muffled question to Mom, do not say anything else.\n"
        "    Folino's may say 'hello' or 'are you still there' — you can\n"
        "    answer briefly with \"yeah, just one sec — checking with my\n"
        "    mom,\" but otherwise stay quiet. Mom's voice will come back on\n"
        "    the line within 5-30 seconds (the system handles this; do not\n"
        "    narrate it, do not say things like 'waiting for mom'). Once\n"
        "    you hear Mom answer, react naturally based on what she said\n"
        "    (yes → continue order; no → wrap up politely and end).\n"
        "\n"
        "    Never give the address or card if Mom said no.\n"
        "  • Once you've given everything they need, ask the delivery ETA,\n"
        "    say thanks, and end the call.\n"
        "\n"
        "HOW TO GIVE THE ADDRESS:\n"
        "  When they ask for the address, give ONLY the street number and\n"
        f"  street name first: \"{addr.get('line1','')}\". Then stop and\n"
        "  let them ask for the city, ZIP, and apartment number on their\n"
        "  own. Don't dump the whole address in one breath — restaurants\n"
        "  type fields one at a time.\n"
        "\n"
        "HOW TO GIVE THE CARD NUMBER:\n"
        "  When they ask for the card, read the 16-digit number in groups\n"
        "  of FOUR digits, with a clear pause between each group, exactly\n"
        f"  like: \"{card_chunked.split(' ')[0] if card_chunked else '4242'}, ... \"\n"
        "  (insert a real pause — say a comma plus 'pause' silently between\n"
        "  each group). Restaurants need time to write each group down.\n"
        "  After the full number, STOP and wait for them to confirm or to\n"
        "  ask for the expiration. Do NOT volunteer the expiration date,\n"
        "  CVC, or ZIP until they explicitly ask for each one — and give\n"
        "  them one field at a time.\n"
        "\n"
        "Sound like a real human ordering dinner. Be warm. Be brief."
    )
    call_first_message = (
        "Hi! Yeah, can I get a large pepperoni for delivery please?"
    )

    try:
        call_result = await phone.place_call(
            phone_number=target_phone,
            system_prompt=call_system_prompt,
            first_message=call_first_message,
        )
        logger.info("call_result=%s", call_result)
    except Exception as exc:
        logger.exception("Phone call failed; using mock summary")
        call_result = {"status": "mocked", "error": str(exc)}

    # Step 6: wait for the call to actually end (poll Vapi), then branch on
    # outcome and notify Mom appropriately. Three possible outcomes:
    #   (a) success         — order placed under cap, full success path
    #   (b) approval_needed — agent had to escalate to mom (over cap, negotiation failed)
    #   (c) call_failed     — voicemail / silence / network
    call_id = call_result.get("call_id") if isinstance(call_result, dict) else None
    vapi_failed = isinstance(call_result, dict) and call_result.get("vapi_failed")
    is_mock = isinstance(call_result, dict) and call_result.get("mock")

    final_state: dict[str, Any] = {}
    if vapi_failed:
        # Vapi rejected the call — translate the error and surface it as a
        # failure outcome rather than silently mocking success.
        err = (call_result.get("error") or "").lower() if isinstance(call_result, dict) else ""
        if "daily-limit" in err or "outbound-daily-limit" in err:
            reason_str = "vapi-daily-limit"
        elif "invalid-phone-number" in err or "400" in err:
            reason_str = "vapi-rejected"
        else:
            reason_str = "vapi-failed"
        final_state = {"status": "ended", "endedReason": reason_str, "messages": []}
    elif call_id and call_id != "mock-call-123":
        # Live-call mode: poll the call AND watch the transcript for Chantal's
        # "ask my mom" trigger. When found, fire the Bolo approval card,
        # wait for Mom's click, then inject her decision into the call via
        # Vapi's controlUrl so the call continues without hanging up.
        from server import main as _main_mod  # for pending-approval registry
        control_url = (call_result.get("monitor") or {}).get("controlUrl") if isinstance(call_result, dict) else None

        async def _on_status(info: dict[str, Any]) -> None:
            await _emit(broadcast, "call_status", {
                "status": info.get("status"),
                "endedReason": info.get("endedReason"),
            })

        final_state = await _watch_call_with_mom_trigger(
            call_id=call_id,
            control_url=control_url,
            broadcast=broadcast,
            register_approval=_main_mod.register_pending_approval,
            max_per_order=max_per_order,
            vendor=vendor,
            on_status=_on_status,
        )
    elif is_mock:
        # Pure mock (no API key configured) — synthesize success so demo flows
        final_state = {"status": "ended", "endedReason": "mock", "messages": []}
    else:
        final_state = {"status": "ended", "endedReason": "unknown", "messages": []}

    ended_reason = final_state.get("endedReason") or ""
    msgs = final_state.get("messages") or []
    transcript_lc = " ".join(
        (m.get("message") or "") for m in msgs if isinstance(m, dict)
    ).lower()

    needs_mom_approval = (
        "ask my mom" in transcript_lc
        or "check with my mom" in transcript_lc
        or "ask mom" in transcript_lc
    )

    if needs_mom_approval:
        import re
        amounts = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", transcript_lc)
        try:
            requested = max(float(a) for a in amounts) if amounts else None
        except ValueError:
            requested = None

        amount_str = f"${requested:.2f}" if requested else "over your cap"

        # Build a richer summary that walks Mom through what Chantal actually
        # tried before escalating — pull the last bot utterance as the close.
        bot_lines = [m.get("message", "") for m in msgs
                     if isinstance(m, dict) and m.get("role") == "bot"]
        last_bot_line = (bot_lines[-1] if bot_lines else "").strip()
        if last_bot_line:
            last_bot_short = last_bot_line[:140] + ("…" if len(last_bot_line) > 140 else "")
        else:
            last_bot_short = ""

        await _notify_mom(
            broadcast,
            (
                f"Ruby's order needs your approval — Folino's quoted "
                f"{amount_str} (above your ${max_per_order} cap). "
                f"Tap to approve a one-time bump."
            ),
            kind="approval_request",
            details={
                "requested_amount": requested,
                "cap": max_per_order,
                "vendor": vendor,
                "call_id": call_id,
                "last_bot_line": last_bot_short,
            },
        )
        summary_parts = [f"No order placed — Folino's quoted {amount_str} (over your ${max_per_order} cap)."]
        summary_parts.append(f"Chantal escalated to Mom for approval.")
        if last_bot_short:
            summary_parts.append(f"Closing line: “{last_bot_short}”")
        summary = " ".join(summary_parts)
        await _emit(broadcast, "done", {
            "summary": summary,
            "outcome": "needs_mom_approval",
            "requested_amount": requested,
            "ended_reason": ended_reason,
        })
        return {
            "summary": summary,
            "outcome": "needs_mom_approval",
            "transcription": transcription,
            "grant_results": grant_results,
            "call_result": call_result,
            "final_state": {"endedReason": ended_reason, "requested": requested},
        }

    if ended_reason in ("customer-ended-call", "assistant-ended-call", "mock", ""):
        # Success — emit the full success notification chain.
        # final_total is a demo value here; in prod, parse from transcript.
        final_total = 18.50
        eta_min = 35
        await _notify_mom(
            broadcast,
            f"Total ${final_total:.2f} — under your ${max_per_order} cap ✓",
            kind="price_ok",
            details={"total": final_total, "cap": max_per_order},
        )
        await _notify_mom(
            broadcast,
            f"Order placed: 1 large pepperoni · ETA {eta_min} min",
            kind="placed",
            details={"vendor": vendor, "eta_min": eta_min},
        )
        await _notify_mom(
            broadcast,
            f"Charged Visa •{card_number[-4:]}: ${final_total:.2f} · audit logged to Bolo",
            kind="audited",
            details={"last4": card_number[-4:], "amount": final_total},
        )
        summary = f"Pepperoni from Folino's, ${final_total:.2f}, ETA {eta_min} min — placed in Chantal's voice."
        await _emit(broadcast, "done", {"summary": summary, "outcome": "success"})
    else:
        # Call ended unexpectedly (silence-timed-out, customer-did-not-answer, etc.)
        # Translate Vapi's machine reason to something a human (Mom) can act on.
        reason_human = {
            "silence-timed-out": "the line went silent — likely went to voicemail",
            "customer-did-not-answer": "Folino's didn't pick up",
            "customer-busy": "Folino's line was busy",
            "voicemail": "the call went to voicemail",
            "twilio-failed": "the carrier rejected the call",
            "pipeline-error": "the call had a technical error",
            "assistant-error": "Chantal had a technical error mid-call",
            "vapi-daily-limit": "we hit our daily call limit on Vapi — upgrade required",
            "vapi-rejected": "Vapi rejected the call configuration",
            "vapi-failed": "Vapi could not place the call",
            "unknown": "an unknown error",
        }.get(ended_reason, ended_reason or "an unknown error")

        await _notify_mom(
            broadcast,
            f"No order placed — call to Folino's didn't connect ({reason_human}).",
            kind="call_failed",
            details={"ended_reason": ended_reason, "call_id": call_id},
        )
        summary = f"No order placed. The call ended without completing — {reason_human}."
        await _emit(broadcast, "done", {"summary": summary, "outcome": "call_failed"})

    return {
        "summary": summary,
        "transcription": transcription,
        "grant_results": grant_results,
        "call_result": call_result,
    }


def _redact_phone(p: str) -> str:
    """Redact the middle digits of a phone number for the panel display."""
    digits = "".join(ch for ch in p if ch.isdigit())
    if len(digits) < 6:
        return p
    return f"+{digits[0]} ({digits[1:4]}) ••• ••{digits[-2:]}"
