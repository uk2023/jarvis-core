import unittest

from core.learning.learning_coordinator import LearningCoordinator
from core.skills.skill_learner import SkillLearner
from core.skills.skill_registry import SkillRegistry


class SkillActivationBoundaryTests(unittest.TestCase):
    def _coordinator_with_proposal(self):
        learner = SkillLearner(min_repetitions=3, min_success_rate=0.8)
        registry = SkillRegistry()
        coordinator = LearningCoordinator(skill_learner=learner, skill_registry=registry)
        experience = {
            "action": {"skill": "calculate_total"},
            "outcome": {"success": True, "detail": "calculated"},
            "context": {"goal": "calculate a total"},
        }
        for _ in range(3):
            learner.observe(experience)
        return coordinator, learner, registry

    def test_unapproved_proposal_cannot_activate_or_register(self):
        coordinator, learner, registry = self._coordinator_with_proposal()
        name = "skill_calculate_total"

        with self.assertRaises(PermissionError):
            coordinator.activate_skill_proposal(name, lambda: 42)

        self.assertFalse(registry.is_registered(name))
        self.assertEqual(learner.list_proposals()[0]["status"], "proposed")

    def test_only_explicitly_approved_proposal_can_register_handler(self):
        coordinator, learner, registry = self._coordinator_with_proposal()
        name = "skill_calculate_total"

        approved = coordinator.approve_skill_proposal(name)
        self.assertEqual(approved["status"], "approved")
        self.assertFalse(registry.is_registered(name))

        handler = lambda value=40: value + 2
        result = coordinator.activate_skill_proposal(name, handler)

        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["proposal"]["status"], "registered")
        self.assertTrue(registry.is_registered(name))
        self.assertEqual(registry.get(name)(40), 42)
        self.assertEqual(registry.metadata[name]["source"], "learned")
        self.assertEqual(learner.list_proposals("registered")[0]["name"], name)

    def test_registry_rejects_direct_unapproved_learned_registration(self):
        registry = SkillRegistry()
        proposal = {"name": "skill_forbidden", "status": "proposed"}

        with self.assertRaises(PermissionError):
            registry.register_approved(proposal, lambda: None)

        self.assertFalse(registry.is_registered("skill_forbidden"))


if __name__ == "__main__":
    unittest.main()
