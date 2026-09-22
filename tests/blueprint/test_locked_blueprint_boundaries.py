"""Executable contract tests for the locked JARVIS architecture.

These tests intentionally test boundaries, not implementation trivia.  A future
module may be rewritten, but these contracts must continue to hold:

Perception -> Cognition -> Router -> Brain -> Action/Response -> Experience
-> Self-Evaluation -> Learning -> Knowledge/Skill -> Approval/Activation
and the separate controlled Evolution boundary.
"""

import ast
import inspect
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.autonomy.idle_executor import IdleExecutor
from core.autonomy.idle_loop import IdleLoop
from core.learning.controlled_evolution import ControlledEvolutionEngine
from core.learning.experience_engine import ExperienceEngine
from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator
from core.learning.learning_queue import AsyncLearningQueue
from core.learning.self_evaluator import SelfEvaluator
from core.orchestration.brain import Brain
from core.orchestration.cognitive_router import CognitiveRouter
from core.orchestration.llm_bridge import HybridLLMBridge
from core.orchestration.perception import LLMPerceptionProvider, PerceptionEngine, PerceptionResult
from core.skills.skill_executor import SkillExecutor
from core.skills.skill_learner import SkillLearner
from core.skills.skill_registry import SkillRegistry


ROOT = Path(__file__).resolve().parents[2]


class LockedBlueprintStaticBoundaryTests(unittest.TestCase):
    def _source(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def _tree(self, relative):
        return ast.parse(self._source(relative), filename=relative)

    def test_legacy_optional_brain_is_absent(self):
        self.assertFalse((ROOT / "core/orchestration/llm_optional_brain.py").exists())
        for path in (ROOT / "core").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("LLMOptionalBrain", text, str(path))
            self.assertNotIn("OptionalLLMBrain", text, str(path))
            self.assertNotIn("llm_optional_brain", text, str(path))

    def test_legacy_perception_engine_file_is_absent(self):
        self.assertFalse((ROOT / "core/orchestration/perception_engine.py").exists())

    def test_perception_has_no_execution_or_learning_imports(self):
        tree = self._tree("core/orchestration/perception.py")
        forbidden = {"SkillExecutor", "SkillRegistry", "LearningCoordinator",
                     "KnowledgeBuilder", "ControlledEvolutionEngine", "ExperienceEngine"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[-1] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
        self.assertTrue(forbidden.isdisjoint(imported), imported & forbidden)

    def test_router_has_no_llm_or_execution_owner_import(self):
        tree = self._tree("core/orchestration/cognitive_router.py")
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.lower() for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(a.name.lower() for a in node.names)
        self.assertFalse(any("llm" in name for name in imported), imported)
        self.assertFalse(any("executor" in name for name in imported), imported)
        self.assertFalse(any("brain" in name for name in imported), imported)

    def test_self_evaluator_has_no_execution_owner_imports(self):
        tree = self._tree("core/learning/self_evaluator.py")
        forbidden = {"SkillExecutor", "SkillRegistry", "KnowledgeBuilder", "LearningCoordinator"}
        imported = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for a in node.names}
        self.assertTrue(forbidden.isdisjoint(imported))

    def test_knowledge_builder_does_not_import_execution_components(self):
        tree = self._tree("core/learning/knowledge_builder.py")
        forbidden = {"SkillExecutor", "SkillRegistry", "IdleExecutor", "ControlledEvolutionEngine"}
        imported = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for a in node.names}
        self.assertTrue(forbidden.isdisjoint(imported))

    def test_brain_is_central_orchestrator_not_llm_subclass(self):
        self.assertEqual(Brain.__name__, "Brain")
        self.assertEqual(Brain.__bases__, (object,))
        self.assertIn("cognitive_router", inspect.signature(Brain.__init__).parameters)
        self.assertIn("perception_engine", inspect.signature(Brain.__init__).parameters)


class LockedBlueprintPerceptionRouterTests(unittest.TestCase):
    def test_perception_result_is_structured_not_response_text(self):
        result = PerceptionResult(
            "hello", "hello", intent={"name": "chat"}, entities={"x": "y"},
            language="en", confidence=.91, uncertainty=.09, source="test", reason="ok"
        )
        data = result.as_dict()
        required = {"user_input", "normalized_text", "intent", "entities", "goal",
                    "requested_capability", "speech_act", "language", "confidence",
                    "uncertainty", "source", "reason", "timestamp"}
        self.assertTrue(required.issubset(data))
        self.assertNotIn("response", data)

    def test_llm_perception_is_for_structured_understanding_only(self):
        llm = Mock()
        llm.generate_response.return_value = (
            '{"intent":{"name":"chat"},"entities":{},"goal":null,'
            '"requested_capability":null,"speech_act":"inform","language":"en",'
            '"confidence":0.9,"reason":"structured"}'
        )
        result = LLMPerceptionProvider(llm).perceive("hello")
        self.assertEqual(result.source, "llm")
        self.assertNotIn("response", result.as_dict())
        system_prompt = llm.generate_response.call_args.kwargs["system_prompt"]
        self.assertIn("Never answer the user", system_prompt)

    def test_perception_provider_failure_degrades_without_action(self):
        class Broken:
            name = "broken"
            def perceive(self, *args, **kwargs):
                raise RuntimeError("broken")
        result = PerceptionEngine([Broken()]).perceive("do something")
        self.assertEqual(result.source, "none")
        self.assertEqual(result.intent, {})

    def test_router_native_requires_input_match_confidence_and_capability(self):
        router = CognitiveRouter()
        decision = router.decide(
            user_input="run ping",
            perception={"user_input": "run ping", "confidence": .95, "intent": {"skill": "ping"}},
            skills={"ping": object()},
        )
        self.assertEqual(decision.mode, "tool")
        self.assertFalse(decision.llm_required)

    def test_router_low_confidence_forces_fallback(self):
        router = CognitiveRouter()
        decision = router.decide(
            user_input="run ping",
            perception={"user_input": "run ping", "confidence": .79, "intent": {"skill": "ping"}},
            skills={"ping": object()},
        )
        self.assertEqual(decision.mode, "llm")
        self.assertTrue(decision.llm_required)

    def test_router_mismatched_perception_cannot_execute(self):
        router = CognitiveRouter()
        decision = router.decide(
            user_input="run ping",
            perception={"user_input": "delete files", "confidence": .99, "intent": {"skill": "ping"}},
            skills={"ping": object()},
        )
        self.assertEqual(decision.mode, "llm")
        self.assertTrue(decision.llm_required)

    def test_router_hybrid_is_explicit_and_requires_native_capability(self):
        router = CognitiveRouter()
        hybrid = router.decide(
            user_input="summarize ping",
            perception={"user_input": "summarize ping", "confidence": .95,
                        "intent": {"skill": "ping", "execution_mode": "hybrid"}},
            skills={"ping": object()},
        )
        self.assertEqual(hybrid.mode, "hybrid")
        self.assertTrue(hybrid.llm_required)

        fallback = router.decide(
            user_input="summarize ping",
            perception={"user_input": "summarize ping", "confidence": .95,
                        "intent": {"skill": "ping", "execution_mode": "hybrid"}},
            skills={},
        )
        self.assertEqual(fallback.mode, "llm")

    def test_router_confirmation_never_becomes_llm_execution(self):
        decision = CognitiveRouter().decide(
            user_input="delete it",
            perception={"user_input": "delete it", "confidence": .99,
                        "intent": {"skill": "delete", "requires_confirmation": True}},
            skills={"delete": object()},
        )
        self.assertEqual(decision.mode, "clarify")
        self.assertFalse(decision.llm_required)

    def test_router_goal_route_does_not_plan(self):
        decision = CognitiveRouter().decide(
            user_input="learn this",
            perception={"user_input": "learn this", "confidence": .99,
                        "intent": {"name": "goal"}, "goal": {"text": "learn this"}},
        )
        self.assertEqual(decision.mode, "goal")
        self.assertFalse(decision.llm_required)
        self.assertNotIn("plan", decision.as_dict())


class LockedBlueprintLearningBoundaryTests(unittest.TestCase):
    @staticmethod
    def experience(success=True, fact=True):
        context = {"subject": "jarvis", "predicate": "mode", "value": "offline"} if fact else {}
        return ExperienceEngine().process(
            "BRAIN_ACTION_RESPONSE", context=context,
            action={"skill": "safe_action"},
            outcome={"success": success, "status": "completed" if success else "failed"},
            source="brain",
        )["experience"]

    def test_success_and_failure_are_both_experiences(self):
        engine = ExperienceEngine()
        success = engine.process("ACTION", {}, {"skill": "x"}, {"success": True})["experience"]
        failure = engine.process("ACTION", {}, {"skill": "x"}, {"success": False})["experience"]
        self.assertTrue(success["success"])
        self.assertFalse(failure["success"])
        self.assertEqual(engine.statistics()["processed"], 2)

    def test_experience_does_not_directly_persist_knowledge(self):
        memory = Mock()
        ExperienceEngine(memory_manager=memory).process(
            "ACTION", {}, {"skill": "x"}, {"success": True}
        )
        memory.remember_knowledge.assert_not_called()
        memory.remember_experience.assert_called_once()

    def test_self_evaluation_is_required_before_knowledge_building(self):
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder()
        exp = self.experience(True)
        evaluation = evaluator.evaluate(exp)
        candidate = builder.build(exp, evaluation)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["status"], "CANDIDATE")

    def test_failed_evaluation_cannot_create_knowledge_candidate(self):
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder()
        exp = self.experience(False)
        evaluation = evaluator.evaluate(exp)
        self.assertFalse(evaluation["success"])
        self.assertIsNone(builder.build(exp, evaluation))

    def test_candidate_does_not_enter_semantic_memory_before_acceptance(self):
        memory = Mock()
        builder = KnowledgeBuilder(memory_manager=memory)
        candidate = builder.build(self.experience(True), {"success": True, "score": 1.0})
        self.assertEqual(candidate["status"], "CANDIDATE")
        memory.remember_knowledge.assert_not_called()
        builder.accept(candidate["id"])
        memory.remember_knowledge.assert_called_once()

    def test_learning_coordinator_is_dispatch_boundary(self):
        evaluator = Mock()
        evaluator.evaluate.return_value = {"type": "SELF_EVALUATION", "success": True, "score": 1.0,
                                           "errors": [], "strengths": []}
        builder = Mock()
        builder.build.return_value = None
        learner = Mock()
        learner.observe.return_value = []
        coordinator = LearningCoordinator(evaluator=evaluator, knowledge_builder=builder, skill_learner=learner)
        result = coordinator.learn(self.experience(True, fact=False))
        evaluator.evaluate.assert_called_once()
        builder.build.assert_called_once()
        learner.observe.assert_called_once()
        self.assertEqual(result["type"], "LEARNING_CYCLE")

    def test_learning_stopped_is_a_controlled_failure(self):
        coordinator = LearningCoordinator(evaluator=SelfEvaluator())
        coordinator.stop()
        with self.assertRaises(RuntimeError):
            coordinator.learn(self.experience(True))


class LockedBlueprintSkillBoundaryTests(unittest.TestCase):
    def _proposal(self):
        learner = SkillLearner(min_repetitions=3, min_success_rate=.8)
        exp = {"action": {"skill": "calculate_total"}, "outcome": {"success": True, "detail": "ok"}}
        for _ in range(3):
            proposals = learner.observe(exp)
        self.assertTrue(proposals)
        return learner, proposals[0]

    def test_one_success_is_not_executable_capability(self):
        learner = SkillLearner(min_repetitions=3)
        self.assertEqual(learner.observe({"action": {"skill": "x"}, "outcome": {"success": True}}), [])
        self.assertEqual(learner.list_proposals(), [])

    def test_failed_observation_never_contributes_to_skill_learning(self):
        learner = SkillLearner(min_repetitions=2, min_success_rate=1.0)
        learner.observe({"action": {"skill": "x"}, "outcome": {"success": False}})
        learner.observe({"action": {"skill": "x"}, "outcome": {"success": True}})
        self.assertEqual(learner.list_proposals(), [])

    def test_repeated_verified_success_creates_proposal_only(self):
        learner, proposal = self._proposal()
        self.assertEqual(proposal["status"], "proposed")
        registry = SkillRegistry()
        self.assertFalse(registry.is_registered(proposal["name"]))
        self.assertEqual(learner.statistics()["registered"], 0)

    def test_unapproved_proposal_is_rejected_by_registry(self):
        _, proposal = self._proposal()
        registry = SkillRegistry()
        with self.assertRaises(PermissionError):
            registry.register_approved(proposal, lambda: "ok")
        self.assertFalse(registry.is_registered(proposal["name"]))

    def test_approval_alone_does_not_activate(self):
        learner, proposal = self._proposal()
        approved = learner.approve(proposal["name"])
        self.assertEqual(approved["status"], "approved")
        registry = SkillRegistry()
        self.assertFalse(registry.is_registered(proposal["name"]))

    def test_activation_requires_approved_state(self):
        learner, proposal = self._proposal()
        registry = SkillRegistry()
        coordinator = LearningCoordinator(skill_learner=learner, skill_registry=registry)
        with self.assertRaises(PermissionError):
            coordinator.activate_skill_proposal(proposal["name"], lambda: "ok")
        self.assertFalse(registry.is_registered(proposal["name"]))

    def test_approved_activation_registers_learned_capability(self):
        learner, proposal = self._proposal()
        registry = SkillRegistry()
        coordinator = LearningCoordinator(skill_learner=learner, skill_registry=registry)
        coordinator.approve_skill_proposal(proposal["name"])
        result = coordinator.activate_skill_proposal(proposal["name"], lambda: "ok")
        self.assertEqual(result["status"], "registered")
        self.assertTrue(registry.is_registered(proposal["name"]))
        self.assertEqual(registry.metadata[proposal["name"]]["source"], "learned")

    def test_skill_executor_is_registry_bound(self):
        registry = SkillRegistry()
        executor = SkillExecutor(registry)
        with self.assertRaises(KeyError):
            executor.execute("missing")
        registry.register("safe", lambda: "ok")
        self.assertEqual(executor.execute("safe"), "ok")


class LockedBlueprintIdleBoundaryTests(unittest.TestCase):
    def test_idle_confirmation_is_not_executed(self):
        calls = []
        executor = IdleExecutor({"safe": lambda step: calls.append(step) or "ok"})
        result = executor.execute({"action": "safe", "requires_confirmation": True})
        self.assertFalse(result["success"])
        self.assertEqual(result["result"], "confirmation_required")
        self.assertEqual(calls, [])

    def test_idle_unknown_capability_is_not_executed(self):
        calls = []
        executor = IdleExecutor({"safe": lambda step: calls.append(step)})
        result = executor.execute({"action": "unknown"})
        self.assertFalse(result["success"])
        self.assertEqual(calls, [])

    def test_idle_failure_is_structured_and_not_reported_as_success(self):
        executor = IdleExecutor({"bad": lambda step: (_ for _ in ()).throw(RuntimeError("boom"))})
        result = executor.execute({"action": "bad"})
        self.assertFalse(result["success"])
        self.assertIn("boom", result["result"])

    def test_idle_loop_delegates_execution_to_supplied_brain_boundary(self):
        executor = Mock(return_value={"success": True, "result": "ok"})
        goal_manager = Mock()
        goal_manager.pending.return_value = []
        goal_manager.next_goal.return_value = None
        curiosity = Mock()
        curiosity.candidates.return_value = []
        planner = Mock()
        loop = IdleLoop(goal_manager=goal_manager, curiosity=curiosity, planner=planner, executor=executor)
        result = loop.step()
        self.assertEqual(result["action"], "NO_OP")
        executor.assert_not_called()


class LockedBlueprintEvolutionBoundaryTests(unittest.TestCase):
    def _engine(self):
        return ControlledEvolutionEngine()

    def test_proposal_starts_unapplied(self):
        proposal = self._engine().propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertIsNone(proposal["applied_at"])

    def test_evolution_cannot_skip_validation(self):
        engine = self._engine()
        proposal = engine.propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        with self.assertRaises(RuntimeError):
            engine.approve(proposal["id"])
        with self.assertRaises(RuntimeError):
            engine.apply(proposal["id"])

    def test_evolution_cannot_skip_approval(self):
        engine = self._engine()
        proposal = engine.propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        engine.validate(proposal["id"])
        with self.assertRaises(RuntimeError):
            engine.apply(proposal["id"])

    def test_controlled_evolution_requires_registered_adapter(self):
        engine = self._engine()
        proposal = engine.propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        engine.validate(proposal["id"])
        engine.approve(proposal["id"])
        with self.assertRaises(PermissionError):
            engine.apply(proposal["id"])
        self.assertEqual(engine.get_proposal(proposal["id"])["status"], "APPROVED")

    def test_controlled_evolution_applies_only_after_full_gate(self):
        engine = self._engine()
        calls = []
        engine.register_adapter("routing", lambda proposal: calls.append(proposal["id"]) or {"changed": True})
        proposal = engine.propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        engine.validate(proposal["id"])
        engine.approve(proposal["id"])
        applied = engine.apply(proposal["id"])
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(calls, [proposal["id"]])

    def test_adapter_failure_does_not_mark_evolution_applied(self):
        engine = self._engine()
        engine.register_adapter("routing", lambda proposal: (_ for _ in ()).throw(RuntimeError("adapter failed")))
        proposal = engine.propose({"score": .2, "errors": ["bad"], "strengths": []}, "routing")
        engine.validate(proposal["id"])
        engine.approve(proposal["id"])
        with self.assertRaises(RuntimeError):
            engine.apply(proposal["id"])
        self.assertEqual(engine.get_proposal(proposal["id"])["status"], "APPROVED")
        self.assertEqual(engine.statistics()["applied"], 0)


class LockedBlueprintQueueTests(unittest.TestCase):
    def test_queue_is_fifo_and_single_worker(self):
        seen = []
        active = 0
        peak = 0
        lock = threading.Lock()

        def worker(job):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            seen.append(job["id"])
            with lock:
                active -= 1

        queue = AsyncLearningQueue(worker=worker, max_queue=10)
        queue.start()
        try:
            for i in range(5):
                self.assertTrue(queue.submit({"id": i}))
            queue._q.join()
            self.assertEqual(seen, [0, 1, 2, 3, 4])
            self.assertEqual(peak, 1)
            self.assertEqual(queue.status()["failed"], 0)
        finally:
            queue.stop()

    def test_queue_records_worker_failure_without_killing_worker(self):
        seen = []
        def worker(job):
            if job["id"] == 1:
                raise RuntimeError("expected failure")
            seen.append(job["id"])
        queue = AsyncLearningQueue(worker=worker, max_queue=5)
        queue.start()
        try:
            for i in range(3):
                queue.submit({"id": i})
            queue._q.join()
            status = queue.status()
            self.assertEqual(seen, [0, 2])
            self.assertEqual(status["failed"], 1)
            self.assertEqual(status["last_error"], "expected failure")
        finally:
            queue.stop()

    def test_queue_has_bounded_overflow_behavior(self):
        gate = threading.Event()
        release = threading.Event()
        seen = []
        def worker(job):
            seen.append(job["id"])
            if job["id"] == 0:
                gate.set()
                release.wait(1)
        queue = AsyncLearningQueue(worker=worker, max_queue=2)
        queue.start()
        try:
            self.assertTrue(queue.submit({"id": 0}))
            gate.wait(1)
            self.assertTrue(queue.submit({"id": 1}))
            self.assertTrue(queue.submit({"id": 2}))
            self.assertTrue(queue.submit({"id": 3}))
            self.assertGreaterEqual(queue.status()["dropped"], 1)
            release.set()
            queue._q.join()
        finally:
            release.set()
            queue.stop()


class LockedBlueprintLLMBoundaryTests(unittest.TestCase):
    def test_combined_bridge_parses_response_and_memory_signal_without_persisting(self):
        bridge = HybridLLMBridge(force_mode="offline")
        bridge.generate_response = Mock(return_value=(
            '{"response":"I remember.","memory":{"has_fact":true,'
            '"subject":"jarvis","predicate":"mode","value":"offline"}}'
        ))
        result = bridge.generate_combined("system", "hello")
        self.assertEqual(result["response"], "I remember.")
        self.assertEqual(result["memory_signal"]["predicate"], "mode")
        self.assertEqual(bridge.generate_response.call_count, 1)

    def test_malformed_combined_llm_output_becomes_response_only(self):
        bridge = HybridLLMBridge(force_mode="offline")
        bridge.generate_response = Mock(return_value="plain answer")
        result = bridge.generate_combined("system", "hello")
        self.assertEqual(result["response"], "plain answer")
        self.assertIsNone(result["memory_signal"])

    def test_llm_perception_and_llm_response_are_distinct_contracts(self):
        self.assertNotEqual(LLMPerceptionProvider.SYSTEM_PROMPT, "")
        self.assertIn("structured perception", LLMPerceptionProvider.SYSTEM_PROMPT)
        self.assertIn("response", HybridLLMBridge._MEMORY_SIGNAL_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
