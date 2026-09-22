from __future__ import annotations

"""CODING AGENT -- artifact packaging (Phase 9).

A standalone capability, not hard-coded into agent.py's loop, so it
is usable on its own ("project ko zip kar do") and from any future
workflow, not only after a full agent run.

SECRET EXCLUSION. Before packaging, every candidate file is checked
against the same SECRET_FILE_GLOBS repo_tools.py already uses for
read/write/search, so the two tools cannot disagree about what counts
as a secret. Excluded files are listed in the result so the exclusion
is visible, not silent.
"""

import fnmatch
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ...runtime.log import log_event
except Exception:  # pragma: no cover -- see BLUEPRINT.md, Phase 1 finding #1
    def log_event(channel: str, message: str, level: str = "info") -> None:
        pass

from .repo_tools import DEFAULT_IGNORE_DIRS, SECRET_FILE_GLOBS

MAX_ARCHIVE_FILES = 5000


def _is_secret(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILE_GLOBS)


def _collect_files(root: Path, extra_exclude: Optional[List[str]] = None) -> tuple[List[Path], List[str]]:
    extra_exclude = extra_exclude or []
    included: List[Path] = []
    excluded: List[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if any(part in DEFAULT_IGNORE_DIRS for part in p.relative_to(root).parts):
            continue
        if _is_secret(rel) or any(fnmatch.fnmatch(rel, pat) for pat in extra_exclude):
            excluded.append(rel)
            continue
        included.append(p)
        if len(included) >= MAX_ARCHIVE_FILES:
            break
    return included, excluded


def package_project(repo_path: str, *, out_dir: str, archive_name: str,
                     fmt: str = "zip", extra_exclude: Optional[List[str]] = None) -> Dict[str, Any]:
    """fmt: 'zip' or 'tar.gz'. Returns {ok, artifact_path, included, excluded}."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"'{repo_path}' is not a directory"}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    files, excluded = _collect_files(root, extra_exclude)
    if not files:
        return {"ok": False, "error": "nothing to package -- no files found after exclusions"}

    started = time.time()
    try:
        if fmt == "zip":
            artifact_path = out / f"{archive_name}.zip"
            with zipfile.ZipFile(artifact_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, arcname=str(f.relative_to(root)))
        elif fmt in ("tar.gz", "targz", "tgz"):
            artifact_path = out / f"{archive_name}.tar.gz"
            with tarfile.open(artifact_path, "w:gz") as tf:
                for f in files:
                    tf.add(f, arcname=str(f.relative_to(root)))
        else:
            return {"ok": False, "error": f"unsupported format '{fmt}' -- use 'zip' or 'tar.gz'"}
    except Exception as exc:
        return {"ok": False, "error": f"packaging failed: {exc}"}

    log_event("coding_agent",
              f"packaged {len(files)} files ({len(excluded)} excluded) -> {artifact_path}",
              level="info")
    return {
        "ok": True, "artifact_path": str(artifact_path),
        "file_count": len(files), "excluded": excluded,
        "duration_s": round(time.time() - started, 3),
        "size_bytes": artifact_path.stat().st_size,
    }
