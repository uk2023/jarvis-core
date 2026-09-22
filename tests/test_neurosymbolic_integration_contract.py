import unittest

from core.cognition.semantic_understanding.bridge_to_cognition import SemanticUnderstanding
from core.cognition.semantic_understanding.semantic_retriever import SemanticRetriever


class FakeFact:
    def __init__(self, subject):
        self.subject = subject


class FakeSemanticMemory:
    def __init__(self):
        self.calls = []

    def search(self, query, limit=20):
        self.calls.append(("search", query, limit))
        return [FakeFact("user")]

    def semantic_search(self, query, similarity_threshold=0.70, max_candidate_cap=20):
        self.calls.append(("semantic_search", query, similarity_threshold, max_candidate_cap))
        return [FakeFact("user")]

    def get_graph_relations(self, subject, max_limit=5):
        self.calls.append(("graph", subject, max_limit))
        return [{"subject": subject, "predicate": "name", "target": "Ujjwal"}]


class NeuroSymbolicIntegrationContractTests(unittest.TestCase):
    def test_retriever_delegates_all_persistent_retrieval_to_semantic_memory(self):
        memory = FakeSemanticMemory()
        retriever = SemanticRetriever(semantic_memory=memory)
        result = retriever.retrieve("my name", limit=4)
        self.assertEqual(set(result), {"exact", "vector", "graph"})
        self.assertEqual(len(result["exact"]), 1)
        self.assertEqual(len(result["vector"]), 1)
        self.assertEqual(len(result["graph"]), 1)
        self.assertTrue(any(call[0] == "search" for call in memory.calls))
        self.assertTrue(any(call[0] == "semantic_search" for call in memory.calls))
        self.assertTrue(any(call[0] == "graph" for call in memory.calls))

    def test_bridge_exposes_stable_cognitive_contract(self):
        memory = FakeSemanticMemory()
        bridge = SemanticUnderstanding(semantic_memory=memory)
        result = bridge.understand("my name is Ujjwal")
        self.assertIn("semantic", result)
        self.assertIn("entities", result)
        self.assertIn("relations", result)
        self.assertIn("context", result)
        self.assertIn("evidence", result)
        self.assertEqual(set(result["evidence"]), {"exact", "vector", "graph"})


if __name__ == "__main__":
    unittest.main()
