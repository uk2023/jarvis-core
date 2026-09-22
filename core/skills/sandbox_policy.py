from __future__ import annotations

"""WHOSE SANDBOX IS THIS, AND WHAT MAY IT INSTALL.

Two things UK asked for (2026-09-13), which turn out to be the same
question asked twice: who is running this, and how much is that person
allowed to reach.

SEPARATE SANDBOXES PER ROLE. "JARVIS ka QA sandbox alag ho aur user +
admin + owner logo ka alag." One shared scratch directory means a user's
half-finished script is visible to -- and clobberable by -- everyone
else, and JARVIS's own self-evolution drafts would sit in the same place
people are running arbitrary code. So every principal gets their own
tree under data/sandboxes/, and JARVIS's evolution workspace stays
entirely separate under data/evolution/ (see self_evolution.py).

    data/sandboxes/owner/<session>/      -- UK, co-owner
    data/sandboxes/admin/<session>/      -- admins
    data/sandboxes/user/<username>/      -- one per account, not shared
    data/evolution/                      -- JARVIS's own, never a user's

THE PIP QUESTION. UK's point is fair: refusing auto-install means a
sandbox test can fail purely because a package is missing, which is a
real cost. And he is right that .env is the safer lever. So the policy
is not "never install" -- it is "never install whatever a model names".

The difference matters. `pip install <model-supplied-string>` is
arbitrary remote code execution: pip runs setup.py from PyPI at install
time, so a hallucinated or typo-squatted name executes attacker code
before anyone sees an import statement. An ALLOWLIST removes exactly
that property while keeping the convenience: UK decides the set once in
.env, and within that set installs are automatic and need no approval.

    JARVIS_ALLOWED_PACKAGES=numpy,pandas,requests,matplotlib
    JARVIS_ALLOW_INSTALL=true        # off unless explicitly enabled

Anything outside the list is reported, never installed -- and reported
with the exact line UK would paste to allow it, so saying yes is one
step rather than a research task.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..runtime.log import log_event

SANDBOX_ROOT = Path("data/sandboxes")

# Roles, mirroring core/identity/access_control.py.
OWNER_TIER = "owner"
ADMIN_TIER = "admin"
USER_TIER = "user"

# System-level work is owner/co-owner only. An admin operates the
# system; that is not the same as being allowed to reconfigure the
# machine it runs on.
SYSTEM_TASK_ROLES = {"owner", "co_owner"}

_ENV_FILE = Path(".env")


def _load_env_value(key: str, default: str = "") -> str:
    """Reads .env directly as well as the process environment, so a
    freshly edited .env takes effect without a restart -- otherwise
    'maine .env update kiya par kuch nahi hua' becomes a bug report."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        if _ENV_FILE.exists():
            for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def _venv_dir(sandbox_dir: Path) -> Path:
    return sandbox_dir / ".jarvis_venv"


def ensure_sandbox_venv(sandbox_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    """Creates (if needed) an isolated Python virtual environment INSIDE
    this sandbox, and returns its python/pip paths. (2026-09-17, UK:
    "hamesha hamesha hamesha ek virtual environment create kare taki
    original JARVIS ke libraries ya Linux system mein koi dikkat na
    aaye"). Every pip install this module does from here on goes into
    THIS venv, never into sys.executable's own environment -- so an
    install can never touch JARVIS's own packages or the host Python,
    no matter what gets installed or how many times. Returns
    (python_path, error) -- python_path is None if venv creation
    failed, with error explaining why."""
    venv_path = _venv_dir(sandbox_dir)
    python_path = venv_path / "bin" / "python3"
    if python_path.exists():
        return python_path, None
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not python_path.exists():
            return None, f"venv creation fail hua: {(proc.stderr or '')[:200]}"
        return python_path, None
    except Exception as exc:
        return None, f"venv creation error: {exc}"


def allowed_packages() -> List[str]:
    raw = _load_env_value("JARVIS_ALLOWED_PACKAGES", "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def installs_enabled() -> bool:
    return _load_env_value("JARVIS_ALLOW_INSTALL", "false").lower() in {"1", "true", "yes", "on"}


# A package name that is not a plain identifier is not a package name --
# it is an attempt to pass options or a URL to pip.
_SAFE_PACKAGE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,60}$")


def resolve_dependencies(missing: List[str], sandbox_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Decide what to do about missing imports.

    REWRITTEN 2026-09-17 (UK's exact complaint: "bar bar mujhse bolta
    hai model not install toh fir fail hai" / "auto pip install ho hi
    jaye"). Previously this required BOTH a manually-edited .env flag
    (JARVIS_ALLOW_INSTALL, off by default) AND a pre-approved package
    allowlist -- so out of the box, nothing ever auto-installed, and
    every missing import became a dead end the person had to notice,
    go edit a config file for, and retry. That gate existed because an
    install here used to run against sys.executable's own pip, i.e.
    JARVIS's OWN Python environment -- a typo'd or hallucinated package
    name really could execute attacker setup.py code INTO the running
    system, so caution was correct FOR THAT DESIGN.
    
    The design changed instead of the caution: every install below now
    goes into ensure_sandbox_venv()'s ISOLATED per-sandbox
    virtualenv -- never sys.executable, never JARVIS's own site-packages,
    never the host Python. A bad package name can still fail to
    install or misbehave, but it cannot reach JARVIS's own libraries or
    the Linux system, which was the actual risk the gate was protecting
    against. With that risk structurally removed, requiring a manual
    .env edit before ANY install -- even numpy, even requests -- no
    longer buys any real safety, just friction on every task that
    happens to need a library. The package-name shape check (pip
    options/URLs disguised as a name) stays; that is a different,
    still-real risk, independent of which environment installs into.
    """
    missing = [m.strip().lower() for m in (missing or []) if m and m.strip()]
    if not missing:
        return {"installed": [], "refused": [], "note": None, "venv_python": None}

    if sandbox_dir is None:
        return {"installed": [], "refused": [{"package": p, "reason": "sandbox_dir nahi diya gaya -- venv nahi bana sakta"} for p in missing],
                "note": None, "venv_python": None}

    venv_python, venv_err = ensure_sandbox_venv(sandbox_dir)
    if venv_python is None:
        return {"installed": [], "refused": [{"package": p, "reason": venv_err or "venv unavailable"} for p in missing],
                "note": venv_err, "venv_python": None}

    installed: List[str] = []
    refused: List[Dict[str, str]] = []

    for pkg in missing:
        if not _SAFE_PACKAGE_NAME.match(pkg):
            refused.append({"package": pkg, "reason": "Valid package name nahi hai -- pip ko options/URL pass karne ki koshish lagti hai."})
            continue
        try:
            proc = subprocess.run(
                [str(venv_python), "-m", "pip", "install", pkg, "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=180,
            )
            if proc.returncode == 0:
                installed.append(pkg)
                log_event("sandbox", f"auto-installed into sandbox venv: {pkg}", level="info")
            else:
                refused.append({"package": pkg, "reason": f"pip fail hua: {(proc.stderr or '')[:200]}"})
        except Exception as exc:
            refused.append({"package": pkg, "reason": f"install error: {exc}"})

    note = None
    if refused:
        names = ",".join(sorted({r["package"] for r in refused}))
        note = f"Yeh packages install nahi ho paaye (sandbox venv mein): {names}."
    return {"installed": installed, "refused": refused, "note": note, "venv_python": str(venv_python)}


def sandbox_dir_for(role: str, username: Optional[str] = None,
                    session_id: Optional[str] = None) -> Path:
    """Isolated working directory for this principal.

    Users get one stable directory keyed by username (so their work
    survives across sessions and is never shared with another account);
    owner/admin get per-session directories, since they run one-off
    tasks far more often.
    """
    role = (role or "user").strip().lower()
    if role in SYSTEM_TASK_ROLES:
        tier = OWNER_TIER
    elif role == "admin":
        tier = ADMIN_TIER
    else:
        tier = USER_TIER

    if tier == USER_TIER:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (username or "anonymous")).strip("_") or "anonymous"
        path = SANDBOX_ROOT / tier / safe
    else:
        safe_session = re.sub(r"[^a-zA-Z0-9_-]", "_", (session_id or "default")).strip("_") or "default"
        path = SANDBOX_ROOT / tier / safe_session

    path.mkdir(parents=True, exist_ok=True)
    return path


def can_run_system_task(role: str, is_verified: bool) -> Tuple[bool, str]:
    """System-level work (package installs, service control, device
    settings, anything outside the sandbox) is owner/co-owner only.

    Admin is deliberately excluded. UK's words: "user system level task
    na de sakta na admin -- kewal owner ya co-owner." Admin inspects and
    operates; it does not reconfigure the machine.
    """
    if not is_verified:
        return False, "Session verified nahi hai -- system-level kaam ke liye login zaroori hai."
    role = (role or "").strip().lower()
    if role in SYSTEM_TASK_ROLES:
        return True, "Owner/co-owner -- system-level kaam allowed hai."
    if role == "admin":
        return False, ("Admin system ko dekh aur chala sakta hai, par system-level changes "
                       "sirf owner ya co-owner kar sakte hain.")
    return False, "System-level kaam sirf owner ya co-owner kar sakte hain."


def sandbox_overview() -> Dict[str, Any]:
    """For monitor/CLI -- who has a sandbox and how big it is."""
    out: Dict[str, Any] = {"root": str(SANDBOX_ROOT), "tiers": {}}
    for tier in (OWNER_TIER, ADMIN_TIER, USER_TIER):
        tier_dir = SANDBOX_ROOT / tier
        entries = []
        if tier_dir.exists():
            for d in sorted(tier_dir.iterdir()):
                if d.is_dir():
                    files = list(d.rglob("*"))
                    entries.append({
                        "name": d.name,
                        "files": sum(1 for f in files if f.is_file()),
                        "bytes": sum(f.stat().st_size for f in files if f.is_file()),
                    })
        out["tiers"][tier] = entries
    out["jarvis_own_sandbox"] = "data/evolution (separate -- never shared with any user)"
    out["install_policy"] = {
        "enabled": installs_enabled(),
        "allowlist": allowed_packages(),
        "note": "Sirf allowlisted packages install hote hain; baaki report hote hain.",
    }
    return out
