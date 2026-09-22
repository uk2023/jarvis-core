import unittest

from core.cognition.semantic_understanding.engine import SemanticUnderstandingEngine


class SemanticUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.engine = SemanticUnderstandingEngine()

    def test_hinglish_relation_name_fact(self):
        result = self.engine.understand("mera ex ka nan Devyana hai")
        facts = result["fact_candidates"]
        self.assertTrue(facts)
        self.assertEqual(facts[0]["subject"], "ex")
        self.assertEqual(facts[0]["predicate"], "name")
        self.assertEqual(facts[0]["value"], "Devyana")

    def test_english_name_fact(self):
        result = self.engine.understand("my name is Ujjwal")
        self.assertEqual(result["fact_candidates"][0]["subject"], "user")
        self.assertEqual(result["fact_candidates"][0]["predicate"], "name")
        self.assertEqual(result["fact_candidates"][0]["value"], "Ujjwal")

    def test_preference(self):
        result = self.engine.understand("mujhe offline AI pasand hai")
        self.assertEqual(result["fact_candidates"][0]["predicate"], "likes")
        self.assertEqual(result["fact_candidates"][0]["value"], "offline AI")

    def test_no_external_knowledge_is_invented(self):
        result = self.engine.understand("kal weather kaisa hoga")
        self.assertEqual(result["fact_candidates"], [])

    def test_normalization(self):
        result = self.engine.understand("mera nan Ujjwal hai")
        self.assertEqual(result["normalized"], "mera naam Ujjwal hai")


if __name__ == "__main__":
    unittest.main()
