import unittest

from core.cognition.semantic_understanding.engine import SemanticUnderstandingEngine


class CompleteSemanticUnderstandingFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = SemanticUnderstandingEngine()

    def test_surface_semantics(self):
        result = self.engine.understand("Kya mera naam Ujjwal hai?")
        self.assertEqual(result["language"], "hinglish")
        self.assertEqual(result["intent"]["name"], "question")
        self.assertTrue(result["tokens"])
        self.assertTrue(any(e["text"] == "Ujjwal" for e in result["entities"]))

    def test_contextual_reference_resolution(self):
        first = self.engine.understand("I started learning Python")
        self.assertEqual(first["events"][0]["event_type"], "learning_started")
        second = self.engine.understand("Usme kya seekh raha hoon?")
        self.assertTrue(second["references"])
        self.assertEqual(second["references"][0]["mention"], "usme")
        self.assertIsNotNone(second["references"][0]["resolved_to"])
        self.assertEqual(second["references"][0]["resolved_to"]["text"], "Python")

    def test_event_relation_and_temporal_representation(self):
        result = self.engine.understand("Maine kal Python seekhna start kiya")
        self.assertEqual(result["events"][0]["event_type"], "learning_started")
        self.assertEqual(result["events"][0]["object"], "Python")
        self.assertEqual(result["events"][0]["time"], "kal")
        predicates = {r["predicate"] for r in result["relations"]}
        self.assertIn("learning_started", predicates)
        self.assertIn("occurred_at", predicates)

    def test_reasoning_produces_learning_target(self):
        result = self.engine.understand("I started learning Python")
        inference = next(x for x in result["inferences"] if x["type"] == "current_learning_target")
        self.assertEqual(inference["value"], "Python")
        self.assertGreater(inference["confidence"], 0.0)

    def test_existing_fact_contract_is_preserved(self):
        result = self.engine.understand("mera ex ka naam Devyana hai")
        self.assertEqual(result["fact_candidates"][0]["subject"], "ex")
        self.assertEqual(result["fact_candidates"][0]["predicate"], "name")
        self.assertEqual(result["fact_candidates"][0]["value"], "Devyana")


if __name__ == "__main__":
    unittest.main()
