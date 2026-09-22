from __future__ import annotations

"""Meta-awareness: five native (zero-LLM-cost) resolvers that let UK
ask JARVIS about ITSELF -- its own architecture, its live internal
numbers, what happened on the last turn, whether anything is broken,
and how much to trust its last answer. This is the concrete
implementation of "brain.py se seedhi baat" (talk to brain.py
directly): every function here reads real, retained state (or a
curated, accurate description of real code) -- nothing here is
invented or guessed, matching the existing self_awareness discipline
in response_brief.py.

Each function has the same shape as try_self_awareness_answer:
(user_input, brain) -> Optional[str]. None means "not this resolver's
question" -- the caller falls through to the next one.
"""

import re
import time
import difflib
from typing import Any, Dict, Optional


# =====================================================================
# 1. ARCHITECTURE SELF-DESCRIPTION
# =====================================================================
# Curated, not auto-scraped from docstrings -- an auto-scraper risks
# quoting an internal comment out of context or in English when the
# person is asking in Hinglish. Each entry here is a short, accurate,
# human-facing summary of what that real module actually does, kept
# in sync by hand as the architecture changes.
_ARCHITECTURE_DESCRIPTIONS: Dict[str, str] = {
    "perception": (
        "Perception sabse pehle raw text ko dekhta hai. Pehle deterministic "
        "pattern-match try karta hai (free), agar wo confident nahi hota to "
        "LLM se classify karwata hai, aur agar wo bhi fail ho to ek safe "
        "default return karta hai -- kabhi raw/malformed data aage nahi jaane deta."
    ),
    "semantic_understanding": (
        "Semantic Understanding engine (native, zero-LLM-cost) text se facts "
        "nikalta hai symbolic regex parsing se -- naam, location, favourite, "
        "preference patterns. Sirf jab yeh confident nahi hota tab LLM fallback "
        "call hoti hai."
    ),
    "memory_consolidator": (
        "Idle time mein episodic chat history ko dobara dekhta hai aur jo facts "
        "live turn mein miss ho gaye the, unhe semantic memory mein promote "
        "karta hai. Raw episodic memory ko kabhi touch nahi karta, sirf naya "
        "add karta hai."
    ),
    "native_response_learning": (
        "Trace log se repeated, hamesha-consistent small talk (greeting, "
        "identity, capabilities) seekh kar zero-LLM-cost templates banata hai. "
        "Personal facts (naam, pasand, girlfriend) kabhi nahi seekhta -- "
        "kyunki fact badal sakta hai aur purana cached jawab jhoot ban jayega."
    ),
    "trace_log": (
        "Har turn ka poora raw data -- input, perception, LLM response, "
        "grounding check, budget usage -- ek JSONL file mein forever save "
        "karta hai. Isi data se native_response_learning aur yeh introspection "
        "sab kaam karte hai."
    ),
    "knowledge_builder": (
        "Ek extracted relation ko final semantic-memory fact banane se pehle "
        "reliability check karta hai (score >= 0.5, plausibility gate) -- "
        "har relation seedha trust nahi kiya jaata."
    ),
    "grounding_check": (
        "Har LLM response ke baad check karta hai ki usmein koi naam/number/dawa "
        "aaya jo brief mein diya hi nahi gaya tha. Kabhi response ko block nahi "
        "karta, sirf FLAG karta hai -- taaki hallucination pakadi ja sake."
    ),
    "llm_bridge": (
        "LLM calls ka budget manage karta hai -- 3 levels mein bata hua "
        "(perception+understanding / response / post-response-reasoning), "
        "taaki koi ek layer poora budget khatam na kar de aur baaki starve ho jaye."
    ),
    "idle_loop": (
        "Jab tum busy nahi ho, tab yeh curiosity/goal/planner cycle chalata "
        "hai, aur memory_consolidator + native_response_learning ko bhi "
        "trigger karta hai (~30s cooldown pe)."
    ),
    "native_reasoner": (
        "Mera pehla-check layer -- kisi bhi LLM call se PEHLE yeh try karta hai "
        "ki kya answer already memory/template/graph se free mein mil sakta hai. "
        "Sirf tab LLM tak jaata hai jab yeh sab fail ho jaaye."
    ),
}

_ARCHITECTURE_TRIGGER = re.compile(
    r"\b(?:tumhar[ae]|is|iska)?\s*.{0,25}?"
    r"(?:kya\s+kar(?:ta|te)\s+hai|kaam\s+kya\s+hai|kaise\s+kaam\s+karta\s+hai|"
    r"what\s+does\b.{0,20}\bdo\b)", re.I,
)


def try_architecture_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 150:
        return None
    if not _ARCHITECTURE_TRIGGER.search(text):
        return None
    lowered = text.lower()
    # Alias map so common phrasing/spelling variants all resolve to the
    # same canonical entry above.
    aliases = {
        "perception": "perception",
        "semantic": "semantic_understanding", "semantic understanding": "semantic_understanding",
        "consolidat": "memory_consolidator", "memory consolidator": "memory_consolidator",
        "native response": "native_response_learning", "template": "native_response_learning",
        "trace log": "trace_log", "trace_log": "trace_log",
        "knowledge builder": "knowledge_builder", "knowledge_builder": "knowledge_builder",
        "grounding": "grounding_check", "flagged": "grounding_check",
        "llm bridge": "llm_bridge", "budget": "llm_bridge",
        "idle loop": "idle_loop", "idle_loop": "idle_loop",
        "native reasoner": "native_reasoner", "native_reasoner": "native_reasoner",
    }
    for alias, key in aliases.items():
        if alias in lowered:
            return _ARCHITECTURE_DESCRIPTIONS[key]
    return None


# =====================================================================
# 2. LIVE RUNTIME INTROSPECTION
# =====================================================================

def try_live_status_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 150 or brain is None:
        return None
    lowered = text.lower()

    if re.search(r"\bbudget\s+kitna\s+bach|remaining\s+calls|llm\s+call.{0,10}bache", lowered):
        llm = getattr(brain, "llm", None)
        status = llm.budget_status() if llm is not None and hasattr(llm, "budget_status") else {}
        if not status:
            return "Budget status abhi available nahi hai (LLM bridge attached nahi hai)."
        return (
            f"Is turn mein {status.get('calls', 0)}/{status.get('max_calls', '?')} calls use hui, "
            f"{status.get('remaining_calls', '?')} bachi hai. "
            f"Level-wise usage: {status.get('level_calls', {})}."
        )

    if re.search(r"\btemplate\b.{0,15}(?:seekh|kitne|kya)|native\s+response.{0,15}(?:seekh|status)", lowered):
        learner = getattr(brain, "native_response_learner", None)
        status = learner.status() if learner is not None else {}
        if not status:
            return "Native response learning abhi attached nahi hai."
        return (
            f"Abhi tak {status.get('template_count', 0)} template seekhe hai, "
            f"jo total {status.get('total_hits', 0)} baar LLM call bachane mein use hue. "
            f"Last scan: {(status.get('last_mine_result') or {}).get('candidates_found', 0)} candidates dekhe."
        )

    if re.search(r"\bconsolidat(?:ion|e)\b.{0,20}(?:kya\s+kiya|status|kitna)", lowered):
        consolidator = getattr(brain, "consolidator", None)
        status = consolidator.status() if consolidator is not None else {}
        if not status:
            return "Memory consolidator abhi attached nahi hai."
        last = status.get("last_result") or {}
        return (
            f"Ab tak {status.get('run_count', 0)} baar idle consolidation chali hai. "
            f"Last run mein {last.get('examined', 0)} episodes dekhe, "
            f"{last.get('consolidated', 0)} naye facts semantic memory mein daale."
        )

    if re.search(r"\btrace\s*log\b.{0,20}(?:kitna|kitne|size|data)", lowered):
        try:
            from ..runtime.trace_log import get_trace_log
            status = get_trace_log().status()
        except Exception:
            status = {}
        if not status:
            return "Trace log status abhi available nahi hai."
        return f"Trace log ke {status.get('files', 0)} din ke files hai ({status.get('retention_days', '?')} din tak rakhta hoon)."

    return None


# =====================================================================
# 3. PER-TURN WORKFLOW NARRATOR
# =====================================================================

def _fuzzy_has_any(words: list, vocabulary: frozenset, cutoff: float = 0.72) -> bool:
    """Typo-tolerant vocabulary check (same spirit as Translator's own
    Stage 2 fuzzy match in core/cognition/translator.py, just a
    separate small vocabulary here since these are meta-awareness
    trigger words, not fact-extraction vocabulary). Real production
    evidence: UK typed "resoonse"/"congition"/"workfloe" and the old
    exact-word triggers below silently never fired for any of them --
    JARVIS looked like it was ignoring direct orders when it was
    actually just failing a literal string match on a typo."""
    for word in words:
        if word in vocabulary:
            return True
        if len(word) >= 4 and difflib.get_close_matches(word, vocabulary, n=1, cutoff=cutoff):
            return True
    return False


_META_REFERENCE_WORDS = frozenset({"last", "pichhla", "pichhli", "pehla", "purana"})
_META_SUBJECT_WORDS = frozenset({"response", "turn", "workflow", "schema", "cognition", "data", "pipeline", "trace"})
_META_ACTION_WORDS = frozenset({"dikhao", "batao", "bhejo", "explain", "breakdown", "kaise", "bata", "send", "show", "chahiye"})


def _is_workflow_query(text: str) -> bool:
    # THE ACTUAL BUG (2026-09-12, UK: "jab bhi last response chat me
    # likha rehta hai, regex se last turn trigger ho jata hai"):
    # fuzzy matching was applied to the REFERENCE word too, and at
    # cutoff 0.72 ordinary Hinglish words collide with it -- "pata"
    # matches "pehla", "jante" matches "purana" -- so a message that
    # merely MENTIONED tools or a response would hijack the whole turn
    # into workflow narration instead of being answered. The reference
    # word is the one term that decides "this is a question ABOUT a
    # previous turn", so it must match EXACTLY; fuzzy tolerance stays
    # on the subject/action words, where a typo is common and a false
    # positive alone can't trigger anything.
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not any(word in _META_REFERENCE_WORDS for word in words):
        return False
    # A pasted block of JARVIS's own previous output is not a request
    # to narrate -- it is context UK is showing. Real narration asks
    # are short; anything with the tell-tale shape of pasted UI/log
    # text is excluded outright.
    if any(marker in text for marker in ("│", "╭", "╰", "──", "->", "[llm_unverified]", "JARVIS:")):
        return False
    return (
        _fuzzy_has_any(words, _META_SUBJECT_WORDS)
        and _fuzzy_has_any(words, _META_ACTION_WORDS)
    )


def try_workflow_narration_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 150 or brain is None:
        return None
    if not _is_workflow_query(text):
        return None

    # BUG FIX (2026-09-12, UK's trace: "Last 4 resposne check karke
    # btao" -> only ever got back ONE turn, never four). This used to
    # hardcode read_recent(limit=1) no matter what the user asked for
    # -- a count in the message ("last 3", "last 4", "pichhle 2") was
    # silently ignored. Now the count is actually parsed out and used.
    count = 1
    digit_match = re.search(r"\b(\d{1,2})\b", text)
    if digit_match:
        count = max(1, min(int(digit_match.group(1)), 20))  # capped, this is a chat reply not a dump
    else:
        _WORD_NUMBERS = {
            "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3,
            "char": 4, "chaar": 4, "four": 4, "paanch": 5, "panch": 5, "five": 5,
        }
        for word in re.findall(r"[a-zA-Z]+", text.lower()):
            if word in _WORD_NUMBERS:
                count = _WORD_NUMBERS[word]
                break

    try:
        from ..runtime.trace_log import get_trace_log
        recent = get_trace_log().read_recent(limit=count)
    except Exception:
        recent = []
    # BUG FIX: this used to prefer recent[1] over recent[0] ("in case
    # the freshest entry is this same turn") -- but this resolver runs
    # BEFORE the current turn's own trace_log.write() (that happens at
    # the very end of think_and_respond), so recent[0] was ALREADY the
    # correct, most-recent PAST turn the whole time. The old code was
    # silently reading one turn further back than intended -- another
    # reason "show me the last response's data" kept coming back empty
    # or stale.
    if not recent:
        return "Abhi tak koi pichhla turn record nahi hai."

    if count == 1:
        entry = recent[0]
        # THE ACTUAL BUG (2026-09-11, UK's direct feedback): this used to
        # return raw internal telemetry ("Perception source=unknown, Mode=
        # llm, status=completed...") AS the chat reply -- meaningless,
        # confusing debug text where a natural answer belongs. This is
        # also why recent_turns exclusion (see brain.py's
        # _record_action_response) matters: even the NATURAL version below
        # is a meta-answer about the system, not real conversational
        # content, and shouldn't be quoted back as if it were.
        prior_input = entry.get("user_input", "")
        prior_response = entry.get("response", "")
        grounded = entry.get("stayed_within_brief")
        note = ""
        if grounded is False:
            note = " (is jawab mein kuch aisa tha jo brief se bahar tha, flag ho gaya tha.)"
        if prior_response:
            return f'Pichhli baar tumne poocha tha "{prior_input}", aur maine jawab diya tha: "{prior_response}"{note}'
        return f'Pichhli baar tumne "{prior_input}" kaha tha, par uska response record nahi mila.'

    # Multi-turn case (last N > 1): list them oldest-to-newest so the
    # conversation reads in the order it actually happened.
    lines = [f"Yeh rahe aapke aakhri {len(recent)} turn:", ""]
    for i, entry in enumerate(reversed(recent), start=1):
        prior_input = entry.get("user_input", "")
        prior_response = entry.get("response", "") or "(response record nahi mila)"
        lines.append(f'{i}. User: {prior_input}\n   JARVIS: "{prior_response}"')
    return "\n\n".join(lines)


# =====================================================================
# 4. CONVERSATIONAL SELF-DIAGNOSTIC
# =====================================================================

_DIAGNOSTIC_TRIGGER = re.compile(
    r"\btum\s+theek\s+ho\b|\bkoi\s+bug\s+hai\b|\bsab\s+(?:sahi|thik)\s+chal\s+raha\b|"
    r"\bsab\s+organs?\s+fine\b|\bare\s+you\s+ok(?:ay)?\b|\bany\s+bugs?\b", re.I,
)


def try_self_diagnostic_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 100 or brain is None:
        return None
    if not _DIAGNOSTIC_TRIGGER.search(text):
        return None
    try:
        from ..orchestration.organ_introspection import introspect_all
        report = introspect_all(brain)
    except Exception:
        return "Self-check abhi run nahi ho paya (organ_introspection module issue)."

    flagged = []
    _BENIGN = {"nothing flagged", "none", "none flagged", "(no record yet this session)", ""}
    for organ_name, answers in (report or {}).items():
        unverified = str(answers.get("what_remains_unverified", "")).strip()
        if unverified.lower() not in _BENIGN:
            flagged.append(f"{organ_name}: {unverified}")

    if not flagged:
        return "Sab organs se self-check kiya -- koi flagged issue nahi mila is session mein."
    lines = ["Kuch cheezein flag hui hai self-check mein:"]
    lines.extend(f"- {item}" for item in flagged[:4])
    return " ".join(lines)


# =====================================================================
# 5. PER-ANSWER CONFIDENCE SELF-REPORT
# =====================================================================

_CONFIDENCE_TRIGGER = re.compile(
    r"\bpakka\s+fact\s+tha\s+ya\s+guess\b|\bkitna\s+(?:confident|sure)\b|"
    r"\bguess\s+tha\s+kya\b|\bhow\s+(?:confident|sure)\s+(?:are|were)\s+you\b", re.I,
)


def try_confidence_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 100 or brain is None:
        return None
    if not _CONFIDENCE_TRIGGER.search(text):
        return None

    perception = getattr(brain, "last_perception", None) or {}
    decision = getattr(brain, "last_brain_decision", None) or {}
    source = perception.get("source") if isinstance(perception, dict) else None
    confidence = perception.get("confidence") if isinstance(perception, dict) else None
    grounded = decision.get("stayed_within_brief")

    if source in ("direct_recall", "identity", "graph_multi_hop", "learned_template"):
        return f"Pichhla jawab ek stored fact/record se aaya tha ({source}) -- guess nahi tha, pakka data tha."
    if grounded is False:
        return "Pichhla jawab flag hua tha -- usmein kuch aisa tha jo brief mein confirm nahi tha, isliye usse zyada bharosa mat karo."
    if source == "llm":
        conf_txt = f" (perception confidence={confidence:.2f})" if isinstance(confidence, (int, float)) else ""
        return f"Pichhla jawab LLM ne generate kiya tha, brief ke andar rehte hue{conf_txt} -- guess nahi, par ek generated sentence tha, literal database record nahi."
    return "Pichhle turn ka confidence data abhi retained nahi hai."


# =====================================================================
# 6. METACOGNITIVE CALIBRATION (recall/learning/memory proposal #5)
# =====================================================================

_CALIBRATION_TRIGGER = re.compile(
    r"\bcalibration\s+kaisa\s+hai\b|\bkabhi\s+(?:galat|wrong)\s+confident\b|"
    r"\bkitna\s+reliable\s+ho\s+tum\b|\bhow\s+well[- ]calibrated\b|"
    r"\bkitni\s+baar\s+(?:galat|wrong)\s+the\s+confident\s+hokar\b", re.I,
)


def try_calibration_answer(user_input: str, brain: Any = None) -> Optional[str]:
    text = (user_input or "").strip()
    if not text or len(text) > 120 or brain is None:
        return None
    if not _CALIBRATION_TRIGGER.search(text):
        return None
    try:
        from ..learning.metacognition import calibration_report
        report = calibration_report(getattr(brain, "memory", None))
    except Exception:
        return "Calibration report abhi generate nahi ho paya."

    if not report.get("available"):
        return "Calibration data abhi available nahi hai (memory attached nahi hai)."
    total = report.get("total_contradictions", 0)
    if total == 0:
        return "Abhi tak koi fact contradict/correct nahi hua hai, isliye calibration score compute karne layak data nahi hai."
    score = report.get("calibration_score")
    over = report.get("overconfident_contradictions", 0)
    parts = [
        f"Ab tak {total} facts contradict/correct hue hai, jinme se {over} baar main HIGH confidence "
        f"(>=0.75) pe tha aur phir galat nikla.",
        f"Calibration score = {score} (1.0 = hamesha sahi confident, 0.0 = hamesha galat confident).",
    ]
    examples = report.get("examples") or []
    if examples:
        ex = examples[0]
        parts.append(
            f"Example: {ex['subject']} {ex['predicate']} pehle \"{ex['old_value']}\" tha "
            f"(confidence {ex['confidence_at_the_time']}), ab \"{ex['current_value']}\" hai."
        )
    return " ".join(parts)
