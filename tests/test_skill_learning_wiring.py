import unittest

from core.learning.learning_coordinator import LearningCoordinator
from core.skills.skill_learner import SkillLearner
from core.skills.skill_registry import SkillRegistry
from core.organism.bootstrap import create_jarvis


class SkillLearningWiringTests(unittest.TestCase):
    def test_learning_coordinator_receives_organism_skill_components(self):
        jarvis = create_jarvis()
        learning = jarvis.get_organ("learning")
        learner = jarvis.get_organ("skill_learner")
        registry = jarvis.get_organ("skill_registry")

        self.assertIs(learning.skill_learner, learner)
        self.assertIs(learning.skill_registry, registry)
        self.assertEqual(learner.list_proposals(), [])
        self.assertEqual(registry.skills, {})

    def test_verified_repeated_successes_generate_a_stored_proposal(self):
        class Evaluator:
            def evaluate(self, experience):
                return {"accepted": True, "success": True}

        learner = SkillLearner(min_repetitions=3, min_success_rate=0.8)
        coordinator = LearningCoordinator(evaluator=Evaluator(), skill_learner=learner)

        experience = {
            "action": {"skill": "open_app"},
            "outcome": {"success": True, "detail": "opened"},
            "context": {"goal": "launch application"},
        }
        for _ in range(3):
            result = coordinator.learn(experience)

        self.assertEqual(len(result["skill_proposals"]), 1)
        proposal = result["skill_proposals"][0]
        self.assertEqual(proposal["name"], "skill_open_app")
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["repetitions"], 3)
        self.assertEqual(learner.list_proposals("proposed")[0]["name"], "skill_open_app")
        self.assertEqual(coordinator.skill_proposal_count, 1)


if __name__ == "__main__":
    unittest.main()
