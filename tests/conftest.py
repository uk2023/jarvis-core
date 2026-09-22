import numpy as np
import pytest


@pytest.fixture(autouse=True)
def mock_embedder(monkeypatch):
    """Use a lightweight fake ONNX embedder for tests."""

    class FakeEmbedder:
        def get_embedding_dimension(self):
            return 384

        def get_sentence_embedding_dimension(self):
            return self.get_embedding_dimension()

        def encode(self, sentences, **kwargs):
            if isinstance(sentences, str):
                sentences = [sentences]
            return np.zeros((len(sentences), 384), dtype=np.float32)

    monkeypatch.setattr(
        "core.memory.semantic_memory.FastONNXEmbedder",
        lambda *args, **kwargs: FakeEmbedder(),
    )
