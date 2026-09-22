from __future__ import annotations

"""WHERE SHOULD THIS TURN'S ANSWER COME FROM? -- Brain's call, not the
router's.

THE ARCHITECTURAL INVERSION (2026-09-13, UK's explicit ask: "abhi
router brain ka route control karta hai... mai chahta hu position
reverse ho -- router ko brain bataye kab native use karna hai, kab SLM,
kab hybrid").

Before this module, cognitive_router.decide() was the authority: it
counted evidence (how many memories matched, how many skills exist,
what the semantic confidence was) and picked a route. Counting evidence
cannot tell you what KIND of knowing a question needs, so nearly
everything fell through its last branch to "llm" -- UK's own monitor
showed native_resolution_rate=0.0492, i.e. 95% of turns went to the
LLM regardless of whether the answer was sitting in JARVIS's own
database.

The fix models how a brain actually routes: the question's FORM tells
you which memory system owns it, before you know anything about the
answer. "What did I say last turn" is episodic. "What is my friend's
name" is semantic. "What is the Nifty at today" is not in any internal
store by definition -- it is world-state, so it needs a live source.
"How do I normally start a session" is procedural. None of that needs
an LLM call to work out, which is why this is pure structure
inspection: zero extra latency, zero tokens, and deterministic enough
that the same question always routes the same way.

Brain calls decide_information_need() and hands the result to the
router as a directive. The router's evidence-counting still runs, but
only to fill in details -- it no longer overrides Brain on WHERE the
answer lives.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# The memory systems / sources Brain can direct the turn at.
EPISODIC = "episodic"          # what happened in this or a past session
SEMANTIC = "semantic"          # stored facts about people, the world, the project
PROCEDURAL = "procedural"      # learned habits and how-we-usually-do-this
RULES = "rules"                # standing instructions and self-authored rules
SELF_STATE = "self_state"      # JARVIS's own architecture, organs, budget, health
WORLD_LIVE = "world_live"      # changes faster than any local store -- needs a real source
LANGUAGE = "language"          # genuine open-ended language work: the honest LLM case


@dataclass
class InformationNeed:
    """Brain's instruction to the router."""
    source: str
    route: str                      # native | hybrid | llm -- the executable route this implies
    reason: str                     # human-readable, shows up in the workflow trace
    confidence: float = 0.0
    requires_live_data: bool = False
    signals: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "route": self.route, "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "requires_live_data": self.requires_live_data, "signals": self.signals,
        }


# --- Signal vocabularies -------------------------------------------------
# Hinglish first, since that is how UK actually talks to JARVIS.

# Anything whose true value changes on a timescale shorter than a
# consolidation cycle cannot be answered from local memory, no matter
# how confident the model sounds. This is the NIFTY case from UK's
# trace: the model produced "18,340.15" from nothing.
_LIVE_WORLD_TERMS = {
    "aaj", "aj", "abhi", "today", "current", "currently", "latest", "live", "now",
    "kal", "tomorrow", "yesterday", "recent", "news", "khabar", "breaking",
    "price", "rate", "bhav", "kimat", "stock", "share", "nifty", "sensex", "market",
    "weather", "mausam", "temperature", "forecast", "barish",
    "score", "match", "result", "election", "kaun jeeta",
}
_LIVE_WORLD_PHRASES = (
    "kitne pe", "kya chal raha", "kya hua", "kab hoga", "band hua", "close hua",
    "open hua", "what is the price", "how much is", "kitna hai aaj",
)

# Questions about the conversation itself.
_EPISODIC_TERMS = {
    "pichhla", "pichhle", "pichla", "last", "previous", "earlier", "pehle",
    "abhi bola", "abhi kaha", "conversation", "baat", "turn", "response", "resposne",
    "session", "history", "chat",
}

# Questions about JARVIS's own machinery.
_SELF_STATE_TERMS = {
    "architecture", "organ", "organs", "budget", "token", "tokens", "memory type",
    "capability", "capabilities", "tool", "tools", "kaise kaam", "how do you work",
    "kaun ho", "who are you", "idle", "health", "status", "module", "pipeline",
}

_RULES_TERMS = {
    "rule", "rules", "instruction", "instructions", "standing", "pending",
    "niyam", "behaviour", "behavior", "hamesha", "always",
}

_PROCEDURAL_TERMS = {
    "procedure", "habit", "routine", "normally", "usually", "aam taur", "hamesha kaise",
    "workflow", "process", "steps", "tarika",
}

# A question ABOUT a stored person/thing -- semantic memory's job.
_SEMANTIC_RELATION_TERMS = {
    "naam", "name", "kaun", "who", "kaha", "where", "kab", "when", "birthday",
    "dost", "friend", "girlfriend", "family", "bhai", "behen", "papa", "mummy",
    "rehta", "rehti", "lives", "hobby", "pasand", "likes", "favourite", "favorite",
}


def _words(text: str) -> set:
    return set(re.findall(r"[a-zA-Z\u0900-\u097F]+", (text or "").lower()))


def _has_phrase(text: str, phrases) -> bool:
    low = (text or "").lower()
    return any(p in low for p in phrases)


def decide_information_need(
    user_input: str,
    perception: Optional[Dict[str, Any]] = None,
    *,
    has_stored_match: bool = False,
    native_capability_available: bool = False,
) -> InformationNeed:
    """Pure structure inspection -- no LLM call, no network, no DB read.

    Order matters and is not arbitrary: the checks run from the most
    specific, least reversible need to the most general. Getting
    WORLD_LIVE wrong is the expensive mistake (it produces confident
    fabrications like the invented Nifty close), so it is checked
    before anything that could answer from a local store.
    """
    text = (user_input or "").strip()
    words = _words(text)
    perception = perception or {}
    intent = (perception.get("intent") or {}) if isinstance(perception.get("intent"), dict) else {}
    intent_name = str(intent.get("name") or "").lower()
    requested = str(perception.get("requested_capability") or "").lower()
    signals: Dict[str, Any] = {"intent": intent_name or None, "requested_capability": requested or None}

    # 1. WORLD-STATE / LIVE DATA.
    # Two conditions together, not either alone: a recency marker AND a
    # question. "aaj maine code kiya" mentions aaj but asserts a
    # personal fact -- that belongs in semantic memory, not a search.
    live_hits = (words & _LIVE_WORLD_TERMS) | ({"phrase"} if _has_phrase(text, _LIVE_WORLD_PHRASES) else set())
    asks_something = intent_name in {"question", "search"} or "?" in text or requested in {"search", "web_search", "stock_price"}
    if live_hits and asks_something:
        signals["live_terms"] = sorted(t for t in live_hits if t != "phrase")
        return InformationNeed(
            source=WORLD_LIVE, route="hybrid",
            reason=("Yeh world-state ka sawaal hai -- iska sach local memory mein ho hi nahi sakta, "
                    "kyunki yeh time ke saath badalta hai. Live source chahiye, guess nahi."),
            confidence=0.9, requires_live_data=True, signals=signals,
        )

    # 2. THE CONVERSATION ITSELF -> episodic store, never the LLM's
    # impression of what was said (that is how a narration-of-a-
    # narration gets quoted back as if it were a real past reply).
    if words & _EPISODIC_TERMS:
        signals["episodic_terms"] = sorted(words & _EPISODIC_TERMS)
        return InformationNeed(
            source=EPISODIC, route="native",
            reason="Apni hi baatcheet ka sawaal -- episodic memory se seedha uthao, LLM se mat poocho.",
            confidence=0.88, signals=signals,
        )

    # 3. RULES / STANDING INSTRUCTIONS -- exact text matters, so these
    # are read, never paraphrased from memory of them.
    if words & _RULES_TERMS:
        signals["rules_terms"] = sorted(words & _RULES_TERMS)
        return InformationNeed(
            source=RULES, route="native",
            reason="Rules/instructions ka sawaal -- inka exact text store se padhna hai.",
            confidence=0.85, signals=signals,
        )

    # 4. JARVIS'S OWN MACHINERY -- answerable by introspection tools.
    if words & _SELF_STATE_TERMS:
        signals["self_terms"] = sorted(words & _SELF_STATE_TERMS)
        return InformationNeed(
            source=SELF_STATE, route="native",
            reason="Apne hi system ke baare mein -- introspection se jawab do, andaaze se nahi.",
            confidence=0.85, signals=signals,
        )

    if words & _PROCEDURAL_TERMS:
        signals["procedural_terms"] = sorted(words & _PROCEDURAL_TERMS)
        return InformationNeed(
            source=PROCEDURAL, route="native",
            reason="Seekhi hui habit/procedure ka sawaal -- procedural memory dekho.",
            confidence=0.75, signals=signals,
        )

    # 5. FACTS ABOUT PEOPLE AND THINGS. Routed native only when
    # something actually matched in the store -- otherwise honesty
    # requires saying "yeh mujhe nahi pata" rather than having an LLM
    # invent a plausible relative.
    if (words & _SEMANTIC_RELATION_TERMS) and asks_something:
        signals["semantic_terms"] = sorted(words & _SEMANTIC_RELATION_TERMS)
        signals["stored_match"] = has_stored_match
        if has_stored_match:
            return InformationNeed(
                source=SEMANTIC, route="native",
                reason="Stored fact ka sawaal aur memory mein match mila -- wahin se jawab, LLM ki zaroorat nahi.",
                confidence=0.9, signals=signals,
            )
        return InformationNeed(
            source=SEMANTIC, route="native",
            reason=("Stored fact ka sawaal, par memory mein kuch nahi mila -- iska imaandar jawab "
                    "'mujhe nahi pata' hai, LLM se banwana nahi."),
            confidence=0.8, signals=signals,
        )

    # 6. Genuine language work. Reached only when nothing above owns
    # the turn -- this is the honest LLM case, not a dumping ground.
    signals["native_capability_available"] = native_capability_available
    return InformationNeed(
        source=LANGUAGE, route="hybrid" if native_capability_available else "llm",
        reason="Open-ended language turn -- koi specific memory system iska maalik nahi hai.",
        confidence=0.6, signals=signals,
    )
