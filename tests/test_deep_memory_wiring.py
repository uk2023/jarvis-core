import tempfile
import unittest
from pathlib import Path

from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator
from core.learning.self_evaluator import SelfEvaluator
from core.memory.memory_manager import MemoryManager
from core.memory.semantic_memory import SemanticMemory
from database.sqlite_store import SQLiteStore


class DeepMemoryWiringTests(unittest.TestCase):
    """Verify learning reaches durable semantic/episodic memory and survives restart."""

    def _memory(self, root: Path):
        db_path = root / "jarvis.db"
        faiss_path = root / "jarvis_faiss.index"
        semantic = SemanticMemory(
            db_path=str(db_path),
            faiss_index_path=str(faiss_path),
        )
        store = SQLiteStore(str(db_path))
        return MemoryManager(semantic=semantic, store=store)

    def test_accepted_knowledge_survives_memory_restart_and_context_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = self._memory(root)
            evaluator = SelfEvaluator()
            builder = KnowledgeBuilder(memory_manager=memory)
            learning = LearningCoordinator(
                evaluator=evaluator,
                knowledge_builder=builder,
                memory_manager=memory,
            )

            experience = {
                "event_type": "TASK_COMPLETED",
                "context": {
                    "subject": "jarvis",
                    "predicate": "project_language",
                    "value": "python",
                },
                "action": {"name": "build_feature"},
                "outcome": {"success": True},
                "success": True,
            }

            result = learning.learn(experience)
            candidate = result["knowledge"]
            self.assertIsNotNone(candidate)
            self.assertFalse(result["accepted"])

            accepted = learning.accept_knowledge(candidate["id"])
            self.assertEqual(accepted["status"], "ACCEPTED")

            stored = memory.get_knowledge("jarvis", "project_language")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].value, "python")
            self.assertEqual(stored[0].knowledge_id, accepted["semantic_knowledge_id"])

            context = memory.build_context(subject="jarvis")
            self.assertEqual(len(context["relevant_knowledge"]), 1)
            self.assertEqual(context["relevant_knowledge"][0]["value"], "python")
            self.assertTrue(context["graph_relations"])

            memory.close()

            restored = self._memory(root)
            try:
                restored_item = restored.get_knowledge("jarvis", "project_language")
                self.assertEqual(len(restored_item), 1)
                self.assertEqual(restored_item[0].value, "python")
                self.assertEqual(restored_item[0].knowledge_id, accepted["semantic_knowledge_id"])
                self.assertEqual(restored.semantic.faiss_index.ntotal, 1)

                restored_context = restored.build_context(subject="jarvis")
                self.assertEqual(restored_context["relevant_knowledge"][0]["value"], "python")
                self.assertTrue(restored_context["graph_relations"])
            finally:
                restored.close()

    def test_episodic_experience_survives_memory_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = self._memory(root)

            episode = memory.remember_experience(
                event_type="NATIVE_ACTION_COMPLETED",
                context={"subject": "jarvis", "predicate": "last_test", "value": "deep_memory"},
                action={"name": "verify_memory"},
                outcome={"success": True},
                source="test",
            )
            episode_id = episode.episode_id
            memory.close()

            restored = self._memory(root)
            try:
                episodes = restored.find_experiences(event_type="NATIVE_ACTION_COMPLETED")
                self.assertTrue(any(item.episode_id == episode_id for item in episodes))
                self.assertEqual(
                    next(item for item in episodes if item.episode_id == episode_id).outcome["success"],
                    True,
                )
            finally:
                restored.close()


if __name__ == "__main__":
    unittest.main()
