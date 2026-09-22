from __future__ import annotations

"""SELF-EVOLUTION SANDBOX -- where JARVIS writes its own new features.

UK's requirement (2026-09-13): JARVIS should be able to author its own
sub-modules and features as it finds a need, in its OWN sandbox, with a
full trail, auto-proposing at high confidence -- and CRITICALLY:

    "baaki jo existing structure hai chaah ke bhi JARVIS change na kar
     paye khud ko"

So the single most important thing in this file is not what JARVIS can
write. It is what it CANNOT. A system that can rewrite its own
safeguards has no safeguards, so the protection is structural:

  * Everything JARVIS authors lands under data/evolution/ -- a
    directory that contains no running code paths. Nothing there is
    imported automatically. Adoption into the live tree is a separate,
    human step.

  * PROTECTED_PATHS below can never be written by this module. The
    check resolves real paths rather than comparing strings, because a
    string check is defeated by "core/../core" or a symlink. This
    covers core/ itself, including this file -- JARVIS cannot edit its
    own restrictions.

  * Anything matching a dangerous pattern goes to the approval queue
    regardless of how confident JARVIS is. Confidence is not evidence
    of safety; a confidently wrong model is the normal case, not the
    exception.

The QA pipeline borrows its layered shape from UK's own qa_engine.py
(syntax -> security -> isolated execution). One thing from that file is
deliberately NOT carried over: auto-installing missing pip packages.
Silently running `pip install` on whatever a model names is arbitrary
remote code execution with extra steps -- missing dependencies are
reported and left for a human instead.
"""

import ast
import json
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event

# JARVIS's own workspace. Deliberately under data/, never inside core/.
EVOLUTION_ROOT = Path("data/evolution")
DRAFTS_DIR = EVOLUTION_ROOT / "drafts"          # freshly written, not yet validated
APPROVED_DIR = EVOLUTION_ROOT / "approved"      # passed QA + human approval
REJECTED_DIR = EVOLUTION_ROOT / "rejected"      # failed QA or refused by UK
AUDIT_DB = EVOLUTION_ROOT / "evolution_audit.db"

# NEVER writable by JARVIS, at any confidence, for any reason.
PROTECTED_PATHS = ("core", "backend", "cli.py", "monitor.py", "config")

# Auto-propose threshold. Below this JARVIS records the idea but does
# not act; above it, it may draft and validate -- but still never
# adopts into the live tree by itself.
AUTO_PROPOSE_CONFIDENCE = 0.85

EXECUTION_TIMEOUT = 10

# Operations that require a human decision even when QA passes. These
# are not "bad code" -- they are code whose blast radius extends past
# the sandbox, which is exactly what a human should be reviewing.
_DANGEROUS_PATTERNS = (
    (r"\bos\.system\b", "shell execution"),
    (r"\bsubprocess\.(Popen|run|call|check_output)\b", "subprocess spawn"),
    (r"\beval\s*\(", "eval()"),
    (r"\bexec\s*\(", "exec()"),
    (r"\b__import__\s*\(", "dynamic import"),
    (r"\bshutil\.rmtree\b", "recursive delete"),
    (r"\bos\.remove\b|\bos\.unlink\b", "file deletion"),
    (r"\bopen\s*\([^)]*['\"][wa]", "file write outside sandbox helpers"),
    (r"\bsocket\b|\brequests\.|\burllib\b|\bhttpx\b", "network access"),
    (r"\bpip\s+install\b|\bpip3\s+install\b", "package installation"),
    (r"\bsetattr\b|\bglobals\s*\(\)|\bimportlib\b", "runtime self-modification"),
)


def _init_audit() -> sqlite3.Connection:
    EVOLUTION_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evolution_log (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            feature_name TEXT NOT NULL,
            rationale TEXT,
            confidence REAL,
            status TEXT NOT NULL,
            qa_report TEXT,
            needs_approval INTEGER DEFAULT 0,
            approval_reasons TEXT,
            decided_by TEXT,
            decided_at REAL,
            draft_path TEXT
        )
    """)
    conn.commit()
    return conn


def _record(entry: Dict[str, Any]) -> None:
    try:
        with _init_audit() as conn:
            conn.execute(
                "INSERT INTO evolution_log (id, created_at, feature_name, rationale, confidence,"
                " status, qa_report, needs_approval, approval_reasons, draft_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status=excluded.status, qa_report=excluded.qa_report,"
                " needs_approval=excluded.needs_approval, approval_reasons=excluded.approval_reasons",
                (entry["id"], entry.get("created_at", time.time()), entry["feature_name"],
                 entry.get("rationale"), entry.get("confidence"), entry["status"],
                 json.dumps(entry.get("qa_report") or {}), int(bool(entry.get("needs_approval"))),
                 json.dumps(entry.get("approval_reasons") or []), entry.get("draft_path")),
            )
            conn.commit()
    except Exception as exc:
        log_event("evolution", f"audit write failed: {exc}", level="warning")


def is_protected(target_path: str) -> bool:
    """True if this path is part of the live system JARVIS must not edit.

    Resolved, not string-compared: 'data/evolution/../../core/brain.py'
    and a symlink both have to fail, and only path resolution catches
    them.
    """
    try:
        resolved = Path(target_path).resolve()
        repo_root = Path.cwd().resolve()
        try:
            relative = resolved.relative_to(repo_root)
        except ValueError:
            return True            # outside the project entirely -- refuse
        first = relative.parts[0] if relative.parts else ""
        return first in PROTECTED_PATHS or str(relative) in PROTECTED_PATHS
    except Exception:
        return True                # unresolvable -> treat as protected


def scan_for_danger(code: str) -> List[str]:
    """Returns human-readable reasons this code needs a person to look."""
    found = []
    for pattern, label in _DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            found.append(label)
    return sorted(set(found))


@dataclass
class QAReport:
    syntax_ok: bool = False
    syntax_error: Optional[str] = None
    danger_flags: List[str] = field(default_factory=list)
    missing_imports: List[str] = field(default_factory=list)
    executed: bool = False
    exit_code: Optional[int] = None
    output: str = ""
    duration_ms: float = 0.0
    # LAYER 5 (2026-09-14, UK: "codebox sandbox aur 5-layered QA se lass
    # hona chahiye"). The first four layers (syntax, danger scan,
    # dependency check, isolated execution) already existed for
    # self-evolution proposals. CodeBox runs arbitrary code from a much
    # wider set of callers (UK himself, JARVIS's own coding tool), so it
    # gets a fifth: bounded OUTPUT validation -- did the run actually
    # produce a sane amount of output in a sane amount of time, or does
    # it look like a runaway process that happened to exit 0 (e.g. an
    # infinite print loop killed only by the timeout, which still exits
    # 0 in some shells). Layers 1-4 answer "did it run correctly";
    # layer 5 answers "was the fact that it ran correctly itself
    # trustworthy".
    resource_ok: bool = True
    resource_flags: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.syntax_ok and self.executed and self.exit_code == 0 and self.resource_ok

    def as_dict(self) -> Dict[str, Any]:
        return {
            "syntax_ok": self.syntax_ok, "syntax_error": self.syntax_error,
            "danger_flags": self.danger_flags, "missing_imports": self.missing_imports,
            "executed": self.executed, "exit_code": self.exit_code,
            "output": self.output[:2000], "duration_ms": round(self.duration_ms, 2),
            "resource_ok": self.resource_ok, "resource_flags": self.resource_flags,
            "passed": self.passed,
            "layers": {
                "1_syntax": self.syntax_ok,
                "2_danger_scan": not self.danger_flags,
                "3_dependencies": not self.missing_imports,
                "4_isolated_execution": self.executed and self.exit_code == 0,
                "5_resource_output": self.resource_ok,
            },
        }


# Layer 5 thresholds. Output this large or a run this close to the
# timeout is treated as suspicious rather than clean -- both are common
# signatures of a runaway loop rather than a program that finished.
MAX_CLEAN_OUTPUT_CHARS = 6_000
SLOW_FRACTION_OF_TIMEOUT = 0.9


def _resource_layer(report: "QAReport", timeout_seconds: float) -> None:
    """Layer 5. Mutates report in place; called after execution.

    Both the execution paths that feed this (this module's own run_qa,
    and codebox.py's run_python) truncate `output` to their own hard
    cap BEFORE this runs -- so comparing raw length against a large
    threshold would never fire; genuinely runaway output is
    indistinguishable from output that was merely long once both are
    cut to the same cap. The truncation MARKER itself is the reliable
    signal: it only appears when the real output exceeded the cap,
    which is exactly the "looks like a print loop" case this layer
    exists to catch.
    """
    flags: List[str] = []
    if "truncated" in report.output.lower() or len(report.output) >= MAX_CLEAN_OUTPUT_CHARS:
        flags.append(f"output truncated/{len(report.output)} chars -- runaway print loop jaisa lagta hai")
    if timeout_seconds > 0 and report.duration_ms >= timeout_seconds * 1000 * SLOW_FRACTION_OF_TIMEOUT:
        flags.append(f"{report.duration_ms:.0f}ms liya, timeout ke bahut kareeb -- shayad time khatam hone se ruka")
    report.resource_flags = flags
    report.resource_ok = not flags


def run_qa(code: str, run_it: bool = True) -> QAReport:
    """Layered validation, cheapest and most decisive first."""
    report = QAReport()

    # Layer 1 -- syntax. Nothing else is meaningful if this fails.
    try:
        ast.parse(code)
        report.syntax_ok = True
    except SyntaxError as exc:
        report.syntax_error = str(exc)
        return report

    # Layer 2 -- danger scan. Does NOT block here; it decides whether a
    # human must approve. Blocking outright would make JARVIS unable to
    # even propose legitimate file-handling features.
    report.danger_flags = scan_for_danger(code)

    # Layer 3 -- dependency check. REPORTS missing packages; deliberately
    # does not install them (see module docstring).
    try:
        tree = ast.parse(code)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        stdlib_ish = {"os", "sys", "re", "json", "time", "math", "random", "datetime",
                      "pathlib", "typing", "dataclasses", "collections", "itertools",
                      "sqlite3", "subprocess", "uuid", "hashlib", "textwrap"}
        for name in sorted(imports - stdlib_ish):
            try:
                __import__(name)
            except Exception:
                report.missing_imports.append(name)
    except Exception:
        pass

    if not run_it or report.missing_imports:
        return report

    # Layer 4 -- isolated execution in the sandbox directory.
    started = time.time()
    try:
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        temp = DRAFTS_DIR / f"_qa_{uuid.uuid4().hex[:8]}.py"
        temp.write_text(code, encoding="utf-8")
        proc = subprocess.run(
            # Absolute path: cwd is DRAFTS_DIR, so passing the relative
            # 'data/evolution/drafts/...' made python3 look for it
            # inside the drafts dir and fail with "can't open file" --
            # every single QA run came back failed for the wrong reason.
            [sys.executable, str(temp.resolve())], capture_output=True, text=True,
            timeout=EXECUTION_TIMEOUT, cwd=str(DRAFTS_DIR.resolve()),
        )
        report.executed = True
        report.exit_code = proc.returncode
        report.output = ((proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")).strip()[:4000]
        temp.unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        report.executed = True
        report.exit_code = -1
        report.output = f"Timeout after {EXECUTION_TIMEOUT}s -- possible infinite loop."
    except Exception as exc:
        report.output = f"Execution failed: {exc}"
    report.duration_ms = (time.time() - started) * 1000
    if report.executed:
        _resource_layer(report, EXECUTION_TIMEOUT)
    return report


def propose_feature(feature_name: str, code: str, rationale: str,
                    confidence: float = 0.0) -> Dict[str, Any]:
    """JARVIS proposes a new feature it wrote for itself.

    Never adopts anything into the live tree. The most it can do on its
    own is leave a validated draft in its sandbox with a full audit
    record -- adoption stays a human action, by design.
    """
    EVOLUTION_ROOT.mkdir(parents=True, exist_ok=True)
    for d in (DRAFTS_DIR, APPROVED_DIR, REJECTED_DIR):
        d.mkdir(parents=True, exist_ok=True)

    entry_id = uuid.uuid4().hex[:12]
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", feature_name.lower()).strip("_") or "feature"
    draft_path = DRAFTS_DIR / f"{safe_name}_{entry_id}.py"

    # Structural guarantee: the draft path itself must be inside the
    # sandbox. This is checked even though we constructed the path
    # ourselves, because feature_name is model-supplied.
    if is_protected(str(draft_path)) or DRAFTS_DIR.resolve() not in draft_path.resolve().parents:
        result = {"id": entry_id, "feature_name": feature_name, "status": "refused",
                  "reason": "Draft path sandbox ke bahar ja raha tha -- refuse kiya."}
        _record({**result, "created_at": time.time(), "confidence": confidence, "rationale": rationale})
        return result

    report = run_qa(code)
    danger = report.danger_flags
    needs_approval = bool(danger) or not report.passed

    if report.passed and not danger and confidence >= AUTO_PROPOSE_CONFIDENCE:
        status = "validated_awaiting_adoption"
        note = (f"QA pass ho gaya aur confidence {confidence:.2f} threshold se upar hai. "
                f"Draft sandbox mein ready hai -- live tree mein daalna aapka call hai.")
    elif not report.passed:
        status = "qa_failed"
        note = "QA fail hua -- draft rakha hai taaki dekha ja sake, par adopt karne layak nahi."
    else:
        status = "awaiting_human_approval"
        note = (f"QA pass hua par ismein yeh hai: {', '.join(danger)}. "
                "Iska asar sandbox ke bahar ja sakta hai, isliye aapki approval chahiye.")

    draft_path.write_text(code, encoding="utf-8")

    entry = {
        "id": entry_id, "created_at": time.time(), "feature_name": feature_name,
        "rationale": rationale, "confidence": confidence, "status": status,
        "qa_report": report.as_dict(), "needs_approval": needs_approval,
        "approval_reasons": danger, "draft_path": str(draft_path),
    }
    _record(entry)
    log_event("evolution",
              f"self-authored feature '{feature_name}': {status} (confidence={confidence:.2f}, danger={danger})",
              level="info")
    return {**entry, "note": note}


def list_proposals(status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        with _init_audit() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM evolution_log WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evolution_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("qa_report", "approval_reasons"):
                try:
                    d[key] = json.loads(d.get(key) or "null")
                except Exception:
                    pass
            out.append(d)
        return out
    except Exception:
        return []


def decide_proposal(proposal_id: str, approve: bool, decided_by: str = "UK") -> Dict[str, Any]:
    """Human decision. Approving moves the draft to approved/ -- it still
    does NOT install it into the live tree; that remains a deliberate
    file operation a person performs, so no single mistaken click can
    change running behaviour."""
    proposals = [p for p in list_proposals(limit=500) if p["id"] == proposal_id]
    if not proposals:
        return {"error": f"No proposal with id {proposal_id}"}
    p = proposals[0]
    src = Path(p.get("draft_path") or "")
    dest_dir = APPROVED_DIR if approve else REJECTED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = None
    try:
        if src.exists():
            moved = dest_dir / src.name
            moved.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            src.unlink(missing_ok=True)
    except Exception as exc:
        log_event("evolution", f"could not move proposal file: {exc}", level="warning")
    new_status = "approved" if approve else "rejected"
    try:
        with _init_audit() as conn:
            conn.execute("UPDATE evolution_log SET status=?, decided_by=?, decided_at=?, draft_path=?"
                         " WHERE id=?",
                         (new_status, decided_by, time.time(), str(moved) if moved else p.get("draft_path"), proposal_id))
            conn.commit()
    except Exception:
        pass
    return {
        "id": proposal_id, "status": new_status, "path": str(moved) if moved else None,
        "note": ("Approve ho gaya -- file approved/ mein hai. Live tree mein daalna abhi bhi "
                 "manual step hai, jaan-boojh kar." if approve else "Reject ho gaya."),
    }


def evolution_status() -> Dict[str, Any]:
    """For monitor.py / CLI / UI -- so self-evolution is never invisible."""
    all_props = list_proposals(limit=500)
    by_status: Dict[str, int] = {}
    for p in all_props:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    awaiting = [p for p in all_props if p["status"] == "awaiting_human_approval"]
    return {
        "sandbox_dir": str(EVOLUTION_ROOT),
        "total_proposals": len(all_props),
        "by_status": by_status,
        "awaiting_your_approval": len(awaiting),
        "protected_from_self_edit": list(PROTECTED_PATHS),
        "auto_propose_threshold": AUTO_PROPOSE_CONFIDENCE,
        "latest": all_props[0] if all_props else None,
    }
