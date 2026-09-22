import unittest

from core.learning.learning_coordinator import LearningCoordinator


class _Evaluator:
    def __init__(self):
        self.calls = []

    def evaluate(self, experience):
        self.calls.append(experience)
        return {
            "type": "SELF_EVALUATION",
            "success": True,
            "score": 0.9,
            "errors": [],
            "strengths": ["ACTION_WAS_EXECUTED"],
            "feedback": {
                "quality": "GOOD",
                "score": 0.9,
                "success": True,
                "errors": [],
                "strengths": ["ACTION_WAS_EXECUTED"],
            },
        }


class _KnowledgeBuilder:
    def __init__(self):
        self.calls = []

    def build(self, experience, evaluation):
        self.calls.append((experience, evaluation))
        return {
            "id": "candidate-1",
            "status": "CANDIDATE",
            "source_evaluation": evaluation,
        }

    def accept(self, knowledge_id):
        return {"id": knowledge_id, "status": "ACCEPTED"}


class LearningSelfEvaluationContractTests(unittest.TestCase):
    def test_learning_routes_experience_through_self_evaluator_before_knowledge(self):
        evaluator = _Evaluator()
        builder = _KnowledgeBuilder()
        coordinator = LearningCoordinator(
            evaluator=evaluator,
            knowledge_builder=builder,
        )

        experience = {
            "event_type": "NATIVE_ACTION_COMPLETED",
            "action": {"name": "ping"},
            "outcome": {"success": True},
            "success": True,
        }

        result = coordinator.learn(experience)

        self.assertEqual(evaluator.calls, [experience])
        self.assertEqual(len(builder.calls), 1)
        self.assertIs(builder.calls[0][0], experience)
        self.assertIs(builder.calls[0][1], result["evaluation"])
        self.assertEqual(result["evaluation"]["type"], "SELF_EVALUATION")
        self.assertEqual(result["evaluation"]["score"], 0.9)
        self.assertEqual(result["knowledge"]["source_evaluation"], result["evaluation"])
        self.assertFalse(result["accepted"])

    def test_learning_cannot_skip_self_evaluator(self):
        coordinator = LearningCoordinator(
            evaluator=None,
            knowledge_builder=_KnowledgeBuilder(),
        )

        with self.assertRaisesRegex(RuntimeError, "SelfEvaluator is not connected"):
            coordinator.learn({
                "event_type": "NATIVE_ACTION_COMPLETED",
                "outcome": {"success": True},
                "success": True,
            })


if __name__ == "__main__":
    unittest.main()
