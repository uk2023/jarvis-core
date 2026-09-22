import numpy as np

from ..runtime.memory_limits import apply_process_limits, low_memory_session_options, memory_guard
apply_process_limits()   # must run before onnxruntime import -- see memory_limits.py

import onnxruntime as ort
from tokenizers import Tokenizer


class FastONNXEmbedder:

  def __init__(
      self,
      model_path="all-MiniLM-L6-v2.onnx",
      tokenizer_path="tokenizer.json",
  ):
    # THE CRASH (fixed 2026-09-14). This constructor had NO
    # SessionOptions at all -- default thread-per-core and the CPU
    # memory arena left on, which pre-allocates a large pool up front.
    # UK's own resource samples showed RSS jump from 172MB to 1897MB in
    # under 15 seconds with only 789MB free on the device -- that is
    # this constructor being called with Android's low-memory killer
    # sitting right there. The model itself is ~45MB; the rest was
    # arena pre-allocation this file never asked ORT to skip.
    self.session = ort.InferenceSession(
        model_path,
        sess_options=low_memory_session_options(ort),
        providers=["CPUExecutionProvider"],
    )
    self.tokenizer = Tokenizer.from_file(tokenizer_path)
    self.tokenizer.enable_padding(
        length=128, pad_id=0, pad_token="[PAD]"
    )
    self.tokenizer.enable_truncation(max_length=128)

  def encode(self, text: str) -> np.ndarray:
    # A second line of defence: refuse rather than allocate when the
    # device is already tight. A degraded turn (fall back to keyword
    # match) is recoverable; a SIGKILL is not.
    if not memory_guard("onnx_embedder.encode"):
        return np.zeros(384, dtype=np.float32)
    encoded = self.tokenizer.encode(text)
    input_ids = np.array([encoded.ids], dtype=np.int64)
    attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
    token_type_ids = np.array([encoded.type_ids], dtype=np.int64)

    inputs = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    }

    outputs = self.session.run(None, inputs)
    # Mean Pooling for Sentence Embeddings
    embeddings = outputs[0]  # shape: (1, seq_len, 384)
    mask_expanded = np.expand_dims(attention_mask, -1)
    sum_embeddings = np.sum(embeddings * mask_expanded, axis=1)
    sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
    vector = sum_embeddings / sum_mask

    # Normalize vector for Cosine Similarity
    norm = np.linalg.norm(vector, axis=1, keepdims=True)
    return (vector / norm).astype("float32").flatten()
