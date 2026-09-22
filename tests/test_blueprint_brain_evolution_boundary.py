import unittest

from core.orchestration.blueprint_brain import BlueprintBrain


class _Experience:
    def process(self, **kwargs):
        return {
            "experience": {
                "event_type": kwargs["event_type"],
                "context": kwargs["context"],
                "action": kwargs["action"],
                "outcome": kwargs["outcome"],
            },
            "episode_id": "episode-test",
        }


class _Learning:
    def learn(self, experience, auto_accept=True):
        return {
            "success": True,
            "experience": experience,
            "evaluation": {
                "success": True,
                "score": 1.0,
                "errors": [],
                "strengths": ["SUCCESSFUL_OUTCOME"],
                "evolution_signal": True,
                "evolution_target": "response_routing",
            },
            "knowledge": {"id": "knowledge-test", "content": "test principle"},
            "accepted": True,
        }


class _Evolution:
    def __init__(self):
        self.calls = []

    def propose(self, evaluation, target, reason=None):
        proposal = {
            "id": "proposal-test",
            "status": "PROPOSED",
            "target": target,
            "reason": reason or "test",
        }
        self.calls.append((evaluation, target, reason))
        return proposal


class BlueprintBrainEvolutionBoundaryTests(unittest.TestCase):
    def test_self_evaluation_reaches_controlled_evolution_boundary(self):
        evolution = _Evolution()
        brain = BlueprintBrain(
            experience_engine=_Experience(),
            learning_coordinator=_Learning(),
            evolution_engine=evolution,
            memory_manager=None,
            semantic_understanding=object(),
        )

        result = brain.process_experience(
            event_type="USER_CHAT",
            context={"user_input": "test"},
            action={"mode": "native"},
            outcome={"response": "ok"},
        )

        self.assertEqual(len(evolution.calls), 1)
        self.assertEqual(evolution.calls[0][1], "response_routing")
        self.assertEqual(brain.last_contracts["evolution.input"]["evolution_proposal"]["id"], "proposal-test")
        self.assertEqual(brain.last_contracts["evolution.output"]["change_record"]["applied"], False)
        self.assertEqual(result["evolution"]["proposal"]["status"], "PROPOSED")


if __name__ == "__main__":
    unittest.main()
