from __future__ import annotations

"""SLM tier (blueprint sections 8, 61 -- LEVEL 4/5 of the escalation
cascade): a local, cheap, bounded semantic accelerator that sits
between native rules and the full LLM.

LOCKED model choice (config/models.json, "slm" section): a dedicated,
separate model from the Offline_LLM fallback -- currently
qwen2.5-0.5b-instruct-q4_k_m.gguf at models/SLM/, chosen specifically
for speed: on real-device benchmarks this class of model runs roughly
2x the tokens/sec of the 1.5B Offline_LLM model, and this tier only
ever needs a ~10-token answer, not a full response, so that speed
difference is the whole point.

What this module adds is a narrow JOB matching the blueprint's SLM
responsibilities list (ambiguity resolution, semantic classification,
query rewriting) -- not full synthesis:

    try_classify_predicate() -- given an unrecognized recall phrase
    ("zodiac sign") and the list of predicates native recall already
    knows about, ask the SLM ONLY (never the cloud/full LLM, never
    even the Offline_LLM fallback model) a strict, single-word
    classification question. This is a ~10-token answer, not a
    generated paragraph -- cheap, bounded,
    and exactly the kind of "too flexible for regex, too small for a
    full LLM call" problem the blueprint describes SLM existing for.

Whether this activates at all depends entirely on whether a local
GGUF model file is actually present in models/SLM/ on this device --
if none is configured, every function here returns None immediately
and the existing native-recall / LLM-fallback cascade behaves exactly
as it did before this module existed. This is deliberately NOT wired to
ever call the cloud/network LLM path -- an SLM tier that quietly used
network calls would not be a local, cheap, offline-friendly layer at
all, it would just be the LLM tier with an extra step.

LOCKED model choice (config/models.json, "slm" section): a separate,
smaller model from the Offline_LLM fallback -- get_slm_engine() (see
llm_bridge.py) loads models/SLM/, never models/Offline_LLM/. These are
two distinct engine instances serving two distinct jobs.
"""

from typing import Any, List, Optional


def try_classify_predicate(llm_bridge: Any, unresolved_phrase: str, known_predicates: List[str]) -> Optional[str]:
    """Ask the SLM (never the Offline_LLM fallback, never the cloud
    LLM) whether an unresolved recall phrase is a synonym/close match
    for one of the already-known predicates. Returns the matching
    predicate name, or None (no match, or no SLM model configured, or
    anything went wrong -- always fails safe into "let the normal
    cascade continue").
    """
    if llm_bridge is None or not unresolved_phrase or not known_predicates:
        return None
    get_slm = getattr(llm_bridge, "get_slm_engine", None)
    if not callable(get_slm):
        return None
    try:
        engine = get_slm()
    except Exception:
        # No SLM model file configured at models/SLM/, or it failed to
        # load -- this is the expected, common case on a device that
        # hasn't set one up. Fail silently into "SLM tier not available".
        return None
    if engine is None:
        return None

    categories = ", ".join(sorted(set(known_predicates)))
    prompt = (
        f"Known categories: {categories}\n"
        f'Phrase: "{unresolved_phrase}"\n'
        "Is this phrase a synonym or close match for EXACTLY ONE of the "
        "known categories? Reply with ONLY that one category word, or "
        "reply NONE if it doesn't match any of them."
    )
    try:
        raw = engine.generate(
            system_prompt="You are a strict classifier. Reply with exactly one word: a category name, or NONE.",
            user_input=prompt,
            max_tokens=8,
            temperature=0.0,
        )
    except Exception:
        return None

    answer = str(raw or "").strip().split()[0].lower().strip(".,!?\"'") if raw else ""
    return answer if answer in {p.lower() for p in known_predicates} else None
