from __future__ import annotations

"""Real auth routes -- backs client.ts's api.login()/signup() for real
this time (2026-09-12). Wires directly to core/identity/user_store.py
and session_tokens.py; issues real tokens the frontend must send back
on every subsequent request via `Authorization: Bearer <token>`.
"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from core.identity import user_store, session_tokens
from core.identity.access_control import Speaker, OWNER, ADMIN, USER

router = APIRouter(prefix="/api/auth", tags=["auth"])

user_store.ensure_owner_seeded()


class SignupBody(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class LoginBody(BaseModel):
    username: str
    password: str


def get_speaker(authorization: Optional[str] = Header(None)) -> Speaker:
    """FastAPI dependency -- every protected route takes
    `speaker: Speaker = Depends(get_speaker)` and gets back a REAL
    Speaker resolved from a verified token, never from a client-
    supplied role claim. No valid token -> lowest-trust USER,
    unverified -- the same conservative default as remote_session()
    in access_control.py, applied consistently everywhere."""
    if not authorization or not authorization.startswith("Bearer "):
        return Speaker(role=USER, is_verified=False)
    token = authorization[len("Bearer "):].strip()
    user = session_tokens.verify_token(token)
    if user is None:
        return Speaker(role=USER, is_verified=False)
    return Speaker(role=user.role, display_name=user.display_name, is_verified=True)


def require_owner(speaker: Speaker) -> None:
    if speaker.role != OWNER or not speaker.is_verified:
        raise HTTPException(status_code=403, detail="Owner authorization required.")


@router.post("/signup")
def signup(body: SignupBody):
    try:
        user = user_store.signup(body.username, body.password, body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = session_tokens.issue_token(user.username)
    return {"success": True, "token": token, "role": user.role, "username": user.username, "display_name": user.display_name}


@router.post("/login")
def login(body: LoginBody, request: Request = None):
    # RATE LIMIT before any password work. Without this, the constant-
    # time comparison and 200k-iteration KDF protect the hash but do
    # nothing against someone simply trying thousands of passwords.
    client_ip = "unknown"
    try:
        if request is not None and request.client:
            client_ip = request.client.host or "unknown"
    except Exception:
        pass
    try:
        from .routes_voice_call import check_login_rate, clear_login_rate
        gate = check_login_rate(client_ip)
        if not gate["allowed"]:
            raise HTTPException(status_code=429, detail=gate["message"],
                                headers={"Retry-After": str(gate["retry_after"])})
    except HTTPException:
        raise
    except Exception:
        clear_login_rate = None  # rate limiting unavailable; login still works

    user = user_store.verify_login(body.username, body.password)
    if user is None:
        # Deliberately identical error for "no such user" and "wrong
        # password" -- distinguishing them lets an attacker enumerate
        # which usernames exist.
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    # Success clears the counter -- a legitimate user should not be
    # locked out by their own earlier typos.
    try:
        if clear_login_rate:
            clear_login_rate(client_ip)
    except Exception:
        pass
    token = session_tokens.issue_token(user.username)
    return {"success": True, "token": token, "role": user.role, "username": user.username, "display_name": user.display_name}


@router.get("/me")
def me(authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    return speaker.as_dict()


@router.post("/request_admin")
def request_admin_role(authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    if not speaker.is_verified or speaker.role != USER:
        raise HTTPException(status_code=400, detail="Only a logged-in regular user can request admin.")
    user_store.request_admin(speaker.display_name or "")
    return {"success": True, "status": "pending", "message": "Request sent -- the owner must approve it."}


@router.get("/pending_admin_requests")
def pending_admin_requests(authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    require_owner(speaker)
    return {"pending": user_store.list_pending_admin_requests()}


@router.post("/approve_admin/{username}")
def approve_admin_route(username: str, authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    require_owner(speaker)
    ok = user_store.approve_admin(username)
    if not ok:
        raise HTTPException(status_code=404, detail="No pending user with that username.")
    return {"success": True, "username": username, "role": "admin"}


@router.post("/reject_admin/{username}")
def reject_admin_route(username: str, authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    require_owner(speaker)
    ok = user_store.reject_admin(username)
    if not ok:
        raise HTTPException(status_code=404, detail="No pending user with that username.")
    return {"success": True, "username": username, "status": "rejected"}


class SetRoleBody(BaseModel):
    role: str  # 'co_owner' | 'admin' | 'user' -- never 'owner'


@router.post("/set_role/{username}")
def set_role_route(username: str, body: SetRoleBody, authorization: Optional[str] = Header(None)):
    """OWNER-ONLY promotion/demotion (co_owner / admin / user).
    require_owner rejects a co-owner and an admin too -- only UK grants
    roles. Note there is no endpoint anywhere that returns a password:
    only PBKDF2 hashes are stored, so not even the owner can read one."""
    speaker = get_speaker(authorization)
    require_owner(speaker)
    try:
        ok = user_store.set_role(username, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="No such account, or it is the owner account (which cannot be changed).")
    return {"success": True, "username": username, "role": body.role}


@router.post("/terminate_account/{username}")
def terminate_account_route(username: str, authorization: Optional[str] = Header(None)):
    """OWNER-ONLY. The owner's own account is protected from deletion."""
    speaker = get_speaker(authorization)
    require_owner(speaker)
    if not user_store.terminate_account(username):
        raise HTTPException(status_code=404, detail="No such account, or it is the owner account (which cannot be deleted).")
    return {"success": True, "username": username, "terminated": True}


@router.post("/revoke_admin/{username}")
def revoke_admin_route(username: str, authorization: Optional[str] = Header(None)):
    speaker = get_speaker(authorization)
    require_owner(speaker)
    ok = user_store.revoke_admin(username)
    if not ok:
        raise HTTPException(status_code=404, detail="No admin with that username.")
    return {"success": True, "username": username, "role": "user"}
