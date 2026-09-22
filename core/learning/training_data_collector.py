from __future__ import annotations

"""Training data collection for a FUTURE locally-trained extraction
model (the goal: "JARVIS khud apne kaam ke liye model banaye aur use
train kare LLM se seekh ke" -- JARVIS should build and train its own
model, learning from the LLM).

READ THIS BEFORE ASSUMING THIS MODULE TRAINS ANYTHING -- IT DOES NOT.

Training a real model -- even a small one -- needs a labeled dataset
FIRST. You cannot skip straight to "self-training" with no data to
train on. This module is that missing first ingredient: every time
extraction succeeds (whether via native regex/rules OR via LLM
fallback), the (input_text, extracted_structure, source) triple gets
logged as one training example, to a plain JSONL file that a future
training pipeline can actually consume.

WHY THE EXISTING REGEX/NATIVE LAYER IS NOT BEING DELETED RIGHT NOW,
EVEN THOUGH THE GOAL IS TO EVENTUALLY REPLACE IT:

    "Remove all regex/hardcoding" and "use LLM only as the last
    resort" are two goals that directly conflict UNLESS something
    else provides the native, zero-LLM-cost understanding layer in
    between -- and that "something else" is exactly the trained model
    this data collection is step one toward. Deleting the regex layer
    NOW, before any trained replacement exists, would not make JARVIS
    "more self-evolving" -- it would mean EVERY understanding task
    falls through to the LLM (the opposite of "LLM as last resort"),
    or fails outright with nothing to extract at all. The correct
    sequence is: (1) collect real labeled data from what already
    works (this module), (2) train and evaluate a small model against
    it, (3) only swap the trained model in where it genuinely
    outperforms the existing regex layer -- not before.

WHY "JUST TRAIN IT NOW" ISN'T A ONE-SESSION TASK, STATED PLAINLY:

    Training (not just running/inferencing) a neural network needs
    meaningfully more compute and memory than inference does, even
    for a genuinely small model -- this is a much harder ask on a
    phone-class ARM CPU with no GPU than the pure-inference 0.5B/1.5B
    GGUF models already chosen for the SLM/Offline_LLM tiers. Before
    any training can happen at all, someone has to: pick a model
    architecture small enough to realistically train on this
    hardware, verify a training framework actually installs and runs
    in Termux/PRoot (this is a genuine open question, not a given),
    and only then run and evaluate training against real collected
    data. That is realistically multiple dedicated sessions of ML
    engineering work, not something a single code change can deliver.
    This module's honest job is to make sure that when that work
    happens, it has real data to start from instead of nothing.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

_DEFAULT_PATH = os.path.join("database", "training_examples.jsonl")


class TrainingDataCollector:
    """Appends one JSON line per successful extraction. Deliberately
    minimal -- a flat, append-only JSONL file is the most portable,
    inspectable format for a future training script to read, and
    needs no new dependency to write."""

    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = path
        self._write_count = 0

    def record_example(
        self,
        *,
        input_text: str,
        relations: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        source: str,
        confidence: float,
    ) -> None:
        """Log one (input, extracted structure) pair. Silently no-ops
        on any I/O failure -- collecting training data must never be
        able to break the actual conversation turn it's observing."""
        if not input_text or not str(input_text).strip():
            return
        # Only relations/entities that genuinely came from SOMEWHERE
        # (native rules or LLM fallback both count -- both are real,
        # validated extraction, not a guess) are worth a future model
        # learning to reproduce. An empty result is only useful
        # training signal if we're confident nothing SHOULD have been
        # extracted, which native's confident negative already implies
        # for greetings/questions -- so those get logged too, as
        # negative examples, not skipped.
        record = {
            "timestamp": time.time(),
            "input_text": str(input_text),
            "relations": relations or [],
            "entities": entities or [],
            "source": source,
            "confidence": float(confidence or 0.0),
        }
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._write_count += 1
        except Exception:
            pass

    def example_count(self) -> int:
        """Real count of examples written THIS process lifetime (not
        a re-read of the file, to stay cheap enough to call every
        turn) -- see stats() for the true on-disk total."""
        return self._write_count

    def stats(self) -> Dict[str, Any]:
        """Real on-disk totals, read fresh -- how much data actually
        exists for a future training pipeline to use, broken down by
        which mechanism produced each example (native vs LLM
        fallback), since that split is itself useful: it shows how
        often native rules already suffice vs how often the LLM is
        still doing the understanding work a trained model would
        eventually take over."""
        counts: Dict[str, int] = {}
        total = 0
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        total += 1
                        src = str(row.get("source", "unknown"))
                        counts[src] = counts.get(src, 0) + 1
            except Exception:
                pass
        return {"total_examples": total, "by_source": counts, "path": self.path}


_singleton: Optional[TrainingDataCollector] = None


def get_training_data_collector() -> TrainingDataCollector:
    global _singleton
    if _singleton is None:
        _singleton = TrainingDataCollector()
    return _singleton
