"""Bolo grant + handle lookup tool.

Backed by the Bolo HTTP API (see calendar project apps/api). Falls back to
deterministic mocks when BOLO_API_KEY is missing so the demo flow can run end
to end with no secrets configured.

Three grants are seeded for the demo:
    @mom      → @ruby   widget=mars      (food/payment/vendors/dietary/comms)
    @chantal  → @ruby   widget=voice     (donated radio voice for outbound calls)
    @ruby     → @mars   widget=voice     (Ruby's consent to use her voice for input)
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BOLO_API_URL = os.environ.get("BOLO_API_URL", "http://localhost:3000")
BOLO_API_KEY = os.environ.get("BOLO_API_KEY")

_MOCK_MARS_GRANT = {
    "grantor": "@mom",
    "grantee": "@ruby",
    "widget": "mars",
    "scopes": {
        "actions:order_food": True,
        "actions:place_call": True,
        "payment:charge": True,
        "payment:max_per_order": 25,
        "vendors:allowlist": ["dominos", "papa_johns", "folinos"],
        # Vendor contact info — separate scope from the allowlist so consent
        # (the name) and logistics (the number) can be revoked independently.
        # Mom-approved numbers only; the agent will not dial anything not here.
        "vendors:directory": {
            "folinos": {
                "display": "Folino's",
                "phone": "+16463258481",
                "approved_by": "@mom",
                "approved_at": "2026-04-29T08:00:00Z",
            },
            "dominos": {"display": "Domino's", "phone": None},
            "papa_johns": {"display": "Papa John's", "phone": None},
        },
        # Mom-authorized payment method. Stripe's canonical test card number —
        # this is INTENTIONALLY a test card and never a real one. Real card
        # details would be tokenized via Stripe and the token stored here, not
        # the PAN. The card lives in the grant so revoking the grant revokes
        # the agent's ability to charge anything.
        "payment:card": {
            "test_mode": True,
            "brand": "Visa",
            "number": "4242424242424242",
            "exp": "12/27",
            "cvc": "123",
            "zip": "10001",
            "name_on_card": "Ruby Cossette",
        },
        # Mom-authorized delivery address. Same trust model — agent can only
        # have orders delivered to addresses Mom has put in the grant.
        "delivery:address": {
            "name": "Ruby Cossette",
            "line1": "123 Main Street",
            "city": "New York",
            "state": "NY",
            "zip": "10014",
            "callback_phone": "+16463258481",
            "delivery_notes": "Please knock loudly.",
        },
        "dietary:no_tree_nuts": True,
        "communications:notify_mom": True,
    },
    "granted_at": "2026-04-29T08:00:00Z",
    "revocable": True,
}

# Chantal — radio DJ ("Chantal on the Radio") — donated her voice to Ruby for
# the outbound calls Ruby's agent makes on her behalf. Modeled as a peer-to-peer
# Bolo grant: @chantal grants @ruby permission to use her voice for outbound
# calls. Revocable. The voice clone ID lives in the grant metadata so the agent
# resolves it dynamically rather than via a hardcoded env var.
_MOCK_CHANTAL_VOICE_GRANT = {
    "grantor": "@chantal",
    "grantee": "@ruby",
    "widget": "voice",
    "scopes": {
        "outbound_calls": True,
        "elevenlabs_voice_id": os.environ.get(
            "CHANTAL_VOICE_ID", "vAfuZdldSpxthmIQYOBC"
        ),
        "platform": "elevenlabs",
        "context": (
            "Donated by 'Chantal on the Radio' — "
            "a working broadcaster lending her voice to Ruby for moments "
            "the world doesn't slow down for."
        ),
    },
    "granted_at": "2026-04-26T00:00:00Z",
    "revocable": True,
}

# Ruby grants her agent (MARS) permission to use her cloned voice for the
# *input* side of the demo — so judges can ask the agent to handle any utterance,
# not just pre-recorded ones. This is the consent record for voice cloning, modeled
# as a peer-to-peer Bolo grant from the person to the agent. Revocable.
_MOCK_RUBY_VOICE_GRANT = {
    "grantor": "@ruby",
    "grantee": "@mars",
    "widget": "voice",
    "scopes": {
        "demo_input": True,
        "elevenlabs_voice_id": os.environ.get("RUBY_VOICE_ID", ""),
        "platform": "elevenlabs",
        "context": (
            "Ruby's own voice, cloned with her family's full consent, "
            "used so the agent can be tested live on any utterance."
        ),
    },
    "granted_at": "2026-04-29T08:00:00Z",
    "revocable": True,
}


def _mock_reason(missing: str) -> None:
    msg = f"[mock] reason: missing {missing}"
    print(msg, file=sys.stderr)
    logger.warning(msg)


def _mock_grant_for(grantor: str, widget: str) -> dict:
    """Return the right mock grant for the requested (grantor, widget) tuple."""
    if grantor == "@ruby" and widget == "voice":
        return dict(_MOCK_RUBY_VOICE_GRANT)
    if grantor == "@chantal" or widget == "voice":
        return dict(_MOCK_CHANTAL_VOICE_GRANT)
    return dict(_MOCK_MARS_GRANT)


async def get_grants(grantor: str, grantee: str, widget: str = "mars") -> dict:
    """Fetch the grant tuple (grantor, grantee, widget) from Bolo."""
    if not BOLO_API_KEY:
        _mock_reason("BOLO_API_KEY")
        return _mock_grant_for(grantor, widget)

    headers = {"Authorization": f"Bearer {BOLO_API_KEY}"}
    params = {"grantor": grantor, "grantee": grantee, "widget": widget}
    url = f"{BOLO_API_URL.rstrip('/')}/api/grants"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.exception("get_grants failed, falling back to mock: %s", exc)
        _mock_reason("BOLO_API_URL unreachable")
        return _mock_grant_for(grantor, widget)


async def notify_mom(message: str, kind: str = "info", details: Optional[dict] = None) -> dict:
    """Push a notification through Bolo to Mom's app.

    Bolo is the comms backbone here — the same trust layer that holds the
    grants also relays the activity feed back to the granting party. Mom
    granted Ruby's agent these permissions; Bolo keeps her in the loop on
    every action it takes on her behalf.
    """
    payload = {
        "grantee": "@ruby",
        "audience": "@mom",
        "message": message,
        "kind": kind,
        "details": details or {},
    }
    if not BOLO_API_KEY:
        _mock_reason("BOLO_API_KEY")
        logger.info("[mock notify_mom] %s", message)
        return {"ok": True, "mocked": True, **payload}

    headers = {"Authorization": f"Bearer {BOLO_API_KEY}"}
    url = f"{BOLO_API_URL.rstrip('/')}/api/activity"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.exception("notify_mom failed, falling back to mock: %s", exc)
        return {"ok": True, "mocked": True, "error": str(exc), **payload}


async def lookup_handle(email: str) -> Optional[dict]:
    """Resolve an email to a Bolo handle record, or None if not found."""
    if not BOLO_API_KEY:
        _mock_reason("BOLO_API_KEY")
        return {"handle": "@ruby", "email": email, "display_name": "Ruby"}

    headers = {"Authorization": f"Bearer {BOLO_API_KEY}"}
    url = f"{BOLO_API_URL.rstrip('/')}/api/handles/lookup"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"email": email})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.exception("lookup_handle failed, falling back to mock: %s", exc)
        _mock_reason("BOLO_API_URL unreachable")
        return {"handle": "@ruby", "email": email, "display_name": "Ruby"}
