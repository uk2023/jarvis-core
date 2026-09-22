"""Regression checks for the single authoritative semantic path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAIN = ROOT / "core" / "orchestration" / "brain.py"
BOUNDARY = ROOT / "core" / "cognition" / "semantic_understanding" / "learning_boundary.py"


def test_brain_has_no_runtime_legacy_fact_extraction_call() -> None:
    source = BRAIN.read_text(encoding="utf-8")
    assert "self._extract_fact(" not in source
    print("PASS: Brain does not invoke the legacy post-response fact extractor")


def test_semantic_boundary_owns_learning_intake() -> None:
    source = BOUNDARY.read_text(encoding="utf-8")
    assert "class SemanticLearningBoundary" in source
    # LearningCoordinator is injected at the boundary rather than imported
    # here, keeping the semantic organ decoupled from a concrete coordinator.
    assert "self.learning" in source
    assert "self.learning.learn" in source
    assert "def learn(" in source
    print("PASS: Semantic Understanding owns the fallback -> learning boundary")


def main() -> None:
    test_brain_has_no_runtime_legacy_fact_extraction_call()
    test_semantic_boundary_owns_learning_intake()
    print("PASS: single authoritative semantic path cleanup validated")


if __name__ == "__main__":
    main()
