from __future__ import annotations

"""JARVIS'S OWN VERSION CONTROL -- a branch it manages, and a running
picture of its own codebase.

UK's ask (2026-09-13): "JARVIS ke paas git hash jaisa feature bhi ho jo
report kare hamesha owner ya co-owner ko, aur JARVIS ko khud ki project
directory ka workflow/architecture bana rahe, uske codes bhi track hote
rahen taaki git ki tarah sync kiya ja sake... ek uk2023 branch honi
chahiye jo JARVIS khud manage kare aur commit kare."

Two design decisions worth stating plainly:

1. REAL GIT, NOT A HOMEMADE IMITATION. It would be easy to hash files
   into a SQLite table and call it version control. That would give
   JARVIS a history nobody else's tools can read -- no diff, no
   bisect, no merge, no recovery if the table corrupts. Using actual
   git means UK can inspect, revert and merge JARVIS's work with the
   same commands he already knows, from any machine. Where git is
   genuinely unavailable, a content-hash fallback records the same
   facts honestly rather than pretending a commit happened.

2. JARVIS COMMITS ONLY ON ITS OWN BRANCH. Everything it does goes to
   JARVIS_BRANCH ("uk2023"). It never commits to main/master, never
   force-pushes, never rewrites history, and never merges its own work
   -- merging is UK's decision, and a system that can merge into main
   unsupervised can change what runs without anyone agreeing to it.
   That is the same reasoning as the protected-paths rule in
   self_evolution.py, applied to history instead of files.
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

JARVIS_BRANCH = "uk2023"
REPO_ROOT = Path(".")
ARCHITECTURE_FILE = Path("data/evolution/ARCHITECTURE.md")
STATE_FILE = Path("data/evolution/version_state.json")

# Directories that describe the running organism. Used for the
# architecture map and for change detection.
TRACKED_DIRS = ("core", "backend", "web_frontend/src", "config")
PROTECTED_BRANCHES = {"main", "master", "production"}


def _git(*args: str, timeout: int = 30) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT.resolve()),
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": proc.returncode == 0, "out": (proc.stdout or "").strip(),
                "err": (proc.stderr or "").strip(), "code": proc.returncode}
    except FileNotFoundError:
        return {"ok": False, "out": "", "err": "git is not installed", "code": -1}
    except Exception as exc:
        return {"ok": False, "out": "", "err": str(exc), "code": -1}


def git_available() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").get("ok", False)


def _content_hash(paths: List[Path]) -> str:
    """Fallback identity when git is unavailable: a stable hash over the
    tracked files' contents. Honest about being a hash, not a commit."""
    h = hashlib.sha256()
    for p in sorted(paths):
        try:
            h.update(str(p).encode())
            h.update(p.read_bytes())
        except Exception:
            continue
    return h.hexdigest()[:12]


def _tracked_files() -> List[Path]:
    files: List[Path] = []
    for d in TRACKED_DIRS:
        root = REPO_ROOT / d
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in str(p))
            files.extend(p for p in root.rglob("*.ts*") if "node_modules" not in str(p))
            files.extend(root.rglob("*.json"))
    return files


def ensure_branch() -> Dict[str, Any]:
    """Make sure JARVIS's own branch exists and is checked out.

    Refuses to operate if the current branch is a protected one and
    switching would be needed unexpectedly -- surfacing that rather
    than silently moving UK off his working branch.
    """
    if not git_available():
        return {"ok": False, "reason": "git repo nahi mila -- hash-only tracking chalega."}

    current = _git("rev-parse", "--abbrev-ref", "HEAD").get("out", "")
    if current == JARVIS_BRANCH:
        return {"ok": True, "branch": JARVIS_BRANCH, "created": False}

    exists = _git("rev-parse", "--verify", JARVIS_BRANCH).get("ok", False)
    if exists:
        res = _git("checkout", JARVIS_BRANCH)
    else:
        res = _git("checkout", "-b", JARVIS_BRANCH)
    if not res["ok"]:
        return {"ok": False, "reason": res["err"], "was_on": current}
    log_event("versioning", f"switched to JARVIS branch {JARVIS_BRANCH} (from {current})", level="info")
    return {"ok": True, "branch": JARVIS_BRANCH, "created": not exists, "was_on": current}


def commit_own_work(message: str, paths: Optional[List[str]] = None,
                    author: str = "JARVIS") -> Dict[str, Any]:
    """Commit JARVIS's own changes to its branch.

    Guards, in order of importance:
      * never commits while on a protected branch;
      * only stages paths explicitly given (default: its own sandbox
        and evolution output), so it cannot sweep up UK's work in
        progress with `git add -A`;
      * never pushes, never merges, never rewrites history.
    """
    if not git_available():
        return {"ok": False, "mode": "hash_only",
                "hash": _content_hash(_tracked_files()),
                "note": "git available nahi hai -- sirf content hash record hua, commit nahi."}

    current = _git("rev-parse", "--abbrev-ref", "HEAD").get("out", "")
    if current in PROTECTED_BRANCHES:
        branch_result = ensure_branch()
        if not branch_result.get("ok"):
            return {"ok": False, "refused": True,
                    "note": f"'{current}' protected branch hai aur {JARVIS_BRANCH} pe switch nahi ho paya. Kuch commit nahi kiya."}

    stage = paths or ["data/evolution", "data/sandboxes"]
    staged_any = False
    for p in stage:
        if Path(p).exists():
            if _git("add", p)["ok"]:
                staged_any = True

    if not staged_any:
        return {"ok": False, "note": "Stage karne ko kuch mila hi nahi."}

    status = _git("diff", "--cached", "--name-only")
    if not status.get("out"):
        return {"ok": True, "changed": False, "note": "Koi change nahi tha -- commit ki zaroorat hi nahi padi."}

    full_message = f"[JARVIS] {message}\n\nAuthored-by: {author}\nBranch: {JARVIS_BRANCH}"
    res = _git("commit", "-m", full_message)
    if not res["ok"]:
        return {"ok": False, "note": res["err"]}

    sha = _git("rev-parse", "--short", "HEAD").get("out", "")
    files = [f for f in status["out"].splitlines() if f.strip()]
    log_event("versioning", f"JARVIS committed {len(files)} file(s) as {sha} on {JARVIS_BRANCH}", level="info")
    return {"ok": True, "changed": True, "sha": sha, "branch": JARVIS_BRANCH,
            "files": files, "message": message,
            "note": f"{len(files)} file(s) commit ho gayi {JARVIS_BRANCH} pe ({sha}). Merge karna aapka call hai."}


def build_architecture_map() -> Dict[str, Any]:
    """JARVIS's running picture of its own codebase: modules, sizes, and
    what each package is for. Regenerated rather than hand-maintained,
    so it cannot drift out of date the way a written doc does."""
    modules: Dict[str, List[Dict[str, Any]]] = {}
    total_lines = 0
    for path in sorted(_tracked_files()):
        if path.suffix != ".py":
            continue
        package = str(path.parent)
        try:
            lines = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            lines = 0
        total_lines += lines
        modules.setdefault(package, []).append({"file": path.name, "lines": lines})

    summary = {
        "generated_at": time.time(),
        "total_python_files": sum(len(v) for v in modules.values()),
        "total_lines": total_lines,
        "packages": {k: {"files": len(v), "lines": sum(f["lines"] for f in v)} for k, v in sorted(modules.items())},
    }

    try:
        ARCHITECTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines_out = [
            "# JARVIS -- self-generated architecture map",
            f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by JARVIS itself._",
            "",
            f"- Python files tracked: **{summary['total_python_files']}**",
            f"- Total lines: **{summary['total_lines']}**",
            f"- JARVIS's own branch: `{JARVIS_BRANCH}`",
            "",
            "## Packages",
            "",
            "| Package | Files | Lines |",
            "| --- | ---: | ---: |",
        ]
        for pkg, info in summary["packages"].items():
            lines_out.append(f"| `{pkg}` | {info['files']} | {info['lines']} |")
        ARCHITECTURE_FILE.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        summary["written_to"] = str(ARCHITECTURE_FILE)
    except Exception as exc:
        summary["write_error"] = str(exc)

    return summary


def version_report() -> Dict[str, Any]:
    """The report for UK -- what JARVIS's codebase looks like right now,
    what changed since it last looked, and where its own work sits.
    Owner/co-owner only; the caller enforces that."""
    files = _tracked_files()
    current_hash = _content_hash(files)

    previous: Dict[str, Any] = {}
    try:
        if STATE_FILE.exists():
            previous = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        previous = {}

    changed = previous.get("hash") != current_hash

    report: Dict[str, Any] = {
        "tracked_files": len(files),
        "content_hash": current_hash,
        "changed_since_last_check": changed,
        "previous_hash": previous.get("hash"),
        "last_checked": previous.get("checked_at"),
        "git_available": git_available(),
        "jarvis_branch": JARVIS_BRANCH,
    }

    if report["git_available"]:
        report["current_branch"] = _git("rev-parse", "--abbrev-ref", "HEAD").get("out", "")
        report["head_sha"] = _git("rev-parse", "--short", "HEAD").get("out", "")
        dirty = _git("status", "--porcelain").get("out", "")
        report["uncommitted_files"] = len([l for l in dirty.splitlines() if l.strip()])
        log = _git("log", "--oneline", "-5", JARVIS_BRANCH)
        report["recent_jarvis_commits"] = log.get("out", "").splitlines() if log.get("ok") else []
    else:
        report["note"] = "git install nahi hai -- sirf content-hash tracking chal rahi hai, real commits nahi."

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"hash": current_hash, "checked_at": time.time()}), encoding="utf-8")
    except Exception:
        pass

    return report
