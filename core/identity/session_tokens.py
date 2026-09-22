from __future__ import annotations

"""Session tokens -- signed, verifiable, real. Not the old client.ts
fallback that minted `op-token-${Date.now()}` locally with nothing on
the server able to check it. A token here is
    base64(username.expiry.hmac_hex)
verified with hmac.compare_digest against a server-side secret that
never leaves the backend, so a client can't forge one.
"""

import base64
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Optional

from .user_store import get_user, UserRecord

SECRET_PATH = Path(os.environ.get("JARVIS_SESSION_SECRET_FILE", "data/session_secret.key"))
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _get_secret() -> bytes:
    """Generated once, persisted to disk -- NOT regenerated on every
    process restart, or every existing session would be silently
    invalidated each time JARVIS restarts (a real annoyance UK would
    hit constantly given how often this project gets redeployed)."""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_bytes()
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    SECRET_PATH.write_bytes(secret)
    return secret


def issue_token(username: str) -> str:
    expiry = int(time.time()) + TOKEN_LIFETIME_SECONDS
    payload = f"{username}.{expiry}"
    signature = hmac.new(_get_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}.{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def verify_token(token: str) -> Optional[UserRecord]:
    """Returns the UserRecord the token is valid for, or None -- never
    raises, so callers can treat any failure uniformly as
    unauthenticated rather than needing per-exception handling."""
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, expiry_str, signature = raw.rsplit(".", 2)
        expiry = int(expiry_str)
    except Exception:
        return None
    if time.time() > expiry:
        return None
    expected_payload = f"{username}.{expiry}"
    expected_signature = hmac.new(_get_secret(), expected_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    return get_user(username)
