import inspect
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.orchestration.perception import PerceptionEngine, PerceptionResult, LLMPerceptionProvider
from core.orchestration.cognitive_router import CognitiveRouter
from core.learning.experience_engine import ExperienceEngine
from core.learning.self_evaluator import SelfEvaluator
from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator
from core.learning.learning_queue import AsyncLearningQueue
from core.skills.skill_learner import SkillLearner
from core.skills.skill_registry import SkillRegistry
from core.skills.skill_executor import SkillExecutor
from core.autonomy.idle_executor import IdleExecutor
from core.learning.controlled_evolution import ControlledEvolutionEngine
from core.organism.bootstrap import create_jarvis, stop_jarvis


class _Provider:
    name = "blueprint-test"
    def __init__(self, result):
        self.result = result
        self.calls = []
    def perceive(self, user_input, context=None):
        self.calls.append((user_input, context))
        return self.result


class BlueprintPerceptionTests(unittest.TestCase):
    def test_structured_perception_contract_contains_required_fields(self):
        result = PerceptionResult(
            user_input="run ping",
            normalized_text="run ping",
            intent={"name": "execute", "skill": "ping"},
            entities={"target": "ping"},
            language="en",
            confidence=0.95,
            uncertainty=0.05,
            source="test",
            reason="deterministic",
        )
        data = result.as_dict()
        for key in ("user_input", "normalized_text", "intent", "entities", "goal",
                    "requested_capability", "speech_act", "language", "confidence",
                    "uncertainty", "source", "reason", "timestamp"):
            self.assertIn(key, data)

    def test_perception_engine_uses_provider_and_publishes_result(self):
        result = PerceptionResult("hello", "hello", intent={"name": "chat"}, confidence=.9, uncertainty=.1, source="p")
        provider = _Provider(result)
        engine = PerceptionEngine([provider])
        actual = engine.perceive("hello", context={"memory": []})
        self.assertIs(actual, result)
        self.assertIs(engine.last_result, result)
        self.assertEqual(provider.calls[0][0], "hello")

    def test_perception_provider_never_answers_user(self):
        llm = Mock()
        llm.generate_response.return_value = '{"intent":{"name":"chat"},"entities":{},"goal":null,"requested_capability":null,"speech_act":"inform","language":"en","confidence":0.9,"reason":"test"}'
        result = LLMPerceptionProvider(llm).perceive("hello")
        self.assertIsInstance(result, PerceptionResult)
        self.assertEqual(result.source, "llm")
        prompt = llm.generate_response.call_args.kwargs["system_prompt"]
        self.assertIn("Never answer the user", prompt)

    def test_perception_failure_degrades_to_structured_empty_result(self):
        class Bad:
            name = "bad"
            def perceive(self, *args, **kwargs):
                raise RuntimeError("boom")
        result = PerceptionEngine([Bad()]).perceive("hello")
        self.assertEqual(result.source, "none")
        self.assertEqual(result.intent, {})
        self.assertEqual(result.entities, {})


class BlueprintRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = CognitiveRouter()

    def test_native_requires_confident_input_matched_perception_and_skill(self):
        d = self.router.decide(
            user_input="run ping",
            perception={"user_input": "run ping", "confidence": .95, "intent": {"skill": "ping"}},
            skills={"ping": object()},
        )
        self.assertEqual(d.mode, "native")
        self.assertFalse(d.llm_required)

    def test_hybrid_requires_explicit_hybrid_request(self):
        d = self.router.decide(
            user_input="summarize ping",
            perception={"user_input": "summarize ping", "confidence": .95,
                        "intent": {"skill": "ping", "execution_mode": "hybrid"}},
            skills={"ping": object()},
        )
        self.assertEqual(d.mode, "hybrid")
        self.assertTrue(d.llm_required)

    def test_hybrid_without_native_capability_falls_back_to_llm(self):
        d = self.router.decide(
            user_input="summarize",
            perception={"user_input": "summarize", "confidence": .95,
                        "intent": {"skill": "missing", "execution_mode": "hybrid"}},
            skills={},
        )
        self.assertEqual(d.mode, "llm")
        self.assertTrue(d.llm_required)

    def test_low_confidence_or_mismatched_perception_cannot_take_deterministic_route(self):
        for confidence, source_input in ((.2, "run ping"), (.95, "other input")):
            d = self.router.decide(
                user_input="run ping",
                perception={"user_input": source_input, "confidence": confidence,
                            "intent": {"skill": "ping"}},
                skills={"ping": object()},
            )
            self.assertEqual(d.mode, "llm")
            self.assertTrue(d.llm_required)

    def test_confirmation_is_a_non_llm_boundary(self):
        d = self.router.decide(
            user_input="delete it",
            perception={"user_input": "delete it", "confidence": .99,
                        "intent": {"skill": "delete", "requires_confirmation": True}},
            skills={"delete": object()},
        )
        self.assertEqual(d.mode, "clarify")
        self.assertFalse(d.llm_required)

    def test_explicit_goal_is_owned_by_brain_not_router_planner(self):
        d = self.router.decide(
            user_input="learn this",
            perception={"user_input": "learn this", "confidence": .99,
                        "intent": {"name": "goal"}, "goal": {"text": "learn this"}},
        )
        self.assertEqual(d.mode, "goal")
        self.assertFalse(d.llm_required)


class BlueprintExperienceLearningTests(unittest.TestCase):
    def _experience(self, success=True):
        return ExperienceEngine().process(
            event_type="BRAIN_ACTION_RESPONSE",
            context={"subject": "python", "predicate": "used_for", "value": "automation"},
            action={"skill": "ping"},
            outcome={"success": success, "status": "completed" if success else "failed"},
            source="brain",
        )["experience"]

    def test_success_and_failure_both_become_experience(self):
        ee = ExperienceEngine()
        ok = ee.process("ACTION", {}, {"skill": "x"}, {"success": True})["experience"]
        bad = ee.process("ACTION", {}, {"skill": "x"}, {"success": False})["experience"]
        self.assertTrue(ok["success"])
        self.assertFalse(bad["success"])
        self.assertEqual(ee.statistics()["processed"], 2)

    def test_self_evaluator_is_between_experience_and_learning(self):
        evaluation = SelfEvaluator().evaluate(self._experience(True))
        self.assertEqual(evaluation["type"], "SELF_EVALUATION")
        self.assertIn("success", evaluation)
        self.assertIn("score", evaluation)
        self.assertIn("errors", evaluation)
        self.assertIn("strengths", evaluation)

    def test_failed_experience_cannot_become_knowledge_candidate(self):
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder()
        exp = self._experience(False)
        ev = evaluator.evaluate(exp)
        self.assertIsNone(builder.build(exp, ev))
        self.assertEqual(builder.built_count, 0)

    def test_successful_experience_is_candidate_until_acceptance(self):
        memory = Mock()
        builder = KnowledgeBuilder(memory_manager=memory)
        exp = self._experience(True)
        ev = SelfEvaluator().evaluate(exp)
        candidate = builder.build(exp, ev)
        self.assertEqual(candidate["status"], "CANDIDATE")
        memory.remember_knowledge.assert_not_called()
        accepted = builder.accept(candidate["id"])
        self.assertEqual(accepted["status"], "ACCEPTED")
        memory.remember_knowledge.assert_called_once()

    def test_learning_coordinator_separates_evaluation_knowledge_and_skill_paths(self):
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder()
        learner = SkillLearner(min_repetitions=3, min_success_rate=.8)
        registry = SkillRegistry()
        coordinator = LearningCoordinator(evaluator=evaluator, knowledge_builder=builder,
                                           skill_learner=learner, skill_registry=registry)
        result = coordinator.learn(self._experience(True))
        self.assertEqual(result["type"], "LEARNING_CYCLE")
        self.assertIsNotNone(result["evaluation"])
        self.assertIsNotNone(result["knowledge"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["skill_proposals"], [])

    def test_auto_accept_is_explicitly_controlled(self):
        memory = Mock()
        memory.remember_knowledge.return_value = type("K", (), {"knowledge_id": "k1", "to_dict": lambda self: {"id": "k1"}})()
        builder = KnowledgeBuilder(memory_manager=memory)
        coordinator = LearningCoordinator(evaluator=SelfEvaluator(), knowledge_builder=builder)
        result = coordinator.learn(self._experience(True), auto_accept=True)
        self.assertTrue(result["accepted"])
        memory.remember_knowledge.assert_called_once()


class BlueprintSkillBoundaryTests(unittest.TestCase):
    def _learner(self):
        learner = SkillLearner(min_repetitions=3, min_success_rate=.8)
        exp = {"action": {"skill": "calculate_total"}, "outcome": {"success": True, "detail": "ok"}, "context": {"goal": "total"}}
        for _ in range(3):
            learner.observe(exp)
        return learner

    def test_one_success_is_not_a_skill(self):
        learner = SkillLearner(min_repetitions=3)
        learner.observe({"action": {"skill": "x"}, "outcome": {"success": True}})
        self.assertEqual(learner.list_proposals(), [])

    def test_repeated_verified_success_creates_proposal_not_executable_skill(self):
        learner = self._learner()
        proposal = learner.list_proposals()[0]
        self.assertEqual(proposal["status"], "proposed")
        registry = SkillRegistry()
        self.assertFalse(registry.is_registered(proposal["name"]))

    def test_unapproved_proposal_cannot_enter_registry(self):
        learner = self._learner()
        registry = SkillRegistry()
        with self.assertRaises(PermissionError):
            registry.register_approved(learner.list_proposals()[0], lambda: 42)
        self.assertFalse(registry.is_registered("skill_calculate_total"))

    def test_explicit_approval_then_activation_is_required(self):
        learner = self._learner()
        registry = SkillRegistry()
        coordinator = LearningCoordinator(skill_learner=learner, skill_registry=registry)
        name = learner.list_proposals()[0]["name"]
        coordinator.approve_skill_proposal(name)
        self.assertFalse(registry.is_registered(name))
        coordinator.activate_skill_proposal(name, lambda: 42)
        self.assertTrue(registry.is_registered(name))
        self.assertEqual(registry.metadata[name]["source"], "learned")

    def test_skill_executor_executes_only_registered_capability(self):
        registry = SkillRegistry()
        executor = SkillExecutor(registry)
        with self.assertRaises(KeyError):
            executor.execute("not_registered")
        registry.register("safe", lambda: "ok")
        self.assertEqual(executor.execute("safe"), "ok")


class BlueprintIdleEvolutionTests(unittest.TestCase):
    def test_idle_executor_blocks_confirmation_and_unknown_capability(self):
        called = []
        executor = IdleExecutor({"safe": lambda step: called.append(step) or "ok"})
        blocked = executor.execute({"action": "safe", "requires_confirmation": True})
        self.assertFalse(blocked["success"])
        self.assertEqual(called, [])
        unknown = executor.execute({"action": "missing"})
        self.assertFalse(unknown["success"])

    def test_idle_executor_success_is_structured_result(self):
        executor = IdleExecutor({"safe": lambda step: "ok"})
        result = executor.execute({"action": "safe", "declared_side_effects": ["none"], "risk": "low"})
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["side_effects"], ["none"])

    def test_controlled_evolution_requires_proposal_validation_and_approval(self):
        evolution = ControlledEvolutionEngine()
        calls = []
        evolution.register_adapter("routing", lambda p: calls.append(p["id"]) or {"changed": True})
        proposal = evolution.propose({"score": .2, "errors": ["bad route"], "strengths": []}, "routing")
        self.assertEqual(proposal["status"], "PROPOSED")
        with self.assertRaises(RuntimeError):
            evolution.apply(proposal["id"])
        self.assertEqual(calls, [])
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])
        applied = evolution.apply(proposal["id"])
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(calls, [proposal["id"]])

    def test_controlled_evolution_blocks_approved_proposal_without_adapter(self):
        evolution = ControlledEvolutionEngine()
        proposal = evolution.propose({"score": .1, "errors": ["x"], "strengths": []}, "unwired")
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])
        with self.assertRaises(PermissionError):
            evolution.apply(proposal["id"])
        self.assertEqual(evolution.get_proposal(proposal["id"])["status"], "APPROVED")
        self.assertEqual(evolution.statistics()["applied"], 0)


class BlueprintBootstrapAndArchitectureTests(unittest.TestCase):
    def test_bootstrap_wires_the_canonical_organs(self):
        jarvis = create_jarvis(heartbeat_interval=60, idle_threshold=120)
        try:
            required = {"brain", "perception", "cognitive_router", "experience", "evaluator",
                        "knowledge_builder", "learning", "evolution", "skill_learner",
                        "skill_registry", "skill_executor", "goal_manager", "planner", "idle_loop"}
            self.assertTrue(required.issubset(jarvis.organs))
            self.assertIs(jarvis.get_organ("brain").perception, jarvis.get_organ("perception"))
            self.assertIs(jarvis.get_organ("brain").cognitive_router, jarvis.get_organ("cognitive_router"))
            self.assertIs(jarvis.get_organ("brain").skill_registry, jarvis.get_organ("skill_registry"))
        finally:
            stop_jarvis(jarvis)

    def test_idle_loop_crosses_brain_executor_boundary(self):
        jarvis = create_jarvis(heartbeat_interval=60, idle_threshold=120)
        try:
            brain = jarvis.get_organ("brain")
            idle = jarvis.get_organ("idle_loop")
            self.assertIs(idle.executor.__self__, brain)
            self.assertEqual(idle.executor.__func__, brain.execute_autonomous_step.__func__)
        finally:
            stop_jarvis(jarvis)

    def test_brain_owns_router_and_action_response_state(self):
        from core.orchestration.brain import Brain
        brain = Brain()
        for attr in ("cognitive_router", "perception", "last_cognitive_decision",
                     "last_brain_decision", "last_action_response"):
            self.assertTrue(hasattr(brain, attr), attr)
        self.assertTrue(callable(brain.think_and_respond))

    def test_no_legacy_optional_brain_source_exists(self):
        root = Path(__file__).resolve().parents[2]
        self.assertFalse((root / "core/orchestration/llm_optional_brain.py").exists())
        matches = []
        for path in (root / "core").rglob("*.py"):
            text = path.read_text(errors="ignore")
            if any(token in text for token in ("LLMOptionalBrain", "OptionalLLMBrain", "llm_optional_brain")):
                matches.append(str(path.relative_to(root)))
        self.assertEqual(matches, [])

    def test_brain_is_not_named_or_subclassed_as_llm_owner(self):
        from core.orchestration.brain import Brain
        self.assertEqual(Brain.__name__, "Brain")
        self.assertNotIn("LLM", [base.__name__ for base in inspect.getmro(Brain)[1:]])


class BlueprintQueueTests(unittest.TestCase):
    def test_learning_queue_is_fifo_single_worker_boundary(self):
        seen = []
        queue = AsyncLearningQueue(lambda job: seen.append(job["id"]))
        queue.start()
        try:
            for i in range(5):
                self.assertTrue(queue.submit({"id": i}))
            queue._q.join()
            self.assertEqual(seen, [0, 1, 2, 3, 4])
            self.assertEqual(queue.status()["processed"], 5)
        finally:
            queue.stop()


if __name__ == "__main__":
    unittest.main()
