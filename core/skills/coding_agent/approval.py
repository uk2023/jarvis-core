from __future__ import annotations

"""CODING AGENT -- intent-based approval / policy gate (Phase 6).

Decides APPROVE / ASK_USER / DENY for every tool call BEFORE it runs.
Not a blanket auto-approve (that would make "Jarvis owns the agent"
meaningless -- see BLUEPRINT.md) and not approval-fatigue on every
harmless read either (UK's explicit ask: don't ask for everything).

Mirrors the role tiering ALREADY established in
core/skills/sandbox_policy.py (owner / co_owner / admin / user)
rather than inventing a second permissions model that could drift
from it.

DECISION ORDER (first match wins):
  1. secrets/credentials  -> DENY, always, regardless of role
  2. named always-ask ops, or destructive=True, or risk=high
                           -> ASK_USER
  3. outside authorized project scope
                           -> ASK_USER
  4. read_only / low risk -> APPROVE
  5. medium risk           -> APPROVE for owner/co_owner/admin, else ASK_USER
  6. anything unclassified -> ASK_USER (default is to ask, not to guess)
"""

from typing import Any, Dict, Optional

from .tool_contract import RISK_READ_ONLY, RISK_LOW, RISK_MEDIUM, RISK_HIGH

try:
    from ..sandbox_policy import OWNER_TIER, ADMIN_TIER, USER_TIER
except Exception:  # pragma: no cover -- keep the gate usable standalone
    OWNER_TIER, ADMIN_TIER, USER_TIER = "owner", "admin", "user"

APPROVE = "APPROVE"
ASK_USER = "ASK_USER"
DENY = "DENY"

# Operation NAMES that expose secrets/credentials outright -- never
# approved automatically for anyone, no matter the role or risk tag
# a caller attached. This list is intentionally about what the
# operation IS, not what it claims its risk is.
_ALWAYS_DENY_TOOLS = {
    "read_secret_file", "print_env_secret", "exfiltrate_data",
    "expose_credentials", "dump_env",
}

# Path/content markers that make ANY tool touching them a DENY,
# regardless of tool name -- catches a generically-named tool
# ("read_file") being pointed at a secret.
_SECRET_MARKERS = (".env", "secret", "credential", "private_key",
                    "id_rsa", ".pem", ".pfx", "api_key", "apikey")

# Operations that are always destructive enough to need a human yes,
# even for the owner -- UK's own examples: deleting important files,
# destructive DB ops, security-sensitive config changes.
_ALWAYS_ASK_TOOLS = {
    "delete_file", "delete_directory", "git_reset_hard", "git_push_force",
    "drop_database", "truncate_table", "modify_security_config",
    "overwrite_env", "git_clean_force",
}


def _looks_like_secret(*values: Optional[str]) -> bool:
    for v in values:
        low = (v or "").lower()
        if any(marker in low for marker in _SECRET_MARKERS):
            return True
    return False


def decide(*, tool_name: str, risk: str, role: str = "user",
            destructive: bool = False, target: Optional[str] = None,
            scope_authorized: bool = True,
            extra_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Returns {"decision": APPROVE|ASK_USER|DENY, "reason": str}."""
    role = (role or "user").lower()
    ctx = extra_context or {}

    if tool_name in _ALWAYS_DENY_TOOLS or _looks_like_secret(target, ctx.get("content_preview")):
        return {"decision": DENY,
                "reason": f"'{tool_name}' would touch secrets/credentials -- never auto-approved."}

    if tool_name in _ALWAYS_ASK_TOOLS or destructive or risk == RISK_HIGH:
        return {"decision": ASK_USER,
                "reason": f"'{tool_name}' is destructive or high-risk -- needs your explicit yes."}

    if not scope_authorized:
        return {"decision": ASK_USER,
                "reason": f"Target '{target}' is outside the authorized project scope."}

    if risk in (RISK_READ_ONLY, RISK_LOW):
        return {"decision": APPROVE,
                "reason": "Read-only or low-risk and reversible, within authorized scope."}

    if risk == RISK_MEDIUM:
        if role in (OWNER_TIER, "co_owner", ADMIN_TIER):
            return {"decision": APPROVE,
                    "reason": "Medium-risk but reversible, and the role is authorized for it."}
        return {"decision": ASK_USER,
                "reason": "Medium-risk operation -- confirming before proceeding."}

    return {"decision": ASK_USER, "reason": "Unclassified risk -- defaulting to asking, not guessing."}


def audit_line(task_id: str, call, decision: Dict[str, Any]) -> str:
    """One inspectable, human-readable audit line -- policy decisions
    must be legible after the fact, not just correct in the moment."""
    return (f"[{task_id}] {call.tool_name}({call.arguments}) "
            f"-> {decision['decision']}: {decision['reason']}")
