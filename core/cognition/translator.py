from __future__ import annotations

"""The Translator layer (blueprint Section T, JARVIS_Workflow_v7_Translator.txt).

Normalizes whatever UK types -- typos, spelling variants, gender
variants (mera/meri/mere) -- into a canonical form BEFORE semantic
understanding's regex ever runs, so extraction only ever has to
handle ONE spelling of each concept instead of an open-ended list of
variants. This is what turns the mera/meri, naam/Name, fast-food/
full-name class of bug (each found and patched individually earlier
this project) into something structurally handled, not something
that needs a new patch every time a new variant appears.

TWO STAGES IMPLEMENTED HERE, BOTH ZERO LLM COST:

    STAGE 1 -- exact dictionary lookup (extends brain.py's existing
    typo_map with category-indicator words, common Hinglish function
    words, and relationship words -- the same vocabulary semantic
    understanding's extraction already depends on knowing).

    STAGE 2 -- fuzzy match (Python's own difflib.get_close_matches,
    zero new dependency) against the SAME canonical vocabulary --
    catches typos that were NEVER explicitly added to the dictionary,
    as long as they're close enough to something already known.
    Verified before writing this: 'favoutite'->'favourite',
    'faviurite'->'favourite', 'grilfriend'->'girlfriend',
    'hobbie'->'hobby', 'namee'->'name', 'codeing'->'coding' --
    six different, never-explicitly-added typos, all six caught.

STAGE 3 (LLM, last resort, self-erasing cost) is NOT implemented in
this module -- it is semantic understanding's EXISTING llm_fallback
(core/orchestration/blueprint_brain.py), reached only when Stage 1
and Stage 2 here both fail to produce a confident native extraction.
This module's job ends at "give extraction the cleanest input
possible without ever calling the LLM for it."
"""

import difflib
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

# The canonical vocabulary Stage 1/Stage 2 both normalize TOWARD.
# Deliberately the SAME words semantic understanding's own extraction
# code already depends on recognizing (category-indicator words,
# common Hinglish function words, relationship words) -- normalizing
# toward a vocabulary nothing downstream expects would just move the
# mismatch one layer earlier instead of removing it.
CANONICAL_VOCABULARY = frozenset({
    "mera", "meri", "mere", "favourite", "favorite", "fav", "hai", "naam",
    "name", "hobby", "hobbies", "sport", "sports", "coding", "programming",
    "language", "color", "colour", "movie", "movies", "song", "songs",
    "team", "game", "games", "show", "genre", "actor", "actress", "book",
    "books", "place", "destination", "car", "bike", "phone", "brand",
    "pet", "friend", "girlfriend", "boyfriend", "job", "profession",
    "city", "country", "subject", "dish", "cuisine", "number", "email",
    "address", "fast", "food", "full", "nick", "nickname", "middle",
    "last", "first", "aur", "kya", "kaun", "kaha", "kahan", "kab", "kyun",
    "kaise", "kitna", "kitni", "tumhara", "tumhari", "aapka", "aapki",
    "aapke", "aap", "tum", "hum", "theek", "thik", "accha", "achha",
    "nahi", "haan", "chahiye", "batao", "bataye", "samjha", "samjhna",
    "karna", "banana", "khatam", "shuru", "bhejna", "lena", "dena",
    "jaana", "aana", "milna", "dekhna", "sunna", "padhna", "likhna",
})

# Stage 1: exact dictionary. Deliberately includes the SAME entries
# as brain.py's typo_map (core/orchestration/brain.py) -- kept as a
# static, independent copy here rather than reflectively reaching
# into Brain's __init__ (which builds this dict inline, not via a
# separate loadable method), plus additional variants observed
# specifically around the canonical vocabulary above.
_EXACT_CORRECTIONS: Dict[str, str] = {
    "chahie": "chahiye", "chahia": "chahiye", "chaiye": "chahiye",
    "krde": "kar de", "krdo": "kar do", "krna": "karna",
    "nhi": "nahi", "mje": "mujhe", "mjhe": "mujhe", "mai": "main", "mein": "main",
    "yhi": "yahi", "yha": "yahan", "wha": "wahan",
    "smjha": "samjha", "smjhna": "samjhna",
    "bta": "bata", "btao": "batao",
    "thik": "theek", "thk": "theek", "acha": "accha", "achha": "accha",
    "rha": "raha", "rhi": "rahi", "rhe": "rahe",
    "kese": "kaise", "kse": "kaise",
    "tmhe": "tumhe", "tmhara": "tumhara", "tm": "tum",
    "hye": "hey", "nam": "naam", "onnly": "only",
    "gielfriend": "girlfriend", "girlfrien": "girlfriend", "grilfriend": "girlfriend",
    "nahu": "nahi", "crator": "creator",
    "tunhe": "tumhe", "tunhara": "tumhara", "tunhari": "tumhari",
    "muje": "mujhe", "mujje": "mujhe", "insoect": "inspect",
    "favoutite": "favourite", "faviurite": "favourite", "favrate": "favourite",
    "namee": "naam", "hobbie": "hobby", "hobbys": "hobbies",
    "codeing": "coding", "collor": "color", "colur": "colour",
    "kys": "kya", "kya": "kya",
}


def normalize(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Stage 1 (exact) + Stage 2 (fuzzy) normalization. Returns
    (normalized_text, corrections) where corrections is a list of
    {"original": ..., "corrected": ..., "stage": "exact"|"fuzzy"}
    for whatever actually changed -- empty list if nothing did."""
    if not text or not text.strip():
        return text, []

    corrections: List[Dict[str, str]] = []
    words = text.split()
    output_words: List[str] = []

    for word in words:
        # Preserve surrounding punctuation; normalize the bare word.
        prefix_match = re.match(r"^[^\w]*", word)
        suffix_match = re.search(r"[^\w]*$", word)
        prefix = prefix_match.group(0) if prefix_match else ""
        suffix = suffix_match.group(0) if suffix_match else ""
        core = word[len(prefix): len(word) - len(suffix)] if suffix else word[len(prefix):]
        if not core:
            output_words.append(word)
            continue

        lowered = core.lower()

        # Stage 1: exact dictionary (case-preserving on output shape
        # not attempted here -- normalized text feeds extraction only,
        # never shown to the user, so lowercase-canonical is fine).
        if lowered in _EXACT_CORRECTIONS:
            corrected = _EXACT_CORRECTIONS[lowered]
            corrections.append({"original": core, "corrected": corrected, "stage": "exact"})
            output_words.append(prefix + corrected + suffix)
            continue
        if lowered in CANONICAL_VOCABULARY:
            output_words.append(word)  # already canonical, nothing to do
            continue

        # Stage 2: fuzzy match against the canonical vocabulary --
        # catches typos never explicitly added to Stage 1's dictionary.
        # min length 6 + cutoff=0.85 chosen from real measurements: a
        # genuine bug was caught while testing this -- "like" (correct,
        # unrelated English) fuzzy-matched to "bike" (in the
        # vocabulary) at a 0.75 ratio and a 4-char minimum, silently
        # corrupting perfectly correct text. Genuine typos measured
        # much higher (favortite/favorite=0.94, grilfriend/girlfriend
        # =0.90) and are virtually always 6+ characters -- this
        # threshold keeps those while excluding the short, common-word
        # collision risk that caused the false positive.
        if len(lowered) >= 6:
            match = difflib.get_close_matches(lowered, CANONICAL_VOCABULARY, n=1, cutoff=0.85)
            if match:
                corrections.append({"original": core, "corrected": match[0], "stage": "fuzzy"})
                output_words.append(prefix + match[0] + suffix)
                continue

        output_words.append(word)

    return " ".join(output_words), corrections


def learn_correction(original: str, corrected: str, memory: object = None) -> None:
    """Stage 3's other half: when the LLM (semantic understanding's
    existing llm_fallback, or now Gemini -- see Section G below)
    successfully resolves something Stage 1/2 here could not, the
    specific correction gets written back into Stage 1's dictionary
    so the SAME gap never costs an API call again. UK's explicit ask:
    this should be PERSONALIZED and PERSISTENT -- UK's own specific
    typos/speaking style, learned over time, not lost on restart. If
    `memory` (the semantic memory organ) is provided, the correction
    is also persisted durably (SYSTEM namespace, same pattern as every
    other piece of self-knowledge this session) so it survives
    restarts; without it, this still works process-lifetime only."""
    key = str(original or "").strip().lower()
    value = str(corrected or "").strip().lower()
    if not key or not value or key == value:
        return
    _EXACT_CORRECTIONS[key] = value
    semantic = getattr(memory, "semantic", memory) if memory is not None else None
    if semantic is not None and hasattr(semantic, "remember"):
        try:
            semantic.remember(
                subject="jarvis_self", predicate=f"personal_correction_{key}", value=value,
                confidence=1.0, importance=0.4, source="personalized_typo_learning",
                tags=["identity", "translator", "personal_correction"], namespace="SYSTEM",
            )
        except Exception:
            pass


def load_personal_corrections(memory: object) -> int:
    """Load UK's own previously-learned corrections back into Stage 1
    on boot -- the actual persistence half of the feature above.
    Returns how many were loaded (0 if memory is unavailable or this
    is genuinely the first-ever boot)."""
    semantic = getattr(memory, "semantic", memory) if memory is not None else None
    if semantic is None or not hasattr(semantic, "find"):
        return 0
    loaded = 0
    try:
        for item in semantic.find(subject="jarvis_self") or []:
            predicate = str(getattr(item, "predicate", "") or "")
            if not predicate.startswith("personal_correction_"):
                continue
            key = predicate[len("personal_correction_"):]
            value = getattr(item, "value", None)
            if key and value:
                _EXACT_CORRECTIONS[key] = str(value)
                loaded += 1
    except Exception:
        pass
    return loaded


# Personal idiolect model (UK's explicit ask, recall/learning/memory
# proposal #1): fuzzy (Stage 2) corrections are, by definition, things
# Stage 1's dictionary did NOT already know -- but if the SAME
# (original, corrected) pair keeps happening, that is not noise, it
# is UK's own recurring spelling habit. Track occurrences and
# automatically promote a pair into Stage 1 (via learn_correction,
# which also persists it) once it repeats often enough that it's
# clearly a pattern and not a one-off fuzzy-match coincidence.
_FUZZY_PROMOTION_THRESHOLD = 3
_fuzzy_occurrence_counts: Dict[Tuple[str, str], int] = defaultdict(int)


def record_and_maybe_promote(corrections: List[Dict[str, str]], memory: object = None) -> List[str]:
    """Call once per turn with normalize()'s own `corrections` list
    (from THIS turn). Returns the list of original words newly
    promoted to a permanent personal correction this call (usually
    empty -- most calls just increment a counter one step closer to
    the threshold)."""
    promoted: List[str] = []
    for correction in corrections or []:
        if correction.get("stage") != "fuzzy":
            continue
        original = str(correction.get("original", "")).lower().strip()
        corrected = str(correction.get("corrected", "")).lower().strip()
        if not original or not corrected:
            continue
        key = (original, corrected)
        _fuzzy_occurrence_counts[key] += 1
        if _fuzzy_occurrence_counts[key] == _FUZZY_PROMOTION_THRESHOLD:
            learn_correction(original, corrected, memory=memory)
            promoted.append(original)
    return promoted


def idiolect_status() -> Dict[str, Any]:
    """Visibility for monitor.py -- how many personal corrections
    have actually been learned/promoted, and what's currently being
    tracked but hasn't crossed the promotion threshold yet."""
    close_to_promotion = [
        {"original": pair[0], "corrected": pair[1], "count": count}
        for pair, count in _fuzzy_occurrence_counts.items()
        if count < _FUZZY_PROMOTION_THRESHOLD
    ]
    close_to_promotion.sort(key=lambda entry: entry["count"], reverse=True)
    return {
        "learned_corrections_count": len(_EXACT_CORRECTIONS),
        "promotion_threshold": _FUZZY_PROMOTION_THRESHOLD,
        "tracked_pending_pairs": len(_fuzzy_occurrence_counts),
        "closest_to_learning": close_to_promotion[:5],
    }

