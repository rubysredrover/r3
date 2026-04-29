"""Vapi outbound calling tool.

MARS uses this to place pizza orders by phone on Ruby's behalf.
"""
from __future__ import annotations

import logging
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
# Chantal — DJ friend's donated voice for outbound calls on Ruby's behalf
CHANTAL_VOICE_ID = os.environ.get("CHANTAL_VOICE_ID", "vAfuZdldSpxthmIQYOBC")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VAPI_URL = "https://api.vapi.ai/call/phone"


def _mock_reason(missing: str) -> None:
    msg = f"[mock] reason: missing {missing}"
    print(msg, file=sys.stderr)
    logger.warning(msg)


async def _resolve_chantal_voice_id() -> str:
    """Pull Chantal's donated voice ID from her Bolo grant to Ruby.

    The voice ID lives in the grant's scopes payload, not in env config —
    so revoking the grant is the canonical way to revoke voice usage.
    Falls back to the env var if the Bolo lookup fails.
    """
    try:
        # Imported here to avoid an import cycle when bolo.py is loaded first.
        from server.tools import bolo
        grant = await bolo.get_grants(grantor="@chantal", grantee="@ruby", widget="voice")
        scopes = grant.get("scopes", {}) if isinstance(grant, dict) else {}
        if scopes.get("outbound_calls") and scopes.get("elevenlabs_voice_id"):
            return scopes["elevenlabs_voice_id"]
    except Exception as exc:  # pragma: no cover - mock path is forgiving
        logger.warning("voice grant lookup failed (using env fallback): %s", exc)
    return CHANTAL_VOICE_ID


async def say_into_call(control_url: str, message: str, end_after: bool = False) -> dict:
    """Inject a `say` command into a live Vapi call via its monitor.controlUrl.

    Used to drive the call mid-flight: e.g. after Chantal pauses to ask Mom,
    we POST mom's verbal answer here so the assistant speaks it on the line.
    """
    if not control_url:
        return {"ok": False, "error": "no control_url"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                control_url,
                json={"type": "say", "message": message, "endCallAfterSpoken": end_after},
            )
            return {"ok": r.status_code < 400, "status_code": r.status_code, "body": r.text[:300]}
    except Exception as exc:
        logger.warning("say_into_call failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def get_call_status(call_id: str) -> dict:
    """Fetch a call's current status from Vapi. Returns the full call object
    or a small mock dict if no API key.
    """
    if not VAPI_API_KEY:
        return {"id": call_id, "status": "ended", "endedReason": "mock"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"https://api.vapi.ai/call/{call_id}",
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("get_call_status failed: %s", exc)
        return {"id": call_id, "status": "unknown", "error": str(exc)}


async def poll_until_ended(call_id: str, on_status=None, max_seconds: int = 600,
                           interval: float = 2.5) -> dict:
    """Poll Vapi until the call's status moves through to ``ended`` (or timeout).

    ``on_status`` is an optional async callback invoked each time the status
    changes — useful for streaming live updates to the web panel.
    """
    import asyncio as _asyncio
    last_status = None
    elapsed = 0.0
    while elapsed < max_seconds:
        info = await get_call_status(call_id)
        status = info.get("status")
        if status != last_status and on_status is not None:
            try:
                await on_status(info)
            except Exception:
                logger.exception("on_status callback raised")
            last_status = status
        if status == "ended":
            return info
        await _asyncio.sleep(interval)
        elapsed += interval
    return {"id": call_id, "status": "timeout", "endedReason": "poll_timeout"}


async def place_call(phone_number: str, system_prompt: str, first_message: str) -> dict:
    """Place an outbound call via Vapi.

    Returns ``{"call_id": str, "status": str}``.
    """
    if not VAPI_API_KEY:
        _mock_reason("VAPI_API_KEY")
        print(f"[mock] would call {phone_number}", file=sys.stderr)
        return {"call_id": "mock-call-123", "status": "queued", "mock": True}

    # Use Chantal's donated voice via ElevenLabs (provider "11labs" in Vapi).
    # Voice ID is sourced from her peer-to-peer Bolo grant to @ruby — not
    # hardcoded — so revoking the grant revokes the voice.
    #
    # IMPORTANT: Vapi does not accept an inline ElevenLabs API key per call.
    # To use a custom-cloned voice ID (Chantal's `vAfuZdldSpxthmIQYOBC` lives
    # on Alison's ElevenLabs account, not Vapi's default), the ElevenLabs key
    # must be added once in the Vapi dashboard at:
    #   vapi.ai → Settings → Provider Credentials → ElevenLabs
    # Without that step, Vapi will reject the call with a 400 because it
    # cannot resolve the custom voice_id.
    voice_id = await _resolve_chantal_voice_id()
    voice_config: dict = {
        "provider": "11labs",
        "voiceId": voice_id,
        "model": "eleven_turbo_v2_5",
        "stability": 0.5,
        "similarityBoost": 0.75,
    }
    body = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number},
        "assistant": {
            # Wait for the human (Folino's) to speak first — natural restaurant
            # flow is "Folino's, what can I get you?" THEN Chantal responds.
            # Without this, Chantal starts talking before the human even says hi.
            "firstMessageMode": "assistant-waits-for-user",
            "firstMessage": first_message,
            "silenceTimeoutSeconds": 30,
            "model": {
                "provider": "anthropic",
                # Vapi only accepts dated/specific Anthropic model IDs (not aliases
                # like "claude-sonnet-4-5"). claude-sonnet-4-6 is on Vapi's allowlist.
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "system", "content": system_prompt}],
            },
            "voice": voice_config,
        },
    }
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(VAPI_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return {
                "call_id": data.get("id"),
                "status": data.get("status"),
                "monitor": data.get("monitor") or {},
            }
    except Exception as exc:
        # Real Vapi call attempted but rejected — surface the failure to the
        # orchestrator instead of pretending it queued. Common reasons:
        # vapi-number-outbound-daily-limit, invalid-phone-number, etc.
        err_msg = str(exc)
        logger.exception("place_call failed: %s", err_msg)
        return {
            "call_id": None,
            "status": "failed",
            "error": err_msg,
            "vapi_failed": True,
        }
