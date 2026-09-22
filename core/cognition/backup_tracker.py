"""BACKUP-THEN-MODIFY WORKFLOW (Priority 2, roadmap.md).

UK requirement: "backup-then-modify workflow set up: without git, it
should stay persistently trackable how far work has progressed and
what happened, the way Claude's own turn-by-turn work is trackable."

Before JARVIS modifies any file in a project, it snapshots the current
content first, with a log entry saying what's about to change and why.
This is NOT a git replacement -- it's a linear, append-only journal
per project, stored as plain files under the project's own
.jarvis_backups/ directory, so:
  - it survives without git being installed/initialized
  - a person can browse it directly (it's just timestamped copies + a
    JSON log), the same way they'd browse `git log` output
  - JARVIS can answer "what did you change and when" from real
    evidence, not from memory of having said it did something
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChangeRecord:
    """One recorded change to one file."""
    file_relative_path: str
    backup_path: str  # where the pre-change snapshot was saved
    reason: str  # why this change was made (evidence, not invented)
    changed_at: float
    turn_number: Optional[int] = None
    change_type: str = "modify"  # "modify", "create", "delete"
    had_prior_content: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_relative_path,
            "backup": self.backup_path,
            "reason": self.reason,
            "changed_at": self.changed_at,
            "turn_number": self.turn_number,
            "change_type": self.change_type,
        }


class BackupThenModifyTracker:
    """Tracks change history for ONE project directory.

    Every modification to a tracked file goes through:
      1. record_before_change() -- snapshot the CURRENT file content
         into .jarvis_backups/<timestamp>_<filename>, log WHY the
         change is about to happen
      2. (the actual edit happens -- this tracker does not perform
         edits itself, it wraps around whatever does)
      3. The journal (.jarvis_backups/journal.json) is appended to,
         never overwritten -- a persistent, human-readable history.
    """

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.backup_dir = os.path.join(project_root, ".jarvis_backups")
        self.journal_path = os.path.join(self.backup_dir, "journal.json")
        self._history: List[ChangeRecord] = []
        self._load_journal()

    def _load_journal(self) -> None:
        """Load existing journal if this project already has one --
        history must survive across sessions/restarts, not just this run."""
        if os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data.get("changes", []):
                    self._history.append(ChangeRecord(
                        file_relative_path=entry["file"],
                        backup_path=entry["backup"],
                        reason=entry["reason"],
                        changed_at=entry["changed_at"],
                        turn_number=entry.get("turn_number"),
                        change_type=entry.get("change_type", "modify"),
                    ))
            except (json.JSONDecodeError, KeyError, OSError):
                # Corrupt or unreadable journal -- start fresh rather than
                # crash, but never silently claim history that isn't there.
                self._history = []

    def _save_journal(self) -> None:
        os.makedirs(self.backup_dir, exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump({"changes": [r.to_dict() for r in self._history]}, f, ensure_ascii=False, indent=2)

    def record_before_change(
        self,
        file_relative_path: str,
        reason: str,
        turn_number: Optional[int] = None,
        change_type: str = "modify",
    ) -> ChangeRecord:
        """Snapshot the file BEFORE it's modified, and log why.

        Call this BEFORE performing an edit. If the file doesn't exist
        yet (change_type="create"), no snapshot is taken -- there's
        nothing to back up -- but the intent is still logged.
        """
        os.makedirs(self.backup_dir, exist_ok=True)
        abs_path = os.path.join(self.project_root, file_relative_path)

        backup_path = ""
        had_prior_content = os.path.exists(abs_path)
        if had_prior_content and change_type != "create":
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_name = file_relative_path.replace(os.sep, "__").replace("/", "__")
            backup_filename = f"{timestamp}_{safe_name}"
            backup_path = os.path.join(self.backup_dir, backup_filename)
            shutil.copy2(abs_path, backup_path)

        record = ChangeRecord(
            file_relative_path=file_relative_path,
            backup_path=backup_path,
            reason=reason,
            changed_at=time.time(),
            turn_number=turn_number,
            change_type=change_type,
            had_prior_content=had_prior_content,
        )
        self._history.append(record)
        self._save_journal()
        return record

    def get_history_for_file(self, file_relative_path: str) -> List[ChangeRecord]:
        """All recorded changes to one file, oldest first."""
        return [r for r in self._history if r.file_relative_path == file_relative_path]

    def get_recent_history(self, limit: int = 10) -> List[ChangeRecord]:
        """Most recent changes across the whole project."""
        return list(reversed(self._history[-limit:]))

    def restore_from_backup(self, record: ChangeRecord) -> bool:
        """Restore a file to its state before a specific recorded change.

        Only works if that change actually recorded a backup (i.e. the
        file existed before that change) -- never fabricates a restore.
        """
        if not record.backup_path or not os.path.exists(record.backup_path):
            return False
        abs_path = os.path.join(self.project_root, record.file_relative_path)
        shutil.copy2(record.backup_path, abs_path)
        return True

    def summarize_progress(self) -> str:
        """Human-readable summary of what's been done so far --
        grounded in the actual journal, for JARVIS to answer 'what
        have we done on this project' without inventing an audit."""
        if not self._history:
            return "No tracked changes recorded yet for this project."
        lines = []
        for r in self._history[-20:]:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.changed_at))
            lines.append(f"[{ts}] {r.change_type}: {r.file_relative_path} -- {r.reason}")
        return "\n".join(lines)
