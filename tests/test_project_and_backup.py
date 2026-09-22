"""Tests for Priority 2 (roadmap.md): Project Directory Awareness +
Backup-Then-Modify workflow.

These use a REAL temp directory and REAL filesystem operations
throughout -- no mocking -- because the whole point of both modules is
that they ground JARVIS's claims in actual, verifiable disk state.
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.project_context import ProjectContext, ProjectContextManager
from core.cognition.backup_tracker import BackupThenModifyTracker


def _make_temp_project():
    root = tempfile.mkdtemp(prefix="jarvis_test_project_")
    os.makedirs(os.path.join(root, "tools"))
    with open(os.path.join(root, "main.py"), "w") as f:
        f.write("# main entry point\n")
    with open(os.path.join(root, "tools", "alarm.py"), "w") as f:
        f.write("# alarm tool\ndef ring(): pass\n")
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("# Test Project\n")
    return root


def test_project_scan_reflects_real_filesystem():
    """scan() must find exactly what's really on disk, nothing invented."""
    root = _make_temp_project()
    try:
        project = ProjectContext(name="test_project", root_directory=root)
        count = project.scan()
        assert count == 3, f"expected 3 files, found {count}"
        assert "main.py" in project.files
        assert os.path.join("tools", "alarm.py") in project.files
        assert "README.md" in project.files
    finally:
        shutil.rmtree(root)


def test_project_scan_raises_on_nonexistent_directory():
    """Never silently 'scan' a directory that doesn't exist."""
    project = ProjectContext(name="ghost", root_directory="/this/does/not/exist/at/all")
    try:
        project.scan()
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "does not exist" in str(e)


def test_resolve_file_by_partial_mention():
    """UK requirement (section 15): 'उस tool में X change करो' -- JARVIS
    must resolve which real file the user means, from actual scan evidence."""
    root = _make_temp_project()
    try:
        project = ProjectContext(name="test_project", root_directory=root)
        project.scan()

        # User says "alarm script" or just "alarm"
        found = project.resolve_file("alarm")
        assert found is not None
        assert found.relative_path == os.path.join("tools", "alarm.py")

        # Exact basename match
        found2 = project.resolve_file("main.py")
        assert found2 is not None
        assert found2.relative_path == "main.py"

        # Non-existent file resolves to None, never fabricated
        found3 = project.resolve_file("totally_fake_file_xyz")
        assert found3 is None
    finally:
        shutil.rmtree(root)


def test_project_context_manager_activates_one_project_at_a_time():
    root1 = _make_temp_project()
    root2 = _make_temp_project()
    try:
        manager = ProjectContextManager()
        manager.activate_project("proj1", root1)
        assert manager.get_active().name == "proj1"

        manager.activate_project("proj2", root2)
        assert manager.get_active().name == "proj2"  # explicit switch, not accumulation
        assert len(manager.known_projects) == 2  # but proj1 is still remembered
    finally:
        shutil.rmtree(root1)
        shutil.rmtree(root2)


def test_backup_before_modify_creates_real_snapshot():
    """The core guarantee: before a file changes, a real copy of its
    PRIOR content exists on disk."""
    root = _make_temp_project()
    try:
        tracker = BackupThenModifyTracker(root)
        original_content = open(os.path.join(root, "main.py")).read()

        record = tracker.record_before_change(
            "main.py",
            reason="Adding CLI argument parsing per user request",
            turn_number=5,
        )

        assert record.backup_path != ""
        assert os.path.exists(record.backup_path)
        backup_content = open(record.backup_path).read()
        assert backup_content == original_content
    finally:
        shutil.rmtree(root)


def test_backup_journal_persists_across_tracker_instances():
    """UK requirement: trackable across restarts, not just this run --
    a NEW tracker instance for the same project must see prior history."""
    root = _make_temp_project()
    try:
        tracker1 = BackupThenModifyTracker(root)
        tracker1.record_before_change("main.py", reason="first change", turn_number=1)
        tracker1.record_before_change("README.md", reason="second change", turn_number=2)

        # Simulate a restart: brand new tracker instance, same project root
        tracker2 = BackupThenModifyTracker(root)
        history = tracker2.get_recent_history()
        assert len(history) == 2
        # Most recent first
        assert history[0].reason == "second change"
        assert history[1].reason == "first change"
    finally:
        shutil.rmtree(root)


def test_restore_from_backup_works():
    root = _make_temp_project()
    try:
        tracker = BackupThenModifyTracker(root)
        original = open(os.path.join(root, "main.py")).read()

        record = tracker.record_before_change("main.py", reason="test change", turn_number=1)

        # Simulate the actual edit happening
        with open(os.path.join(root, "main.py"), "w") as f:
            f.write("# COMPLETELY DIFFERENT CONTENT\n")

        # Now restore
        success = tracker.restore_from_backup(record)
        assert success
        restored = open(os.path.join(root, "main.py")).read()
        assert restored == original
    finally:
        shutil.rmtree(root)


def test_summarize_progress_grounded_in_real_journal():
    """UK requirement (section 10): never claim an audit was done that
    wasn't -- summarize_progress() must reflect ONLY real recorded changes."""
    root = _make_temp_project()
    try:
        tracker = BackupThenModifyTracker(root)

        # No changes yet
        summary_empty = tracker.summarize_progress()
        assert "No tracked changes" in summary_empty

        tracker.record_before_change("main.py", reason="added argparse", turn_number=3)
        summary = tracker.summarize_progress()
        assert "main.py" in summary
        assert "added argparse" in summary
    finally:
        shutil.rmtree(root)


def test_create_change_type_takes_no_backup():
    """A brand-new file has nothing to back up -- change_type='create'
    should not try to snapshot content that doesn't exist yet."""
    root = _make_temp_project()
    try:
        tracker = BackupThenModifyTracker(root)
        record = tracker.record_before_change(
            "tools/new_tool.py", reason="creating a new tool", change_type="create",
        )
        assert record.backup_path == ""
        assert record.had_prior_content is False
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    test_project_scan_reflects_real_filesystem()
    test_project_scan_raises_on_nonexistent_directory()
    test_resolve_file_by_partial_mention()
    test_project_context_manager_activates_one_project_at_a_time()
    test_backup_before_modify_creates_real_snapshot()
    test_backup_journal_persists_across_tracker_instances()
    test_restore_from_backup_works()
    test_summarize_progress_grounded_in_real_journal()
    test_create_change_type_takes_no_backup()
    print("✓ ALL PROJECT CONTEXT + BACKUP TRACKER TESTS PASSED")
