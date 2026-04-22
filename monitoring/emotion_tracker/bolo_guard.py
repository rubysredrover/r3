"""Bolo permission guard for MARS skills.

OPT-IN only. Skills run freely by default (for the dev team).
Bolo checks only happen when:
  - A request comes through the Bolo relay (has a sender_handle)
  - A skill explicitly calls check_access()

This never blocks the dev team's work. It only gates external
users (Mom, PCA, Grandma) who access MARS through Bolo.
"""

import os
import json
import urllib.request
import urllib.error


BOLO_API_KEY = os.environ.get("BOLO_API_KEY", "")
BOLO_BASE_URL = os.environ.get("BOLO_BASE_URL", "https://api.bolospot.com")
MARS_WIDGET_SLUG = "mars"

# DEMO MODE: log access checks but never block
DEMO_MODE = os.environ.get("BOLO_ENFORCE", "false").lower() != "true"


def check_access(requester_handle: str, scope: str, parameters: dict = None) -> dict:
    """Check if a @handle has been granted a specific MARS scope.

    Only call this when a request comes through Bolo relay.
    Direct/local requests skip this entirely.

    Args:
        requester_handle: The @handle of the person asking
        scope: The required scope (e.g., "mood:read")
        parameters: Optional — check grant parameters (e.g., spending_limit)

    Returns:
        {"allowed": True/False, "reason": "...", "grant_params": {...}}
    """
    if DEMO_MODE:
        print(f"[Bolo Guard] DEMO MODE — would check @{requester_handle} for {scope} — allowing")
        return {"allowed": True, "reason": "demo mode"}

    if not requester_handle:
        # no handle = local/direct request, always allow
        return {"allowed": True, "reason": "local request"}

    if not BOLO_API_KEY:
        # no API key configured = dev mode, always allow
        return {"allowed": True, "reason": "dev mode (no BOLO_API_KEY)"}

    clean = requester_handle.lstrip("@").lower()
    url = f"{BOLO_BASE_URL}/api/@{clean}/access/key"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {BOLO_API_KEY}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        # Bolo unreachable — fail open in dev, fail closed in production
        if os.environ.get("BOLO_STRICT"):
            return {"allowed": False, "reason": "Cannot reach Bolo (strict mode)"}
        return {"allowed": True, "reason": "Bolo unreachable (fail-open)"}

    # find the mars widget in the access result
    for widget in data.get("widgets", []):
        if widget.get("slug") == MARS_WIDGET_SLUG and widget.get("status") == "granted":
            granted_scopes = widget.get("scopes", [])
            grant_params = widget.get("parameters") or {}

            if scope not in granted_scopes:
                return {
                    "allowed": False,
                    "reason": f"@{clean} does not have '{scope}' on mars widget",
                }

            # check parameters if provided
            if parameters:
                param_check = _check_parameters(parameters, grant_params)
                if not param_check["allowed"]:
                    return param_check

            return {
                "allowed": True,
                "reason": "granted",
                "grant_params": grant_params,
            }

    return {
        "allowed": False,
        "reason": f"@{clean} has no access to mars widget",
    }


def _check_parameters(requested: dict, granted: dict) -> dict:
    """Check if requested parameters are within granted limits.

    Example: requested={"amount": 30}, granted={"spending_limit": 25}
    → denied, over spending limit
    """
    # spending limit check
    if "amount" in requested and "spending_limit" in granted:
        if requested["amount"] > granted["spending_limit"]:
            return {
                "allowed": False,
                "reason": f"Amount ${requested['amount']} exceeds limit ${granted['spending_limit']}",
            }

    # time window check
    if "time_window" in granted:
        import datetime
        now = datetime.datetime.now().hour
        start, end = granted["time_window"].get("start", 0), granted["time_window"].get("end", 24)
        if not (start <= now < end):
            return {
                "allowed": False,
                "reason": f"Outside allowed hours ({start}:00 - {end}:00)",
            }

    return {"allowed": True}


def guard_relay_request(sender_handle: str, scope: str, parameters: dict = None):
    """Convenience wrapper for relay requests.

    Returns None if allowed, or an error message string if denied.
    Use in skills:

        denied = guard_relay_request(sender, "mood:read")
        if denied:
            return denied, SkillResult.FAILURE
    """
    result = check_access(sender_handle, scope, parameters)
    if result["allowed"]:
        return None
    return f"Access denied: {result['reason']}"
