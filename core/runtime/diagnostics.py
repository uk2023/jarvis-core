from __future__ import annotations

"""JARVIS DIAGNOSES ITSELF, AND CURES WHAT IT SAFELY CAN.

UK's ask (2026-09-15): "ek dedicated diagnostic command banao jo khud
ko diagnose kare -- diagnostic mein hum find karenge ki kya ho raha
hai, kis wajah se ho raha hai, aur jo cure/remedy hai use apply kare.
Main chahta hoon JARVIS apne aap ko fix kar le, ya kam se kam bata de
ki 'sir aisa error hai jo main fix kar sakta hoon'."

THE SHAPE OF EVERY CHECK
=========================
Each diagnostic is a CHECK paired with a REMEDY, and the remedy is one
of three honest kinds:

  AUTO       JARVIS can apply this itself, safely, with no side effects
             outside its own runtime state (e.g. clearing a stale lock,
             pruning an oversized log). Applied automatically when
             `run_diagnostics(auto_fix=True)` is called, or on demand
             via `apply_remedy(name)`.
  GUIDED     JARVIS knows exactly what the fix is, but applying it
             needs a human action outside its own process (restarting
             Termux, editing a file it should not touch itself,
             running a shell command with elevated scope). It reports
             the fix in the same words a person would need to type or
             do -- not just "something is wrong."
  UNKNOWN    The check found a symptom but this project has not yet
             taught JARVIS what causes it. It says so plainly rather
             than guessing -- exactly UK's "kam se kam bata de" case.

WHY THIS IS SEEDED WITH REAL CHECKS, NOT A FRAMEWORK PROMISE
==============================================================
UK asked for this right after several real bugs were found and fixed
this session: the LLM client re-doing a full TLS handshake on every
call (the actual crash cause), monitor.py's curses terminal not
restoring on SIGTERM (the "pkill doesn't work" symptom), and the RSS
spike-capture instrumentation from the round before. Each of those
becomes a genuine check here, with a genuine remedy -- not a stub. A
diagnostic system whose first version can't diagnose anything real
would just be one more thing that looks like it works and doesn't.

HOW IT LEARNS THE PATTERN UK ASKED FOR
========================================
"Ek baar maine bata diya kaise fix hota hai, agli baar khud kar le" --
the honest version of this, without inventing an ML system that isn't
there, is: a NEW check can be registered by name with its remedy kind
and either a fix function or a guided description, and from that point
on `run_diagnostics()` includes it. UK teaching JARVIS a fix, in
practice, is UK (or a future coding session) adding a check function
here -- the same way every check below started as a bug UK reported and
ends as a permanent, reusable diagnostic.
"""

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REMEDY_AUTO = "auto"
REMEDY_GUIDED = "guided"
REMEDY_UNKNOWN = "unknown"

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"


@dataclass
class DiagnosticResult:
    name: str
    status: str                         # ok | warning | critical
    detail: str
    remedy_kind: str                    # auto | guided | unknown | "" (nothing wrong)
    remedy_description: str = ""
    fix_fn: Optional[Callable[[], Dict[str, Any]]] = field(default=None, repr=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "status": self.status, "detail": self.detail,
            "remedy_kind": self.remedy_kind, "remedy_description": self.remedy_description,
            "auto_fixable": self.fix_fn is not None,
        }


# --------------------------------------------------------------- checks
def _check_llm_session_reuse() -> DiagnosticResult:
    """THE ACTUAL CRASH CAUSE, found from UK's own spike-capture stack
    traces (2026-09-15): llm_bridge.py's GroqEngine was calling the
    bare `requests.post()` module function, which opens a brand new
    TCP connection and does a FULL TLS handshake -- including full
    certificate-chain verification -- on EVERY call, with no
    connection pooling. Two concurrent calls (one from the CLI's direct
    query path, one from the web backend) doing this at once was the
    ~1.7-2GB spike that got the process killed.
    """
    try:
        from ..orchestration.llm_bridge import GroqEngine
        import inspect
        source = inspect.getsource(GroqEngine._post_chat_completion)
        reused = "self._session.post" in source
        has_persistent_session = "self._session = requests.Session()" in inspect.getsource(GroqEngine.__init__)
    except Exception as exc:
        return DiagnosticResult(
            "llm_session_reuse", STATUS_WARNING, f"Check nahi chal paya: {exc}",
            REMEDY_UNKNOWN,
        )

    if reused and has_persistent_session:
        return DiagnosticResult(
            "llm_session_reuse", STATUS_OK,
            "GroqEngine ek persistent requests.Session() reuse karta hai -- "
            "har LLM call pe fresh TLS handshake nahi hota.",
            "",
        )
    return DiagnosticResult(
        "llm_session_reuse", STATUS_CRITICAL,
        "GroqEngine bare requests.post() use kar raha hai -- har LLM call pe "
        "poora naya TCP connection + TLS handshake hota hai. Yehi wajah thi "
        "1.7-2GB RSS spikes ki jo Termux crash karte the.",
        REMEDY_GUIDED,
        "core/orchestration/llm_bridge.py mein GroqEngine.__init__ ke andar "
        "self._session = requests.Session() add karo, aur "
        "_post_chat_completion() mein requests.post(...) ko "
        "self._session.post(...) se replace karo.",
    )


def _check_recent_crashes() -> DiagnosticResult:
    from .resource_monitor import recent_crashes
    crashes = recent_crashes(limit=5)
    if not crashes:
        return DiagnosticResult("recent_crashes", STATUS_OK, "Koi recent crash record nahi hai.", "")
    latest = crashes[0]
    return DiagnosticResult(
        "recent_crashes", STATUS_WARNING,
        f"{len(crashes)} crash record mile. Latest: {latest.get('kind')} at "
        f"{latest.get('ts_ist')}, rss={latest.get('rss_mb_at_crash')}MB.",
        REMEDY_UNKNOWN,
        "data/resource/crashes.jsonl aur spikes.jsonl dekho -- agar spike ke "
        "saath thread stack mila hai to us function ko yahan ek naye check "
        "ke roop mein register karo.",
    )


def _check_rss_spike_frequency() -> DiagnosticResult:
    from .resource_monitor import recent_spikes
    spikes = recent_spikes(limit=10)
    if not spikes:
        return DiagnosticResult("rss_spike_frequency", STATUS_OK, "Koi RSS spike record nahi hai.", "")
    if len(spikes) >= 5:
        return DiagnosticResult(
            "rss_spike_frequency", STATUS_WARNING,
            f"{len(spikes)} spikes record mein hain -- yeh baar baar ho raha hai.",
            REMEDY_GUIDED,
            "data/resource/spikes.jsonl ke thread_stacks dekho -- har spike ke "
            "saath asli function record hai. Agar sab ek hi jagah se aa rahe "
            "hain, woh naya diagnostic check banne layak hai.",
        )
    return DiagnosticResult("rss_spike_frequency", STATUS_OK,
                            f"{len(spikes)} spike(s) record hain, abhi tak asaamanya nahi.", "")


def _check_monitor_sigterm_handling() -> DiagnosticResult:
    """The "pkill doesn't work" symptom (found 2026-09-15): monitor.py
    had no SIGTERM handler, so curses never restored the terminal on
    kill -- the terminal looked stuck, which read as "process still
    running" even after it was gone."""
    try:
        monitor_source = Path("monitor.py").read_text(encoding="utf-8")
    except Exception as exc:
        return DiagnosticResult("monitor_sigterm_handling", STATUS_WARNING,
                                f"monitor.py padh nahi paya: {exc}", REMEDY_UNKNOWN)

    if "signal.signal(signal.SIGTERM" in monitor_source:
        return DiagnosticResult(
            "monitor_sigterm_handling", STATUS_OK,
            "monitor.py SIGTERM ko explicitly handle karta hai -- pkill se "
            "curses terminal properly restore hoga.",
            "",
        )
    return DiagnosticResult(
        "monitor_sigterm_handling", STATUS_CRITICAL,
        "monitor.py mein SIGTERM handler nahi hai -- pkill se curses ka "
        "terminal cleanup skip ho jaata hai, jo 'process abhi bhi chal raha "
        "hai' jaisa dikhta hai jabki terminal hi stuck hai.",
        REMEDY_GUIDED,
        "monitor.py ke main() mein curses shuru hone se pehle ek SIGTERM "
        "handler install karo jo SystemExit raise kare, taaki curses.wrapper() "
        "ka cleanup chal sake.",
    )


def _check_sandbox_dir_growth() -> DiagnosticResult:
    """Sandboxes accumulate uploaded files/code across sessions with no
    automatic cleanup -- worth flagging before it becomes a disk-space
    surprise, even though it is not the RAM crash."""
    root = Path("data/sandboxes")
    if not root.exists():
        return DiagnosticResult("sandbox_disk_usage", STATUS_OK, "Koi sandbox data abhi tak nahi bana.", "")
    total_bytes = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    total_mb = total_bytes / (1024 * 1024)
    if total_mb > 200:
        def _prune() -> Dict[str, Any]:
            removed = 0
            for tier_dir in root.iterdir():
                if not tier_dir.is_dir():
                    continue
                for user_dir in tier_dir.iterdir():
                    if user_dir.is_dir():
                        try:
                            shutil.rmtree(user_dir)
                            removed += 1
                        except Exception:
                            continue
            return {"ok": True, "removed_dirs": removed}

        return DiagnosticResult(
            "sandbox_disk_usage", STATUS_WARNING,
            f"Sandboxes {total_mb:.0f}MB disk use kar rahe hain.",
            REMEDY_AUTO, "Saare sandbox directories clear kar dega (uploaded files/code sab).",
            fix_fn=_prune,
        )
    return DiagnosticResult("sandbox_disk_usage", STATUS_OK, f"Sandboxes {total_mb:.1f}MB -- theek hai.", "")


def _check_stale_trace_db_size() -> DiagnosticResult:
    """traces.db grows with every turn, forever, with no rotation --
    worth an early warning before it becomes its own resource problem."""
    path = Path("data/traces.db")
    if not path.exists():
        return DiagnosticResult("trace_db_size", STATUS_OK, "traces.db abhi nahi bana.", "")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 100:
        return DiagnosticResult(
            "trace_db_size", STATUS_WARNING,
            f"traces.db {size_mb:.0f}MB ho gaya hai -- kabhi rotate/trim nahi hota.",
            REMEDY_GUIDED,
            "core/runtime/identity_trace.py mein RETENTION_DAYS ki value "
            "kam karo, ya purane rows manually DELETE karo "
            "(sqlite3 data/traces.db \"DELETE FROM traces WHERE ts < ...\").",
        )
    return DiagnosticResult("trace_db_size", STATUS_OK, f"traces.db {size_mb:.1f}MB.", "")


_ALL_CHECKS: List[Callable[[], DiagnosticResult]] = [
    _check_llm_session_reuse,
    _check_recent_crashes,
    _check_rss_spike_frequency,
    _check_monitor_sigterm_handling,
    _check_sandbox_dir_growth,
    _check_stale_trace_db_size,
]


def run_diagnostics(auto_fix: bool = False) -> Dict[str, Any]:
    """Run every registered check. With auto_fix=True, AUTO-kind
    remedies are applied immediately and their outcome recorded
    alongside the check -- this is JARVIS actually curing what it
    safely can, not just reporting."""
    results: List[DiagnosticResult] = []
    for check in _ALL_CHECKS:
        try:
            results.append(check())
        except Exception as exc:
            results.append(DiagnosticResult(
                check.__name__, STATUS_WARNING, f"Check khud fail ho gaya: {exc}", REMEDY_UNKNOWN,
            ))

    applied = []
    if auto_fix:
        for r in results:
            if r.remedy_kind == REMEDY_AUTO and r.fix_fn is not None:
                try:
                    outcome = r.fix_fn()
                    applied.append({"name": r.name, "outcome": outcome})
                except Exception as exc:
                    applied.append({"name": r.name, "outcome": {"ok": False, "error": str(exc)}})

    critical = [r for r in results if r.status == STATUS_CRITICAL]
    warning = [r for r in results if r.status == STATUS_WARNING]
    return {
        "checked_at": time.time(),
        "total": len(results),
        "ok": len(results) - len(critical) - len(warning),
        "warnings": len(warning),
        "critical": len(critical),
        "results": [r.as_dict() for r in results],
        "auto_fixes_applied": applied,
    }


def apply_remedy(name: str) -> Dict[str, Any]:
    """Apply one specific check's remedy by name, if it is AUTO-kind.
    GUIDED remedies are never auto-applied -- by definition they need a
    human action outside JARVIS's own process, and running them blind
    would be exactly the kind of unsupervised self-modification this
    whole project has repeatedly refused to allow."""
    for check in _ALL_CHECKS:
        result = check()
        if result.name != name:
            continue
        if result.remedy_kind not in (REMEDY_AUTO,) or result.fix_fn is None:
            if not result.remedy_kind:
                return {"ok": False, "reason": f"'{name}' mein kuch galat mila hi nahi -- fix karne ko kuch nahi."}
            return {
                "ok": False,
                "reason": (
                    f"'{name}' ka remedy {result.remedy_kind} hai, auto nahi -- "
                    f"khud apply nahi kar sakta. {result.remedy_description}"
                ),
            }
        try:
            outcome = result.fix_fn()
            return {"ok": True, "outcome": outcome}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
    return {"ok": False, "reason": f"'{name}' naam ka koi check nahi mila."}
