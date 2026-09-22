from __future__ import annotations

"""CODING AGENT -- repo-aware tools (Phase 5).

codebox.py already gives JARVIS a sandbox that writes ONE script,
runs it, and iterates on the traceback (run_coding_session). That is
correct and stays exactly as-is for "likho ek script jo X kare"
turns -- it is not being replaced.

What is missing, and what this module adds, is REPO-SCALE work: an
existing multi-file project that needs inspecting, editing in
several places, tested, debugged and packaged -- "fix this project",
"add a feature across multiple files". RepoWorkspace is the same
damage-limitation posture as CodeBox (a bounded root directory, a
command timeout, a refused-pattern list, truncated output, every
step recorded) applied to a real project tree instead of a
throwaway single-script sandbox.

Every function at the bottom (build_registry) returns ToolSpec
instances bound to one RepoWorkspace -- this is the Coding Agent's
concrete tool belt for THIS run.
"""

import difflib
import fnmatch
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ...runtime.log import log_event
except Exception:  # pragma: no cover -- see BLUEPRINT.md, Phase 1 finding #1
    def log_event(channel: str, message: str, level: str = "info") -> None:
        pass

from .tool_contract import ToolRegistry, ToolSpec, RISK_READ_ONLY, RISK_LOW, RISK_MEDIUM, RISK_HIGH

# Reuse the SAME irreversible-command refusal list codebox.py already
# maintains, rather than a second copy that could drift out of sync.
try:
    from ..codebox import _refused as _refused_command
except Exception:  # pragma: no cover
    _REFUSED_PATTERNS = (r"\brm\s+-rf\s+/", r"\bmkfs\b", r"\bdd\s+if=", r"\bshutdown\b",
                          r"\breboot\b", r":\(\)\{.*\};:", r"\bchmod\s+-R\s+777\s+/",
                          r">\s*/dev/sd", r"\bpkill\s+-9\b", r"\bkillall\b")

    def _refused_command(command: str) -> Optional[str]:
        for pattern in _REFUSED_PATTERNS:
            if re.search(pattern, command, re.I):
                return f"Command refused (irreversible/system-level): pattern `{pattern}`"
        return None

DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 8000
MAX_FILES_LISTED = 500

# Never included in a directory listing, a search, or a packaged
# artifact by default -- matches sandbox posture + the packaging
# secret-exclusion requirement in one place, so both tools agree.
DEFAULT_IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                        "dist", "build", ".pytest_cache", ".mypy_cache"}
SECRET_FILE_GLOBS = ("*.env", ".env*", "*secret*", "*credential*", "*.pem",
                      "*.pfx", "id_rsa*", "*.key", "*apikey*", "*api_key*")


def _is_secret_path(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILE_GLOBS)


class WorkspaceError(Exception):
    pass


class RepoWorkspace:
    """One bounded project root. Every path-taking method resolves the
    path and refuses anything that would escape `root` -- the same
    containment codebox.CodeBox.write_file already does, applied here
    to reads, writes, patches AND the search tool.
    """

    def __init__(self, root: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = max(1, min(int(timeout), 300))

    def _resolve(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise WorkspaceError(f"'{rel_path}' would escape the authorized project root")
        return target

    # ------------------------------------------------------- discovery
    def list_tree(self, sub_path: str = ".", max_files: int = MAX_FILES_LISTED) -> Dict[str, Any]:
        base = self._resolve(sub_path)
        if not base.exists():
            return {"ok": False, "error": f"'{sub_path}' does not exist"}
        files: List[str] = []
        for p in sorted(base.rglob("*")):
            if any(part in DEFAULT_IGNORE_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                rel = str(p.relative_to(self.root))
                files.append(rel + ("  [secret-excluded]" if _is_secret_path(rel) else ""))
                if len(files) >= max_files:
                    files.append(f"... truncated at {max_files} files")
                    break
        return {"ok": True, "root": str(self.root), "files": files, "count": len(files)}

    def search_code(self, pattern: str, sub_path: str = ".", max_matches: int = 200) -> Dict[str, Any]:
        base = self._resolve(sub_path)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return {"ok": False, "error": f"bad regex: {exc}"}
        matches: List[str] = []
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = str(p.relative_to(self.root))
            if any(part in DEFAULT_IGNORE_DIRS for part in p.relative_to(self.root).parts):
                continue
            if _is_secret_path(rel):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(matches) >= max_matches:
                        return {"ok": True, "matches": matches, "truncated": True}
        return {"ok": True, "matches": matches, "truncated": False}

    # --------------------------------------------------------- file I/O
    def read_file(self, path: str, max_chars: int = MAX_OUTPUT_CHARS) -> Dict[str, Any]:
        target = self._resolve(path)
        if _is_secret_path(path):
            return {"ok": False, "error": "refused: looks like a secrets/credentials file"}
        if not target.exists():
            return {"ok": False, "error": f"'{path}' does not exist"}
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {"ok": False, "error": f"read failed: {exc}"}
        truncated = len(content) > max_chars
        return {"ok": True, "content": content[:max_chars], "truncated": truncated,
                "size": len(content)}

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        if _is_secret_path(path):
            return {"ok": False, "error": "refused: writing to a secrets/credentials-shaped path"}
        target = self._resolve(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": f"write failed: {exc}"}
        return {"ok": True, "path": path, "bytes_written": len(content.encode("utf-8"))}

    def apply_patch(self, path: str, find: str, replace: str, *, count: int = 1) -> Dict[str, Any]:
        """A small, LLM-friendly find/replace patch -- deliberately not a
        full unified-diff applier: models are far more reliable at
        emitting "replace this exact block" than a correctly-offset
        diff, and a failed find is a clean, explainable no-op instead
        of a diff that applies to the wrong hunk."""
        current = self.read_file(path)
        if not current.get("ok"):
            return current
        text = current["content"]
        if find not in text:
            return {"ok": False, "error": "find text not present in file -- no change made",
                    "path": path}
        new_text = text.replace(find, replace, count if count > 0 else -1)
        diff = "\n".join(difflib.unified_diff(
            text.splitlines(), new_text.splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
        result = self.write_file(path, new_text)
        if not result.get("ok"):
            return result
        return {"ok": True, "path": path, "diff": diff[:MAX_OUTPUT_CHARS]}

    # -------------------------------------------------------- execution
    def run_command(self, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        refusal = _refused_command(command)
        if refusal:
            log_event("coding_agent", f"refused command: {command[:80]}", level="warning")
            return {"ok": False, "error": refusal}
        started = time.time()
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(self.root),
                capture_output=True, text=True,
                timeout=timeout or self.timeout,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "HOME": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"},
            )
            out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            if len(out) > MAX_OUTPUT_CHARS:
                out = out[:MAX_OUTPUT_CHARS] + f"\n...[truncated at {MAX_OUTPUT_CHARS} chars]"
            return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
                    "output": out.strip(), "duration_s": round(time.time() - started, 3)}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timed out after {timeout or self.timeout}s "
                                            f"-- possible infinite loop"}
        except Exception as exc:
            return {"ok": False, "error": f"execution failed: {exc}"}

    # -------------------------------------------------------------- git
    def git(self, args: str) -> Dict[str, Any]:
        """Restricted to a safe subcommand allowlist -- commit/push/reset
        etc. go through the approval gate as named ops (see approval.py's
        _ALWAYS_ASK_TOOLS), never through this generic passthrough."""
        first = (args or "").strip().split(" ", 1)[0]
        if first not in {"status", "diff", "log", "show", "branch"}:
            return {"ok": False, "error": f"git subcommand '{first}' not permitted via this tool"}
        return self.run_command(f"git {args}")

    def git_commit(self, message: str) -> Dict[str, Any]:
        if not (message or "").strip():
            return {"ok": False, "error": "commit message is required"}
        add = self.run_command("git add -A")
        if not add.get("ok"):
            return add
        return self.run_command(f"git commit -m {message!r}")

    # -------------------------------------------------------------- tests
    def run_tests(self) -> Dict[str, Any]:
        """Auto-detects the appropriate verification method rather than
        assuming pytest -- a project with no tests still gets a real
        check (py_compile on every .py file) instead of a silent pass."""
        has_pytest_cfg = any((self.root / name).exists() for name in
                              ("pytest.ini", "pyproject.toml", "setup.cfg"))
        has_tests_dir = (self.root / "tests").is_dir() or \
            any(self.root.glob("test_*.py")) or any(self.root.glob("**/test_*.py"))
        if has_tests_dir or has_pytest_cfg:
            result = self.run_command("python3 -m pytest -q", timeout=120)
            result["method"] = "pytest"
            return result
        py_files = [str(p.relative_to(self.root)) for p in self.root.rglob("*.py")
                    if not any(part in DEFAULT_IGNORE_DIRS for part in p.relative_to(self.root).parts)]
        if not py_files:
            return {"ok": True, "method": "none_available",
                    "output": "No Python files and no test suite found -- nothing to verify."}
        cmd = "python3 -m py_compile " + " ".join(f'"{f}"' for f in py_files[:200])
        result = self.run_command(cmd)
        result["method"] = "py_compile"
        return result


def build_registry(workspace: RepoWorkspace) -> ToolRegistry:
    """The Coding Agent's tool belt for one run, bound to `workspace`."""
    reg = ToolRegistry()
    reg.register(ToolSpec("list_tree", "List files in the project (or a sub-path).",
                           lambda sub_path=".": workspace.list_tree(sub_path),
                           risk=RISK_READ_ONLY, read_only=True))
    reg.register(ToolSpec("search_code", "Regex search across the project's source files.",
                           lambda pattern, sub_path=".": workspace.search_code(pattern, sub_path),
                           risk=RISK_READ_ONLY, read_only=True))
    reg.register(ToolSpec("read_file", "Read one file's contents.",
                           lambda path: workspace.read_file(path),
                           risk=RISK_READ_ONLY, read_only=True))
    reg.register(ToolSpec("write_file", "Create or overwrite one file.",
                           lambda path, content: workspace.write_file(path, content),
                           risk=RISK_LOW))
    reg.register(ToolSpec("apply_patch", "Find-and-replace a block of text in one file.",
                           lambda path, find, replace, count=1: workspace.apply_patch(path, find, replace, count=count),
                           risk=RISK_LOW))
    reg.register(ToolSpec("run_command", "Run a shell command in the project root (sandboxed, timed out).",
                           lambda command, timeout=None: workspace.run_command(command, timeout),
                           risk=RISK_MEDIUM))
    reg.register(ToolSpec("run_tests", "Run the project's test suite (auto-detected) or compile-check it.",
                           lambda: workspace.run_tests(),
                           risk=RISK_LOW))
    reg.register(ToolSpec("run_python_qa",
                           "Write+run one Python file through JARVIS's existing 5-layer QA sandbox "
                           "(syntax/danger-scan/deps/isolated-exec/resource) -- reuses codebox.py, "
                           "does not duplicate it. Use for a risky or unfamiliar snippet before it "
                           "becomes a permanent project file.",
                           lambda code, filename="scratch.py": _run_python_qa(workspace, code, filename),
                           risk=RISK_LOW))
    reg.register(ToolSpec("propose_new_tool",
                           "Propose a brand-new capability for JARVIS itself (not this project): writes "
                           "the code, runs it through JARVIS's self-evolution QA/danger-scan, and files a "
                           "governed proposal UK can approve. Reuses core/evolution/self_evolution.py -- "
                           "the SAME pipeline behind the 'propose_self_feature' chat tool. This tool "
                           "NEVER activates anything live; use it only when the objective genuinely needs "
                           "a new JARVIS capability, not for ordinary project files.",
                           lambda feature_name, code, rationale, confidence=0.5:
                               _propose_new_tool(feature_name, code, rationale, confidence),
                           risk=RISK_MEDIUM))
    reg.register(ToolSpec("git_status", "git status/diff/log/show/branch (read-only subcommands only).",
                           lambda args="status": workspace.git(args),
                           risk=RISK_READ_ONLY, read_only=True))
    reg.register(ToolSpec("git_commit", "Stage all changes and commit with the given message.",
                           lambda message: workspace.git_commit(message),
                           risk=RISK_HIGH, destructive=True))
    reg.register(ToolSpec("delete_file", "Delete one file from the project.",
                           lambda path: _delete_file(workspace, path),
                           risk=RISK_HIGH, destructive=True))
    return reg


def _delete_file(workspace: RepoWorkspace, path: str) -> Dict[str, Any]:
    if _is_secret_path(path):
        return {"ok": False, "error": "refused: secrets/credentials-shaped path"}
    target = workspace._resolve(path)
    if not target.exists():
        return {"ok": False, "error": f"'{path}' does not exist"}
    try:
        target.unlink()
        return {"ok": True, "path": path, "deleted": True}
    except Exception as exc:
        return {"ok": False, "error": f"delete failed: {exc}"}


def _run_python_qa(workspace: RepoWorkspace, code: str, filename: str) -> Dict[str, Any]:
    """Reuses codebox.CodeBox's run_python (5-layer QA) INSTEAD OF a second
    execution path -- pointed at this workspace's own root rather than a
    fresh sandbox dir, so the file ends up as a real project file, not
    lost in a throwaway session."""
    try:
        from ..codebox import CodeBox
    except Exception as exc:
        return {"ok": False, "error": f"codebox unavailable: {exc}"}
    box = CodeBox(session_id="coding_agent_qa", timeout=workspace.timeout)
    box.session.workdir = workspace.root   # reuse OUR root, not a fresh sandbox dir
    step = box.run_python(code, filename=filename)
    return {"ok": step.ok, "output": step.output, "qa": step.qa, "exit_code": step.exit_code}


def _propose_new_tool(feature_name: str, code: str, rationale: str, confidence: float) -> Dict[str, Any]:
    """Reuses core/evolution/self_evolution.propose_feature -- the exact
    function behind the existing 'propose_self_feature' chat tool. Never
    duplicated: this IS that function, called from inside a coding-agent
    run instead of from a chat turn."""
    try:
        from ..self_extension import propose_tool
    except Exception as exc:
        return {"ok": False, "error": f"self_extension unavailable: {exc}"}
    return propose_tool(feature_name, code, rationale, confidence)
