"""PROJECT DIRECTORY AWARENESS (Priority 2, roadmap.md).

UK requirement: "JARVIS should know it has access to all files/folders
in that project directory so it can plan, edit and fix in steps the
way Claude does -- including outside this chat, on its own."

This gives JARVIS a real, evidence-based picture of ONE active project
directory at a time: what's actually in it, not an assumed or invented
layout. Ties into ConversationState.active_project (already built in
the Conversation Intelligence Layer) -- when the user says "uss tool
mein X change karo", JARVIS resolves which project/directory is active
from conversational state, THEN looks at this module's real file
listing, rather than asking unnecessary technical questions or
guessing a path.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProjectFile:
    """One file JARVIS knows about within the active project."""
    relative_path: str
    absolute_path: str
    size_bytes: int
    modified_at: float
    is_directory: bool = False


@dataclass
class ProjectContext:
    """The active project directory JARVIS is working in.

    Only ONE project is "active" at a time (per UK's spec: sandbox
    scoped to one specific project directory). Switching projects is
    explicit, never inferred from a single ambiguous mention.
    """
    name: str
    root_directory: str
    activated_at: float = field(default_factory=time.time)
    last_scanned_at: Optional[float] = None
    files: Dict[str, ProjectFile] = field(default_factory=dict)  # relative_path -> ProjectFile
    known_tools: List[str] = field(default_factory=list)  # tool names from ToolCapabilityRegistry associated with this project

    def scan(self, max_files: int = 500, ignore_dirs: Optional[List[str]] = None) -> int:
        """Actually walk the directory and record what's really there.

        Never invents file existence -- this is the evidence JARVIS's
        "I have access to this project" claims are grounded in. Returns
        the number of files found.
        """
        ignore_dirs = set(ignore_dirs or [".git", "__pycache__", "node_modules", ".venv", "venv", ".jarvis_backups"])

        if not os.path.isdir(self.root_directory):
            raise ValueError(f"Project root does not exist: {self.root_directory}")

        self.files = {}
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root_directory):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            for fname in filenames:
                if count >= max_files:
                    break
                abs_path = os.path.join(dirpath, fname)
                try:
                    stat = os.stat(abs_path)
                except OSError:
                    continue
                rel_path = os.path.relpath(abs_path, self.root_directory)
                self.files[rel_path] = ProjectFile(
                    relative_path=rel_path,
                    absolute_path=abs_path,
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                )
                count += 1
            if count >= max_files:
                break

        self.last_scanned_at = time.time()
        return count

    def resolve_file(self, mentioned_name: str) -> Optional[ProjectFile]:
        """Resolve a user's mention of a file to a real, known file.

        Exact match first, then a substring/basename match -- e.g. the
        user says "alarm script" and the real file is
        "tools/alarm.py". NEVER returns a fabricated path; only
        matches against self.files, which scan() populated from real
        os.walk() evidence.
        """
        mentioned_lower = mentioned_name.lower()

        # Exact relative path
        if mentioned_name in self.files:
            return self.files[mentioned_name]

        # Basename match
        for rel_path, pf in self.files.items():
            if os.path.basename(rel_path).lower() == mentioned_lower:
                return pf

        # Substring match on basename (without extension too)
        for rel_path, pf in self.files.items():
            base = os.path.basename(rel_path).lower()
            base_no_ext = os.path.splitext(base)[0]
            if mentioned_lower in base or mentioned_lower in base_no_ext:
                return pf

        return None

    def list_files_summary(self, max_shown: int = 30) -> str:
        """Human-readable summary of what's actually in the project --
        for JARVIS to ground a "here's what I can see" response in."""
        if not self.files:
            return f"'{self.name}' scanned but appears empty, or not scanned yet."
        lines = [f"{f.relative_path}" for f in list(self.files.values())[:max_shown]]
        more = len(self.files) - max_shown
        summary = "\n".join(lines)
        if more > 0:
            summary += f"\n... and {more} more files"
        return summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "root_directory": self.root_directory,
            "file_count": len(self.files),
            "last_scanned_at": self.last_scanned_at,
            "known_tools": self.known_tools,
        }


class ProjectContextManager:
    """Manages the ONE active project at a time, plus known past projects."""

    def __init__(self):
        self.active: Optional[ProjectContext] = None
        self.known_projects: Dict[str, ProjectContext] = {}

    def activate_project(self, name: str, root_directory: str, scan_now: bool = True) -> ProjectContext:
        """Switch JARVIS's active project. Explicit action, never inferred."""
        if name.lower() in self.known_projects:
            project = self.known_projects[name.lower()]
        else:
            project = ProjectContext(name=name, root_directory=root_directory)
            self.known_projects[name.lower()] = project

        if scan_now:
            project.scan()

        self.active = project
        return project

    def get_active(self) -> Optional[ProjectContext]:
        return self.active

    def has_active_project(self) -> bool:
        return self.active is not None
