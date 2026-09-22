import unittest

from core.memory.episodic_memory import Episode


class TestEpisodicMemorySerializationSafety(unittest.TestCase):
    def test_cycle_does_not_recurse_forever(self):
        payload = {}
        payload["self"] = payload
        episode = Episode(
            episode_id="cycle",
            timestamp=0.0,
            event_type="TEST",
            context=payload,
            action=None,
            outcome=None,
        )

        result = episode.to_dict()

        self.assertEqual(result["context"]["self"], "<cycle>")

    def test_deep_payload_is_bounded(self):
        payload = current = {}
        for _ in range(2000):
            current["next"] = {}
            current = current["next"]

        episode = Episode(
            episode_id="deep",
            timestamp=0.0,
            event_type="TEST",
            context=payload,
            action=None,
            outcome=None,
        )

        result = episode.to_dict()

        node = result["context"]
        for _ in range(32):
            if not isinstance(node, dict) or "next" not in node:
                break
            node = node["next"]
        self.assertEqual(node, "<max-depth>")

    def test_normal_episode_shape_is_preserved(self):
        episode = Episode(
            episode_id="normal",
            timestamp=1.0,
            event_type="TEST",
            context={"query": "hello", "scores": [1, 2, 3]},
            action={"type": "reply"},
            outcome={"ok": True},
            importance=0.8,
            confidence=0.9,
            source="test",
            tags=["chat"],
        )

        result = episode.to_dict()

        self.assertEqual(result["context"], {"query": "hello", "scores": [1, 2, 3]})
        self.assertEqual(result["action"], {"type": "reply"})
        self.assertEqual(result["outcome"], {"ok": True})
        self.assertEqual(result["tags"], ["chat"])


if __name__ == "__main__":
    unittest.main()
