import unittest

from core.learning.experience_engine import ExperienceEngine
from core.learning.self_evaluator import SelfEvaluator
from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator


class ExperienceLearningKnowledgeContractTests(unittest.TestCase):
    """Verify the controlled Experience -> Learning -> Knowledge boundary."""

    def _build_learning_stack(self):
        experience = ExperienceEngine()
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder()
        learning = LearningCoordinator(
            evaluator=evaluator,
            knowledge_builder=builder,
        )
        return experience, learning, builder

    def test_successful_experience_becomes_untrusted_knowledge_candidate(self):
        experience_engine, learning, builder = self._build_learning_stack()

        processed = experience_engine.process(
            event_type="TASK_COMPLETED",
            context={"subject": "python", "predicate": "used_for", "value": "automation"},
            action={"name": "run_task"},
            outcome={"success": True},
        )

        result = learning.learn(processed["experience"])

        self.assertTrue(result["success"])
        self.assertTrue(result["evaluation"]["success"])
        self.assertIsNotNone(result["knowledge"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["knowledge"]["status"], "CANDIDATE")
        self.assertEqual(result["knowledge"]["subject"], "python")
        self.assertEqual(result["knowledge"]["predicate"], "used_for")
        self.assertEqual(result["knowledge"]["value"], "automation")
        self.assertEqual(builder.accepted_count, 0)

    def test_failed_experience_does_not_create_knowledge_candidate(self):
        experience_engine, learning, builder = self._build_learning_stack()

        processed = experience_engine.process(
            event_type="TASK_FAILED",
            context={"subject": "task", "predicate": "status", "value": "failed"},
            action={"name": "run_task"},
            outcome={"success": False, "error": "execution failed"},
        )

        result = learning.learn(processed["experience"])

        self.assertTrue(result["success"])
        self.assertFalse(result["evaluation"]["success"])
        self.assertIsNone(result["knowledge"])
        self.assertFalse(result["accepted"])
        self.assertEqual(builder.built_count, 0)

    def test_explicit_acceptance_is_the_only_semantic_memory_handoff(self):
        class MemorySpy:
            def __init__(self):
                self.calls = []

            def remember_knowledge(self, **kwargs):
                self.calls.append(kwargs)

                class Knowledge:
                    knowledge_id = "semantic-1"

                    def to_dict(self):
                        return {"knowledge_id": self.knowledge_id}

                return Knowledge()

        memory = MemorySpy()
        experience_engine = ExperienceEngine()
        evaluator = SelfEvaluator()
        builder = KnowledgeBuilder(memory_manager=memory)
        learning = LearningCoordinator(
            evaluator=evaluator,
            knowledge_builder=builder,
            memory_manager=memory,
        )

        processed = experience_engine.process(
            event_type="TASK_COMPLETED",
            context={"subject": "python", "predicate": "used_for", "value": "automation"},
            action={"name": "run_task"},
            outcome={"success": True},
        )

        result = learning.learn(processed["experience"])

        self.assertIsNotNone(result["knowledge"])
        self.assertFalse(result["accepted"])
        self.assertEqual(memory.calls, [])

        accepted = learning.accept_knowledge(result["knowledge"]["id"])

        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(len(memory.calls), 1)
        self.assertEqual(memory.calls[0]["subject"], "python")
        self.assertEqual(memory.calls[0]["predicate"], "used_for")
        self.assertEqual(memory.calls[0]["value"], "automation")


if __name__ == "__main__":
    unittest.main()
