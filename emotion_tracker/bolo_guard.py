"""Bolo permission guard for MARS skills.

Before any skill executes, it checks with Bolospot whether the
requesting user has been granted the required scope by Mom.

Mom controls everything. If she hasn't granted 'mood:read' to
the PCA, the PCA can't ask "how is Ruby feeling?"
"""

import os
import json
import urllib.request
import urllib.error


BOLO_API_KEY = os.environ.get("BOLO_API_KEY", "")
BOLO_BASE_URL = os.environ.get("BOLO_BASE_URL", "https://api.bolospot.com")
MARS_WIDGET_SLUG = "mars"


def check_access(requester_handle: str, scope: str) -> bool:
    """Check if a @handle has been granted a specific MARS scope.

    Args:
        requester_handle: The @handle of the person asking (e.g., "@pca_jane")
        scope: The required scope (e.g., "mood:read")

    Returns:
        True if access is granted, False otherwise.
    """
    if not BOLO_API_KEY:
        # no API key configured — allow all (dev/hackathon mode)
        return True

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
        # if Bolo is unreachable, fail open in hackathon mode
        print("[Bolo Guard] Could not reach Bolo — allowing access (hackathon mode)")
        return True

    # find the mars widget in the access result
    for widget in data.get("widgets", []):
        if widget.get("slug") == MARS_WIDGET_SLUG and widget.get("status") == "granted":
            granted_scopes = widget.get("scopes", [])
            if scope in granted_scopes:
                return True

    return False


def require_access(requester_handle: str, scope: str) -> str | None:
    """Check access and return an error message if denied.

    Returns None if access is granted, or an error message if denied.
    """
    if check_access(requester_handle, scope):
        return None

    return (
        f"Access denied. @{requester_handle.lstrip('@')} does not have "
        f"'{scope}' permission for MARS. Ask Mom to grant access via Bolo."
    )
