from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


class LockedBlueprintPropertyVerifierTests(unittest.TestCase):
    """
    Structural property verifier for the locked JARVIS blueprint.

    Canonical skeleton:

    Input
      -> Perception
      -> Cognition
      -> Cognitive Router
      -> Native / Hybrid / LLM
      -> Brain Decision
      -> Action / Response
      -> Experience / Evaluation
      -> Learning / Knowledge
      -> Self-Evaluation
      -> Evolution
    """

    def read(self, relative_path):
        path = ROOT / relative_path
        self.assertTrue(path.exists(), f"Required file missing: {relative_path}")
        return path.read_text(encoding="utf-8")

    def tree(self, relative_path):
        return ast.parse(self.read(relative_path))

    def imports(self, relative_path):
        tree = self.tree(relative_path)
        result = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.extend(alias.name for alias in node.names)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.append(node.module)

        return result

    # ---------------------------------------------------------
    # PROPERTY 1
    # Perception must not own execution or learning.
    # ---------------------------------------------------------

    def test_perception_has_no_execution_or_learning_imports(self):
        candidates = [
            "core/perception/perception_engine.py",
            "core/perception/__init__.py",
        ]

        existing = [p for p in candidates if (ROOT / p).exists()]

        for path in existing:
            imports = self.imports(path)

            forbidden = [
                "core.execution",
                "core.learning",
                "core.evolution",
            ]

            violations = [
                imp for imp in imports
                if any(imp.startswith(x) for x in forbidden)
            ]

            self.assertEqual(
                violations,
                [],
                f"{path} illegally imports execution/learning/evolution: "
                f"{violations}",
            )

    # ---------------------------------------------------------
    # PROPERTY 2
    # Router must remain a routing boundary.
    # ---------------------------------------------------------

    def test_router_has_no_llm_or_execution_owner_import(self):
        path = ROOT / "core/orchestration/cognitive_router.py"

        self.assertTrue(
            path.exists(),
            "Cognitive Router source file not found."
        )

        imports = self.imports(str(path.relative_to(ROOT)))

        forbidden = [
            "core.llm",
            "core.execution",
            "core.learning",
            "core.evolution",
        ]

        violations = [
            imp for imp in imports
            if any(imp.startswith(x) for x in forbidden)
        ]

        self.assertEqual(
            violations,
            [],
            f"Router owns forbidden components: {violations}",
        )

    # ---------------------------------------------------------
    # PROPERTY 3
    # SelfEvaluator must not execute actions.
    # ---------------------------------------------------------

    def test_self_evaluator_has_no_execution_owner_imports(self):
        path = ROOT / "core/evaluation/self_evaluator.py"

        if not path.exists():
            path = ROOT / "core/learning/self_evaluator.py"

        self.assertTrue(
            path.exists(),
            "SelfEvaluator source file not found."
        )

        imports = self.imports(str(path.relative_to(ROOT)))

        forbidden = [
            "core.execution",
            "core.action",
            "core.evolution",
        ]

        violations = [
            imp for imp in imports
            if any(imp.startswith(x) for x in forbidden)
        ]

        self.assertEqual(
            violations,
            [],
            f"SelfEvaluator owns forbidden components: {violations}",
        )

    # ---------------------------------------------------------
    # PROPERTY 4
    # KnowledgeBuilder must not execute actions.
    # ---------------------------------------------------------

    def test_knowledge_builder_has_no_execution_imports(self):
        path = ROOT / "core/learning/knowledge_builder.py"

        self.assertTrue(
            path.exists(),
            "KnowledgeBuilder source file not found."
        )

        imports = self.imports(str(path.relative_to(ROOT)))

        forbidden = [
            "core.execution",
            "core.action",
            "core.skills.executor",
        ]

        violations = [
            imp for imp in imports
            if any(imp.startswith(x) for x in forbidden)
        ]

        self.assertEqual(
            violations,
            [],
            f"KnowledgeBuilder owns execution: {violations}",
        )

    # ---------------------------------------------------------
    # PROPERTY 5
    # Legacy optional Brain must not return.
    # ---------------------------------------------------------

    def test_legacy_optional_brain_is_absent(self):
        legacy_files = [
            ROOT / "core/brain/optional_brain.py",
            ROOT / "core/optional_brain.py",
            ROOT / "optional_brain.py",
        ]

        existing = [
            str(path.relative_to(ROOT))
            for path in legacy_files
            if path.exists()
        ]

        self.assertEqual(
            existing,
            [],
            f"Legacy optional Brain source exists: {existing}",
        )

    # ---------------------------------------------------------
    # PROPERTY 6
    # Legacy PerceptionEngine must not return.
    # ---------------------------------------------------------

    def test_legacy_perception_engine_is_absent(self):
        legacy = ROOT / "core/perception_engine.py"

        self.assertFalse(
            legacy.exists(),
            "Legacy core/perception_engine.py must not exist.",
        )

    # ---------------------------------------------------------
    # PROPERTY 7
    # LearningCoordinator is the learning dispatch boundary.
    # ---------------------------------------------------------

    def test_learning_coordinator_exists(self):
        path = ROOT / "core/learning/learning_coordinator.py"

        self.assertTrue(
            path.exists(),
            "LearningCoordinator source is missing.",
        )

        source = path.read_text(encoding="utf-8")

        self.assertIn(
            "class LearningCoordinator",
            source,
        )

        self.assertIn(
            "def learn",
            source,
        )

        self.assertIn(
            "def evaluate",
            source,
        )

        self.assertIn(
            "def build_knowledge",
            source,
        )

    # ---------------------------------------------------------
    # PROPERTY 8
    # Learning must pass through SelfEvaluator.
    # ---------------------------------------------------------

    def test_learning_requires_self_evaluation(self):
        source = self.read(
            "core/learning/learning_coordinator.py"
        )

        learn_start = source.find("def learn")

        self.assertNotEqual(
            learn_start,
            -1,
            "LearningCoordinator.learn() missing.",
        )

        learn_body = source[learn_start:]

        self.assertIn(
            "self.evaluator.evaluate",
            learn_body,
            "Learning does not pass through SelfEvaluator.",
        )

    # ---------------------------------------------------------
    # PROPERTY 9
    # Knowledge acceptance must be explicit.
    # ---------------------------------------------------------

    def test_knowledge_acceptance_is_explicit(self):
        source = self.read(
            "core/learning/learning_coordinator.py"
        )

        self.assertIn(
            "def accept_knowledge",
            source,
        )

        self.assertIn(
            "knowledge_builder.accept",
            source,
        )

    # ---------------------------------------------------------
    # PROPERTY 10
    # Skill activation must have an explicit activation boundary.
    # ---------------------------------------------------------

    def test_skill_activation_boundary_exists(self):
        source = self.read(
            "core/learning/learning_coordinator.py"
        )

        self.assertIn(
            "def approve_skill_proposal",
            source,
        )

        self.assertIn(
            "def activate_skill_proposal",
            source,
        )

    # ---------------------------------------------------------
    # PROPERTY 11
    # Evolution must have controlled execution boundary.
    # ---------------------------------------------------------

    def test_controlled_evolution_boundary_exists(self):
        evolution_files = [
            ROOT / "core/learning/controlled_evolution.py",
            ROOT / "core/learning/evolution_engine.py",
            ROOT / "core/evolution/controlled_evolution.py",
            ROOT / "core/evolution/evolution_engine.py",
            ROOT / "core/evolution/controlled_evolution_engine.py",
        ]

        existing = [p for p in evolution_files if p.exists()]

        self.assertTrue(
            existing,
            "No controlled evolution engine found.",
        )

        source = "\n".join(
            p.read_text(encoding="utf-8")
            for p in existing
        )

        self.assertTrue(
            "approve" in source.lower(),
            "Evolution approval boundary not found.",
        )

        self.assertTrue(
            "validate" in source.lower(),
            "Evolution validation boundary not found.",
        )

    # ---------------------------------------------------------
    # PROPERTY 12
    # Brain must remain the central orchestration boundary.
    # ---------------------------------------------------------

    def test_brain_source_exists(self):
        candidates = [
            ROOT / "core/orchestration/brain.py",
            ROOT / "core/brain/brain.py",
            ROOT / "core/brain.py",
        ]

        existing = [p for p in candidates if p.exists()]

        self.assertTrue(
            existing,
            "Canonical Brain source not found.",
        )

    # ---------------------------------------------------------
    # PROPERTY 13
    # Blueprint test suite itself must remain present.
    # ---------------------------------------------------------

    def test_locked_blueprint_suite_exists(self):
        required = [
            ROOT / "tests/blueprint/test_locked_blueprint_boundaries.py",
            ROOT / "tests/blueprint/test_locked_blueprint_runtime.py",
        ]

        missing = [
            str(p.relative_to(ROOT))
            for p in required
            if not p.exists()
        ]

        self.assertEqual(
            missing,
            [],
            f"Locked blueprint test files missing: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
