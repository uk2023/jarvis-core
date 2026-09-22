from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class SemanticFact:
    """Candidate fact produced by deterministic semantic understanding."""

    subject: str
    predicate: str
    value: Any
    confidence: float = 0.8
    source: str = "symbolic_parser"
    evidence: str = ""
    # THE ACTUAL "self-aware" piece: not just WHAT was extracted
    # (evidence = the matched raw text) but WHY this specific
    # mechanism fired -- which rule matched, and on what basis. This
    # is what lets JARVIS answer "why did you extract this" as a real,
    # traceable fact rather than an opaque regex match nobody
    # (including JARVIS itself) could explain afterward.
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticEntity:
    """Entity mention resolved into a stable semantic role."""

    text: str
    entity_id: str
    entity_type: str = "unknown"
    mention: str = "explicit"
    confidence: float = 0.8

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticEvent:
    """Event/action representation extracted from an utterance."""

    event_type: str
    subject: Optional[str] = None
    object: Optional[str] = None
    time: Optional[str] = None
    confidence: float = 0.8
    evidence: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SemanticUnderstandingEngine:
    """Dependency-light semantic understanding organ for JARVIS.

    The engine is deliberately deterministic and side-effect light. It turns
    normalized language into a structured representation containing intent,
    entities, references, relations, events, temporal cues and safe inference.
    It does not persist knowledge; candidates remain subject to the normal
    Experience -> Evaluation -> Knowledge boundary.
    """

    VERSION = "0.2.0"
    _SPACE_RE = re.compile(r"\s+")

    _NAME_PATTERNS = (
        (re.compile(r"\bmera\s+naam\s+(?:hai|is)\s+([A-Za-z][\w .'-]{1,60})", re.I), "user", "name", 0.96),
        (re.compile(r"\bmy\s+name\s+is\s+([A-Za-z][\w .'-]{1,60})\b", re.I), "user", "name", 0.98),
        (re.compile(r"\bi\s+am\s+([A-Za-z][\w .'-]{1,60})\b", re.I), "user", "identity", 0.88),
    )

    _RELATION_NAME_PATTERN = re.compile(
        r"\b(?:mera|meri|mere)\s+([A-Za-z][\w -]{1,50}?)\s+k[ai]\s+(?:naam|name)\s+([A-Za-z][\w .'-]{1,60})\s+(?:hai|h)\b",
        re.I,
    )

    # THE ACTUAL BUG (2026-09-11, UK's direct example: he stated "Heramb
    # mera dost hai" as a plain restatement of a friend's name, and it
    # was never promoted to semantic memory). _RELATION_NAME_PATTERN
    # above only covers relation-FIRST order ("mera dost ka naam Heramb
    # hai"). Name-FIRST order ("Heramb mera dost hai" -- <Name> is my
    # <relation>, no "ka naam" connector at all) is at least as common
    # in casual Hinglish and matched NO existing pattern whatsoever --
    # not a promotion-pipeline bug, a missing extractor pattern.
    _NAME_FIRST_RELATION_PATTERN = re.compile(
        r"\b([A-Za-z][\w'-]{1,40})\s+(?:mera|meri|mere)\s+([A-Za-z][\w -]{1,40}?)\s+(?:hai|h)\b",
        re.I,
    )

    # Capitalized words that are NEVER entities -- see
    # _extract_entities_structured() for why this exists (it is the
    # fix for the pronoun/reference confusion root cause). Covers
    # Hinglish pronouns, question words, connectives and fillers that
    # routinely appear sentence-initial and therefore capitalized.
    _NOT_ENTITY_WORDS = {
        # pronouns / possessives (the ones UK specifically flagged)
        "mai", "main", "mera", "meri", "mere", "mujhe", "mujeh", "muje", "mujhko",
        "tum", "tuu", "tune", "tumne", "tumhe", "tumhara", "tumhari", "tumhare",
        "aap", "aapka", "aapki", "aapke", "aapko", "apna", "apni", "apne",
        "hum", "humara", "humari", "humare", "woh", "wo", "vah", "yah", "yeh", "ye",
        "uska", "uski", "uske", "unka", "unki", "unke", "iska", "iski", "iske",
        "isse", "usse", "isko", "usko", "ise", "use", "inka", "inke",
        # question words
        "kya", "kyu", "kyun", "kaun", "kaunsa", "kis", "kiska", "kiske", "kisne",
        "kab", "kaha", "kahan", "kaise", "kaisa", "kitna", "kitni", "kitne", "jiske", "jo",
        # connectives / fillers
        "toh", "to", "aur", "par", "lekin", "phir", "fir", "bas", "abhi", "abi",
        "haa", "haan", "nahi", "nahin", "koi", "kuch", "kuchh", "sab", "sari", "saari",
        "are", "arey", "acha", "achha", "theek", "thik", "matlab", "bhi", "hi", "na",
        "yaha", "yahan", "waha", "wahan", "yahi", "wahi", "ab", "dekho", "batao",
        "bata", "karo", "kar", "karna", "hona", "hai", "hain", "tha", "thi", "the",
        # english function words that get capitalized sentence-initially
        "the", "this", "that", "these", "those", "there", "here", "what", "which",
        "who", "whom", "whose", "when", "where", "why", "how", "and", "but", "for",
        "not", "yes", "yeah", "you", "your", "yours", "our", "ours", "them", "they",
        "his", "her", "hers", "its", "can", "cant", "will", "would", "should",
        "could", "have", "has", "had", "was", "were", "been", "are", "from", "with",
        "last", "next", "first", "also", "just", "now", "then", "than", "some", "any",
        "all", "more", "most", "only", "very", "much", "many", "such", "same",
        "detail", "details", "list", "show", "check", "please", "thanks", "thank",
        "pehle", "phir", "fir", "baad", "wala", "wali", "wale", "jaisa", "jaisi",
        "jaise", "waisa", "waisi", "waise", "agar", "toh", "isliye", "kyunki",
    }

    # Common lowercase nouns that name the THING being built/discussed in a
    # coding conversation -- calculator, reader, tool, script, file, etc.
    # (2026-09-17, UK: "ye, wo, usse, isse nahi samajh pata" -- root cause
    # #2, once #1 above stopped function words being mistaken for entities:
    # the entity regex only ever matched CAPITALIZED words, so a real
    # referent typed the normal casual way -- "calculator", "pdf reader",
    # "tool", "script" -- never became an entity at all, leaving pronouns
    # with nothing genuine to resolve to. This is a closed, deliberately
    # small list of the object-nouns that actually recur in this domain,
    # not a general lowercase-noun extractor (which would over-match).
    _COMMON_OBJECT_NOUNS = {
        "calculator", "reader", "tool", "script", "file", "project", "app",
        "bot", "game", "function", "class", "module", "program", "code",
        "website", "site", "page", "form", "database", "api", "server",
        "agent", "generator", "converter", "parser", "scraper", "tracker",
        "dashboard", "extension", "plugin", "widget", "component",
    }

    # Value character classes deliberately EXCLUDE "." (unlike the older
    # version of this pattern) -- a period followed by more words means
    # the match has bled across a sentence boundary into whatever comes
    # next ("... hai. but javascript pe ..."), which is exactly how
    # garbage triples like favourite -> "hai. but javascript pe aur
    # react html ye sb b ata" ended up in the knowledge store: the old
    # `.` in the char class let the non-greedy capture keep extending
    # until it found a LATER "hai"/"h" token, swallowing an entire
    # run-on sentence as the "value". _is_plausible_fact() below is a
    # second, independent backstop against the same failure mode.
    _GENERIC_PATTERNS = (
        (re.compile(r"\b(?:mera|meri|mere)\s+([A-Za-z0-9][\w :/@+'-]{1,90}?)(?:\s+hai|\s+h)\b", re.I), "hinglish", 0.78),
        (re.compile(r"\bmy\s+([A-Za-z][\w -]{1,50}?)\s+is\s+([A-Za-z0-9][\w :/@+'-]{0,60}?)(?:[.!?]|$)", re.I), "english", 0.84),
        (re.compile(r"\bi\s+(?:live|work|study)\s+(?:in|at)\s+([A-Za-z0-9][\w .,'-]{1,80})(?:[.!?]|$)", re.I), "location_or_activity", 0.86),
    )

    _PREFERENCE_PATTERNS = (
        (re.compile(r"\bmujhe\s+(.+?)\s+pasand\s+hai\b", re.I), "likes", 0.90),
        (re.compile(r"\bi\s+like\s+(.+?)(?:[.!?]|$)", re.I), "likes", 0.92),
        (re.compile(r"\bi\s+prefer\s+(.+?)(?:[.!?]|$)", re.I), "prefers", 0.92),
        (re.compile(r"\bi\s+hate\s+(.+?)(?:[.!?]|$)", re.I), "dislikes", 0.90),
    )

    # Dedicated "favourite <category>" extraction. Before this existed,
    # a message like "meri favorite hobby coding hai" only matched the
    # generic hinglish catch-all above, which took the literal typed
    # word ("favoutite", "faviurite", whatever spelling the user typed)
    # as the predicate instead of a normalized "favourite_<category>"
    # key -- so /memory_inspect showed three separate, unrelated-looking
    # predicates ("favoutite", "faviurite", "favourite") for what was
    # obviously the same recurring statement type. normalize() below
    # folds common misspellings to "favourite"/"favorite" first, then
    # this pattern captures {category, value} cleanly.
    #
    # Two real, observed bugs fixed here:
    #   1. "fav" (a very common abbreviation -- "meri fav coding
    #      language Python hai") never matched at all, because the
    #      trigger word required the FULL "favourite"/"favorite" --
    #      _canonical_predicate() knows "fav" is an alias, but that
    #      only helps AFTER a match already happened, and the pattern
    #      itself never got that far. Fixed by adding "fav" as an
    #      alternate trigger.
    #   2. Multi-word categories ("coding language", "cricket team")
    #      silently corrupted extraction: with a lazy single-word
    #      capture group, "meri favourite coding language Oython hai"
    #      captured category="coding" and value="language Oython" --
    #      the second category word leaked into the value, producing
    #      a wrong predicate AND a wrong, unusable value. A real user
    #      hit this exact case. Fixed with a curated list of common
    #      multi-word categories tried FIRST (longest match wins in
    #      regex alternation), falling back to the generic single-word
    #      capture for anything not in the list.
    # Common CATEGORY-indicator nouns -- composed word-by-word rather
    # than as a finite list of exact multi-word PHRASES. The earlier
    # approach (a curated list like "coding language", "cricket team")
    # was real whack-a-mole: a genuine user typed "fast food" and
    # "full name", neither of which was in that list, and both hit the
    # exact same word-splitting bug ("favourite_fast" / "food chowmin",
    # "full" / "name UJJWAL") the curated list was supposed to have
    # already fixed. Composing from single indicator words generalizes
    # far further: "fast" and "food" are both indicators, so "fast
    # food X" correctly becomes category="fast_food" WITHOUT "fast
    # food" ever needing to be hardcoded as its own exact phrase --
    # the same goes for "full name", "coding language", and any other
    # combination of these words a person might type.
    # Clause-boundary markers -- when a captured value runs on into a
    # SECOND clause ("Akanksha haim wo Hamirpur district me rehti" --
    # name is "Akanksha", then a NEW clause about where she lives
    # starts at "wo"), truncating at the first one of these recovers
    # just the actual short answer instead of either keeping the whole
    # run-on fragment or rejecting the fact outright. This is a
    # genuinely closed, small class of relative-pronoun/conjunction
    # words in Hindi that mark a new clause starting -- not attempting
    # general sentence parsing.
    _CLAUSE_BOUNDARY_WORDS = ("wo", "woh", "jo", "jise", "jisse", "jiske", "aur", "lekin", "jaha", "jahan")

    @classmethod
    def _truncate_at_clause_boundary(cls, value: str) -> str:
        words = value.split()
        for i, word in enumerate(words):
            if i == 0:
                continue  # the value's own first word is never a boundary
            if word.strip(".,!?").lower() in cls._CLAUSE_BOUNDARY_WORDS:
                words = words[:i]
                break
        # Strip a trailing copula/auxiliary word left over from the
        # truncation itself ("Akanksha haim" -> "Akanksha") -- these
        # carry no meaning as part of a value, they were just the verb
        # of the clause that got cut off.
        _TRAILING_COPULA = {"hai", "hain", "haim", "h", "tha", "thi", "the", "hoon", "hun"}
        while words and words[-1].strip(".,!?").lower() in _TRAILING_COPULA:
            words = words[:-1]
        return " ".join(words).strip()

    _CATEGORY_INDICATOR_WORDS = frozenset({
        "favourite", "favorite", "fav", "full", "fast", "food", "hobby", "hobbies",
        "sport", "sports", "coding", "programming", "language", "name", "nick",
        "nickname", "middle", "last", "first", "color", "colour", "movie", "movies",
        "song", "songs", "team", "game", "games", "show", "genre", "actor", "actress",
        "book", "books", "place", "destination", "car", "bike", "phone", "brand",
        "pet", "friend", "girlfriend", "boyfriend", "job", "profession", "city",
        "country", "subject", "dish", "cuisine", "number", "email", "address",
    })

    @classmethod
    def _split_category_value(cls, span: str) -> tuple:
        """Given a raw captured span like "coding language Oython",
        "fast food chowmin", "full name UJJWAL", or "sport CRICKRT",
        split it into (category, value) by greedily consuming leading
        words that are known category-indicator nouns -- see
        _CATEGORY_INDICATOR_WORDS above for why this replaced a fixed
        multi-word phrase list."""
        words = span.strip().split()
        if len(words) <= 1:
            return ("", span.strip())
        idx = 0
        while idx < len(words) - 1 and words[idx].lower() in cls._CATEGORY_INDICATOR_WORDS:
            idx += 1
        if idx == 0:
            # No leading indicator words recognized at all -- fall back
            # to the original heuristic (first word is the category)
            # rather than dumping the entire span into an unusable value.
            idx = 1
        category = "_".join(w.lower() for w in words[:idx])
        value = " ".join(words[idx:])
        return (category, value)

    _FAVOURITE_PATTERNS = (
        re.compile(
            r"\b(?:mera|meri)\s+fa(?:vou?rite|v)\s+([A-Za-z0-9][\w :/@+'-]{1,80}?)\s+(?:hai|h)\b",
            re.I,
        ),
        re.compile(
            r"\bmy\s+fa(?:vou?rite|v)\s+([A-Za-z][\w -]{1,30}?)\s+is\s+([A-Za-z0-9][\w :/@+'-]{0,60}?)(?:[.!?]|$)",
            re.I,
        ),
    )

    # Second, independent backstop (see _GENERIC_PATTERNS comment above):
    # even a correctly-anchored regex can capture a plausible-looking but
    # wrong value on messy/typo'd input, so every extracted fact -- from
    # every pattern group -- is checked here before it is ever yielded.
    _FACT_FILLER_WORDS = {
        "kya", "batao", "bataye", "bataiye", "lekin", "but", "abhi",
        "pehle", "phla", "aur", "toh", "hai.", "ok", "okay", "acha",
    }
    # Hindi infinitive/task verbs -- catches "mera resume BANANA hai"
    # (I need to MAKE my resume -- a task) getting stored as if
    # predicate="resume" value="banana" were a real identity fact,
    # and "mera kaam khatam KARNA hai" similarly. A real, observed
    # false-positive: the generic "mera X hai" pattern has no way to
    # tell a task/intention from a fact on its own, since both share
    # the exact same surface grammar. This is a principled, closed
    # grammatical category (Hindi infinitives), not an open-ended
    # noun list like category-indicator words -- rejecting a fact
    # whose VALUE is itself an action-to-be-done, rather than a
    # thing that IS true, is what a person naturally does without
    # having to think about it.
    _TASK_VERB_INDICATORS = {
        "banana", "banani", "banane", "banao", "karna", "karni", "karne",
        "karo", "khatam", "shuru", "khareedna", "khareedni", "kharidna",
        "bhejna", "bhejni", "bhejo", "lena", "leni", "leke", "dena", "deni",
        "do", "jaana", "jana", "jani", "jao", "aana", "aani", "milna",
        "milni", "dekhna", "dekhni", "dekho", "sunna", "sunni", "suno",
        "padhna", "padhni", "likhna", "likhni", "likho", "dhundna",
        "dhoondhna", "dhoondna", "samjhana", "samjhao", "batana", "bulana",
        "bulao", "rakhna", "rakhni", "rakho", "bhoolna", "seekhna",
        "sikhna", "chahiye", "padega", "padegi", "hoga", "hogi", "kholna",
        "kholni", "band", "chalu", "theek", "fix",
    }
    # A real, observed failure: "mere dost mere liye important hai" (my
    # friends are important to me -- an OPINION/feeling statement, not
    # a clean fact) matched the generic possessive pattern and produced
    # predicate="dost" value="mere liye important" -- a fragment of the
    # sentence, not a usable value, which then got read back to the
    # user verbatim as if it were someone's actual name. Values ending
    # in a common opinion/descriptor word (rather than a concrete noun,
    # name, or adjective describing a THING) are a strong signal the
    # capture bled into an opinion clause rather than staying inside a
    # clean "X is Y" fact.
    _OPINION_TAIL_WORDS = {
        "important", "zaroori", "achha", "acchi", "accha", "achhi",
        "bura", "buri", "best", "worst", "special", "valuable",
    }
    # A real, severe, observed bug: "jarvis meri girlfriend kaha rehti
    # hai?" and "meri girlfriend kaun hai?" -- both QUESTIONS -- matched
    # the generic possessive pattern and got stored as
    # predicate="girlfriend" value="kaha rehti" / value="kaun", as if
    # the question word itself were the answer. The pattern only ever
    # checked for "mera/meri X hai", never whether X was itself a
    # question ("kaun"=who, "kaha"=where, etc.) rather than an answer.
    # A genuine fact's value should never CONTAIN a question word --
    # this rejects any value where one appears.
    _QUESTION_INDICATOR_WORDS = {
        "kaun", "kise", "kisne", "kiska", "kiski", "kiske",
        "kaha", "kahan", "kidhar", "kab", "kyun", "kyu", "kyon",
        "kaise", "kaisi", "kaisa", "kitna", "kitni", "kitne",
        "kaunsa", "kaunsi", "kaunse", "kya",
    }
    _MAX_FACT_VALUE_WORDS = 6
    _MAX_FACT_VALUE_CHARS = 60

    @classmethod
    def _is_plausible_fact(cls, predicate: str, value: Any) -> bool:
        predicate = str(predicate or "").strip()
        value_text = str(value or "").strip()
        if not predicate or not value_text:
            return False
        # A sentence terminator followed by more text means the capture
        # bled past the end of the intended statement into the next one.
        if re.search(r"[.!?]\s*\S", value_text):
            return False
        words = value_text.split()
        if len(words) > cls._MAX_FACT_VALUE_WORDS:
            return False
        if len(value_text) > cls._MAX_FACT_VALUE_CHARS:
            return False
        lowered_words = {w.strip(".,!?").lower() for w in words}
        if lowered_words & cls._FACT_FILLER_WORDS:
            return False
        # Reject if the value's LAST word (the part that most often
        # carries the verb in Hindi "X karna/banana hai" phrasing) is a
        # task-indicator -- see _TASK_VERB_INDICATORS above. EXCEPT for
        # preference-type predicates (likes/dislikes/prefers): "mujhe
        # travel karna pasand hai" (I like to travel) genuinely
        # describes a liked ACTIVITY, not a task-to-complete, even
        # though it ends in the same verb form as "mera resume banana
        # hai" (I need to make my resume) -- a real, observed false
        # positive this exception fixes. The "pasand/like/prefer"
        # framing already establishes this is a preference, not an
        # intention, so the task-verb heuristic doesn't apply here.
        last_word = words[-1].strip(".,!?").lower() if words else ""
        if last_word in cls._TASK_VERB_INDICATORS and predicate not in ("likes", "dislikes", "prefers"):
            return False
        if last_word in cls._OPINION_TAIL_WORDS:
            return False
        # ANY word in the value being a question-indicator means this
        # is a question, not an answer -- checks the whole value, not
        # just the last word, since "kaha rehti" has the question word
        # FIRST while "kaun" alone has it as the only word.
        value_words_lower = {w.strip(".,!?").lower() for w in words}
        if value_words_lower & cls._QUESTION_INDICATOR_WORDS:
            return False
        predicate_words = {w.lower() for w in re.split(r"[_\s]+", predicate) if w}
        if predicate_words & cls._FACT_FILLER_WORDS:
            return False
        return True

    _TEMPORAL_PATTERNS = (
        (re.compile(r"\b(kal|yesterday)\b", re.I), "relative_day"),
        (re.compile(r"\b(aaj|today)\b", re.I), "today"),
        (re.compile(r"\b(kal|tomorrow)\b", re.I), "relative_day"),
        (re.compile(r"\b(parso)\b", re.I), "relative_day"),
        (re.compile(r"\b(abhi|now)\b", re.I), "now"),
        (re.compile(r"\b(baad\s+mein|later)\b", re.I), "future_relative"),
    )

    _ACTION_PATTERNS = (
        (re.compile(r"\b(?:maine|main)\s+(.+?)\s+(?:seekhna|sikhna)\s+start\s+(?:kiya|ki)\b", re.I), "learning_started"),
        (re.compile(r"\b(?:i|maine|main)\s+(?:start|started)\s+(?:learning|studying)\s+(.+?)(?:[.!?]|$)", re.I), "learning_started"),
        (re.compile(r"\b(?:i\s+am|main\s+)?(?:learning|studying)\s+(.+?)(?:[.!?]|$)", re.I), "learning_started"),
        (re.compile(r"\b(?:maine|main)\s+(.+?)\s+(?:banana|banaya)\s+start\s+(?:kiya|ki)\b", re.I), "creation_started"),
        (re.compile(r"\b(?:maine|main)\s+(.+?)\s+(?:seekha|sikha)\b", re.I), "learned"),
    )

    _COMMAND_PATTERNS = (
        re.compile(r"^(?:open|start|run|stop|search|find|show|tell|remember|delete|create|execute|chala|karo|batao|dikhao|dhundo|khol)\b", re.I),
        re.compile(r"^(?:please\s+)?(?:open|start|run|stop|search|find|show|tell|remember|delete|create|execute)\b", re.I),
    )
    _QUESTION_PATTERNS = re.compile(r"^(?:what|why|how|when|where|who|which|can|could|is|are|do|does|did|kya|kyu|kyun|kaise|kab|kahan|kaun|hai|hain)\b", re.I)

    _PRONOUNS = {
        "it": "singular_object", "this": "demonstrative", "that": "demonstrative",
        "usko": "singular_object", "isko": "singular_object", "usse": "singular_object",
        "isme": "singular_object", "usme": "singular_object", "wahi": "demonstrative",
        "yeh": "demonstrative", "ye": "demonstrative", "woh": "demonstrative",
        # ADDED (2026-09-17, UK: "ye, wo, usse, isse nahi samajh pata"):
        # these are among the MOST common Hinglish object pronouns in
        # everyday typed speech -- "ise fix karo", "use dekho", "isse
        # start karo" -- and were simply absent from this dict, so
        # _resolve_references() never even looked at them; the pronoun
        # passed straight through unresolved, with no reference entry
        # at all (not even a failed one), which is why it looked like
        # JARVIS "didn't understand" rather than "resolved it wrong".
        "ise": "singular_object", "use": "singular_object", "isse": "singular_object",
        "unhe": "plural_object", "unko": "plural_object", "inhe": "plural_object",
        "wo": "demonstrative", "vo": "demonstrative", "iska": "possessive",
        "uska": "possessive", "iski": "possessive", "uski": "possessive",
        "iske": "possessive", "uske": "possessive",
    }

    def __init__(self, *, max_context_turns: int = 8) -> None:
        self.max_context_turns = max(1, int(max_context_turns))
        self._recent_turns: List[Dict[str, Any]] = []
        self._last_entities: List[Dict[str, Any]] = []
        self._last_events: List[Dict[str, Any]] = []

    def normalize(self, text: str) -> str:
        text = str(text or "").strip()
        text = self._SPACE_RE.sub(" ", text)
        replacements = {
            r"\bnan\b": "naam", r"\bkrna\b": "karna", r"\bnhi\b": "nahi",
            r"\bsmjhna\b": "samajhna", r"\bthk\b": "theek",
            # Common typo'd spellings of "favourite" all collapse to one
            # canonical form before extraction, so "favoutite", "faviurite",
            # "favirite", "favorate" etc. all hit _FAVOURITE_PATTERNS
            # instead of each becoming its own distinct, garbage predicate
            # in the generic catch-all (see _FAVOURITE_PATTERNS comment).
            r"\bfavou?ti+te\b": "favourite", r"\bfavi+u?rite\b": "favourite",
            r"\bfavi?rite\b": "favourite", r"\bfavou?rate\b": "favourite",
            r"\bfavrite\b": "favourite", r"\bfavroite\b": "favourite",
        }
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.I)
        return text

    @staticmethod
    def _clean_phrase(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip(" \t\n.,!?;:"))

    @staticmethod
    def _subject_key(raw: str) -> str:
        raw = re.sub(r"[^a-zA-Z0-9_ ]+", " ", raw.lower())
        raw = re.sub(r"\s+", "_", raw.strip())
        return raw[:80] or "user"

    @staticmethod
    def _entity_id(text: str) -> str:
        return "entity:" + SemanticUnderstandingEngine._subject_key(text)

    def _name_facts(self, text: str) -> Iterable[SemanticFact]:
        # THE ACTUAL BUG THIS FIXES: neither branch below ever called
        # _is_plausible_fact() -- so the length limit (_MAX_FACT_VALUE_
        # WORDS/_MAX_FACT_VALUE_CHARS) that exists specifically to keep
        # a value to a short, precise name never actually applied to
        # THIS extractor, which is exactly the one handling "X ka naam
        # Y hai" (girlfriend/friend names). A real, observed failure:
        # "meri girlfriend ka naam Akanksha hai, woh Hamirpur district
        # mein rehti hai" produced value="Akanksha haim wo Hamirpur
        # district me rehti" (7 words, a run-on fragment of the WHOLE
        # sentence) instead of being rejected/truncated to just the
        # name. Both branches now call the same plausibility check
        # every other extractor already uses.
        for pattern, subject, predicate, confidence in self._NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                value = self._clean_phrase(match.group(1))
                if value and self._is_plausible_fact(predicate, value):
                    yield SemanticFact(subject, predicate, value, confidence, "symbolic_parser", match.group(0))
        relation = self._RELATION_NAME_PATTERN.search(text)
        if relation:
            subject = self._subject_key(relation.group(1))
            value = self._truncate_at_clause_boundary(self._clean_phrase(relation.group(2)))
            # THE ACTUAL BUG (2026-09-11 trace-log audit, Bug 3): "mere
            # dost ka naam Heramb aur sunil hai" (typos aside) matched
            # this pattern fine, but value captured the WHOLE joined
            # span "Heramb aur sunil" as if it were one name -- a
            # single-value fact, silently losing the second name's
            # existence as a distinct, individually-recallable fact
            # (only ever findable by matching the exact combined
            # string, never by "sunil" alone). Split on the Hindi/
            # English conjunction and yield ONE fact per name instead,
            # same subject/predicate, each independently stored and
            # therefore independently recallable later.
            if subject and value:
                names = [n.strip() for n in re.split(r"\s+(?:aur|and)\s+", value, flags=re.I) if n.strip()]
                if len(names) > 1:
                    # Same (subject, predicate) slot would otherwise
                    # just overwrite -- "name" isn't in semantic_
                    # memory.py's multi-value-predicate list (rightly
                    # so; that's for accumulating things like hobbies
                    # under ONE subject, not for a single subject
                    # having multiple names). Instead each name gets
                    # its OWN subject slot ("dost_heramb", "dost_sunil")
                    # so both are genuinely independent, individually
                    # recallable facts rather than colliding.
                    for name in names:
                        if self._is_plausible_fact("name", name):
                            distinct_subject = f"{subject}_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"
                            yield SemanticFact(distinct_subject, "name", name, 0.96, "symbolic_parser", relation.group(0))
                elif self._is_plausible_fact("name", value):
                    yield SemanticFact(subject, "name", value, 0.96, "symbolic_parser", relation.group(0))
        else:
            # Name-FIRST order fallback (see _NAME_FIRST_RELATION_PATTERN
            # above) -- only checked when the relation-first pattern
            # didn't already match, so a sentence never gets extracted
            # twice by two different patterns.
            name_first = self._NAME_FIRST_RELATION_PATTERN.search(text)
            if name_first:
                value = self._clean_phrase(name_first.group(1))
                subject = self._subject_key(name_first.group(2))
                if subject and value and self._is_plausible_fact("name", value):
                    yield SemanticFact(subject, "name", value, 0.9, "symbolic_parser", name_first.group(0))

    def _location_facts(self, text: str, subject: str) -> Iterable[SemanticFact]:
        """"X mein rehta/rehti hai" (lives in X) -- the Hindi
        counterpart to _generic_facts' English "I live in X" pattern.
        Takes an explicit subject rather than always assuming "user",
        since this is specifically meant to also catch the SECOND
        clause of a compound sentence about a THIRD PARTY (see
        understand()'s inherited_subject wiring). Anchored to start
        right after a clause-boundary word (wo/jo/...) -- a real,
        observed bug without this anchor: an unanchored search greedily
        captured everything from an EARLIER, unrelated word all the way
        to the location, because nothing constrained where the capture
        group's span could legitimately start."""
        # "hai" is frequently dropped/shortened to just "h" in casual
        # Hinglish texting (e.g. "wo hamirpur, UP me rahti h") -- a
        # real observed miss: the old pattern required literal "hai",
        # so this extremely common shorthand fell all the way through
        # to the LLM fallback (and then sometimes failed there too,
        # purely on LLM call-budget grounds) even though this is a
        # deterministic, zero-LLM-call case. Also widened the location
        # capture to allow a comma ("Hamirpur, UP") since a place name
        # followed by its state/country is a common real pattern.
        # "rehti/rehta" vs "rahti/rahta" -- both are common transliteration
        # spellings of the same Hindi word (रहती/रहता); the old pattern
        # only accepted the "reh-" spelling and silently missed "rah-",
        # which is at least as common in casual typing.
        pattern = re.compile(
            r"\b(?:wo|woh|jo|jise)\s+([A-Za-z][\w, -]{1,40}?)\s+(?:mein|me)\s+r[ae]h[tn][ai]\s+(?:hai|hain|h)\b", re.I
        )
        for match in pattern.finditer(text):
            value = self._truncate_at_clause_boundary(self._clean_phrase(match.group(1)))
            if value and self._is_plausible_fact("lives_in", value):
                yield SemanticFact(subject, "lives_in", value, 0.85, "symbolic_parser", match.group(0))

    def _preference_facts(self, text: str) -> Iterable[SemanticFact]:
        for pattern, predicate, confidence in self._PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                value = self._clean_phrase(match.group(1))
                if value and self._is_plausible_fact(predicate, value):
                    yield SemanticFact("user", predicate, value, confidence, "symbolic_parser", match.group(0))

    def _favourite_facts(self, text: str) -> Iterable[SemanticFact]:
        # .finditer() (not .search()) so a SINGLE message with more
        # than one "favourite X Y hai" statement -- "meri favourite
        # hobby coding hai aur meri favourite sport cricket hai" --
        # yields BOTH facts instead of silently dropping every
        # occurrence after the first. This was a real, observed gap:
        # multi-fact statements in one turn only ever produced one
        # stored fact, no matter how many were actually said.
        for pattern in self._FAVOURITE_PATTERNS:
            for match in pattern.finditer(text):
                if match.lastindex and match.lastindex >= 2 and match.group(2):
                    # The English "my X is Y" pattern -- "is" already
                    # unambiguously delimits category from value, no
                    # splitting heuristic needed.
                    category = self._subject_key(self._clean_phrase(match.group(1)))
                    value = self._clean_phrase(match.group(2))
                    reason = f"matched \"my <category> is <value>\" pattern -- 'is' explicitly separates category from value, no ambiguity to resolve"
                else:
                    # The Hinglish "mera/meri favourite X Y hai" pattern --
                    # genuinely ambiguous where category ends and value
                    # begins with no delimiter word, so split via known
                    # category-indicator words (see _split_category_value).
                    raw_span = self._clean_phrase(match.group(1))
                    raw_category, raw_value = self._split_category_value(raw_span)
                    category = self._subject_key(raw_category)
                    value = self._clean_phrase(raw_value)
                    consumed = raw_category.replace("_", " ").split() if raw_category else []
                    if consumed and all(w.lower() in self._CATEGORY_INDICATOR_WORDS for w in consumed):
                        reason = f"matched \"favourite <category> <value> hai\" -- recognized {consumed} as category-indicator word(s), so everything after became the value"
                    else:
                        reason = f"matched \"favourite <category> <value> hai\" -- no recognized category-indicator word found, fell back to treating the first word as the category"
                predicate = f"favourite_{category}" if category else "favourite"
                if value and self._is_plausible_fact(predicate, value):
                    yield SemanticFact("user", predicate, value, 0.9, "symbolic_parser", match.group(0), reason)

    def _generic_facts(self, text: str) -> Iterable[SemanticFact]:
        # Action statements are represented by _extract_events(), not as
        # generic identity/state facts.
        is_learning_event = bool(
            re.search(
                r"^\s*(?:i\s+(?:am|'m)|main\s+)?(?:learning|studying)\s+.+",
                text,
                re.I,
            )
            or re.search(
                r"^\s*i\s+(?:am|'m)\s+learning\s+.+",
                text,
                re.I,
            )
        )

        # NOT a global "does this text contain the word favourite
        # anywhere" flag -- that was a REAL bug for multi-sentence
        # paragraphs: "Mera naam UJJWAL hai. Meri favourite hobby
        # coding hai." would incorrectly suppress the completely
        # unrelated name-extraction because "favourite" appeared
        # SOMEWHERE ELSE in the paragraph, not in the same sentence as
        # "mera naam". This is checked per-MATCH below instead (does
        # THIS specific matched span contain "favourite"), so one
        # sentence's favourite-statement can no longer silently
        # suppress a different sentence's unrelated fact.

        for pattern, style, confidence in self._GENERIC_PATTERNS:
            if is_learning_event:
                continue
            # .finditer() (not .search()) -- same multi-fact gap as
            # _favourite_facts() above: one message can genuinely state
            # more than one fact ("mera naam UJJWAL hai aur mera pet
            # Tommy hai"), and only the FIRST used to ever get captured.
            for match in pattern.finditer(text):
                # "favourite X ... hai" is handled by the dedicated,
                # cleaner _favourite_facts() extractor above -- skip
                # THIS specific match here (not the whole text) so the
                # broad catch-all doesn't ALSO fire on the same
                # statement and produce a second, cruder triple for
                # what is really one fact.
                if style != "location_or_activity" and re.search(r"\bfavou?rite\b", match.group(0), re.I):
                    continue
                # Same conflict, different trigger word: "X ka naam/name
                # Y hai" is handled by the dedicated, more precise
                # _RELATION_NAME_PATTERN via _name_facts() above (it
                # correctly identifies subject="girlfriend"/"friend" and
                # predicate="name" instead of the generic catch-all's
                # cruder subject="user", predicate="girlfriend",
                # value="ka Name Akanksha" for the exact same sentence --
                # a real, observed duplicate/conflicting-extraction bug).
                if style != "location_or_activity" and re.search(r"\bk[ai]\s+(?:naam|name)\b", match.group(0), re.I):
                    continue
                if style == "location_or_activity":
                    value = self._clean_phrase(match.group(1))
                    if value:
                        predicate = "lives_in" if "live" in match.group(0).lower() else "activity_location"
                        yield SemanticFact("user", predicate, value, confidence, "symbolic_parser", match.group(0))
                    continue
                if style == "hinglish":
                    # No delimiter word between category and value here
                    # ("mera full name UJJWAL hai") -- genuinely ambiguous,
                    # split via known category-indicator words instead of
                    # the previous lazy single-word capture that let "name"
                    # leak into the value ("full" / "name UJJWAL").
                    raw_predicate, value = self._split_category_value(self._clean_phrase(match.group(1)))
                    value = self._clean_phrase(value)
                else:
                    # "english" style: "is" already unambiguously delimits
                    # category from value.
                    raw_predicate = self._clean_phrase(match.group(1))
                    value = self._clean_phrase(match.group(2))

                # Action statements such as "I am learning Python" are
                # events, not identity facts.
                if re.match(r"^i\s+(?:am|m)\s+(?:learning|studying)\b", text, re.I):
                    continue

                raw_predicate = re.sub(r"\b(naam|name)\b", "name", raw_predicate, flags=re.I)
                predicate_key = self._subject_key(raw_predicate)
                if raw_predicate and value and self._is_plausible_fact(predicate_key, value):
                    yield SemanticFact("user", predicate_key, value, confidence, "symbolic_parser", match.group(0))

    def _extract_temporal(self, text: str) -> List[Dict[str, str]]:
        found: List[Dict[str, str]] = []
        for pattern, temporal_type in self._TEMPORAL_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).lower()
                item = {"text": value, "type": temporal_type}
                if item not in found:
                    found.append(item)
        return found

    def _extract_entities_structured(self, text: str) -> List[Dict[str, Any]]:
        entities: List[Dict[str, Any]] = []
        seen = set()
        # Proper nouns / technical names.
        #
        # THE ACTUAL BUG (2026-09-12, from UK's live trace -- this is
        # the ROOT CAUSE of the pronoun/context confusion he reported,
        # "mai tum tumhe mujhe mera tumhara me confuse karta hai"):
        # this regex matches ANY capitalized word, so ordinary Hinglish
        # function words at the start of a sentence -- "Toh", "Koi",
        # "Yaha", "Are", "But", "Kis", "Pata", "Tum", "Mere", "Apne",
        # "Ise", "Abhi", "Haa", "Last" -- were all being recorded as
        # named_entity with 0.90 confidence. _resolve_references()
        # below then resolves demonstratives ("ye", "isko", "uska")
        # against that entity list, so "ye" was resolving to "Toh" or
        # "Kis" -- visible verbatim in the trace as
        # resolved_to={'text': 'Toh'} and resolved_to={'text': 'Kis'}.
        # Every downstream layer then reasoned about the wrong subject.
        # A capitalized word is only a real entity if it is NOT a known
        # function word; the blocklist below is the fix.
        for match in re.finditer(r"\b[A-Z][a-zA-Z0-9_-]{2,30}\b", text):
            value = match.group(0)
            key = value.lower()
            if key in self._NOT_ENTITY_WORDS:
                continue
            if key not in seen:
                seen.add(key)
                entity_type = "person" if value.lower() in {"ujjwal", "devyana"} else "named_entity"
                entities.append(SemanticEntity(value, self._entity_id(value), entity_type, "explicit", 0.90).as_dict())
        # Technical noun phrases in common learning/action constructions.
        for match in re.finditer(r"\b(?:python|javascript|java|react|node(?:\.js)?|machine\s+learning|ai|android)\b", text, re.I):
            value = match.group(0)
            key = value.lower()
            if key not in seen:
                seen.add(key)
                entities.append(SemanticEntity(value, self._entity_id(value), "topic", "explicit", 0.86).as_dict())
        # COMMON OBJECT NOUNS -- lowercase, mid-sentence (see
        # _COMMON_OBJECT_NOUNS above). Matched in mention order like the
        # capitalized pass, so recency-based reference resolution in
        # _resolve_references() has a real "the thing we're building"
        # candidate even when it was never capitalized -- almost always
        # the case in casual typing ("pdf reader banao", "ab calculator
        # fix karo").
        for match in re.finditer(r"\b[a-z][a-z0-9_-]{2,30}\b", text, re.I):
            value = match.group(0)
            key = value.lower()
            if key in seen or key not in self._COMMON_OBJECT_NOUNS:
                continue
            seen.add(key)
            entities.append(SemanticEntity(value, self._entity_id(value), "object", "explicit", 0.82).as_dict())
        return entities[:20]

    def _resolve_references(self, text: str, entities: List[Dict[str, Any]], context: Mapping[str, Any]) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        previous = list(self._last_entities)
        supplied = context.get("entities") if isinstance(context, Mapping) else None
        if isinstance(supplied, list):
            previous = [x for x in supplied if isinstance(x, dict)] + previous
        # RECENCY, NOT FIRST-FOUND (2026-09-17, UK: "ye, wo, usse, isse
        # nahi samajh pata, purana context nahi samajh pata" -- still
        # happening after the _NOT_ENTITY_WORDS fix above, which only
        # stopped function words from becoming FAKE entities. This is a
        # separate bug in how a REAL entity gets picked once there is
        # more than one: `next(...)` always took the FIRST item in
        # `previous`, i.e. whichever entity was mentioned EARLIEST in
        # the prior turn's text -- the opposite of how Hinglish/English
        # pronouns actually resolve. "PDF reader banaya, phir calculator
        # bhi... ab ise fix karo" should resolve "ise" to the
        # calculator (most recently mentioned), not the PDF reader
        # (mentioned first) -- entities are appended in left-to-right
        # mention order by _extract_entities_structured, so the LAST
        # one in the list is the most recent mention, the standard
        # coreference-resolution default in the absence of stronger
        # cues.
        candidate = next((x for x in reversed(previous) if x.get("entity_id") or x.get("text")), None)
        for token in re.findall(r"\b[\w]+\b", text.lower()):
            if token not in self._PRONOUNS:
                continue
            resolved = candidate
            refs.append({
                "mention": token,
                "type": self._PRONOUNS[token],
                "resolved_to": dict(resolved) if resolved else None,
                "confidence": 0.86 if resolved else 0.0,
            })
        return refs

    def _extract_events(self, text: str, temporal: List[Dict[str, str]], entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        time_value = temporal[0]["text"] if temporal else None
        for pattern, event_type in self._ACTION_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            raw = self._clean_phrase(match.group(1))
            # A REAL, previously-unfixed gap: these patterns capture
            # EVERYTHING between the trigger words as the object, with
            # no awareness that a temporal word ("kal", "aaj", "abhi")
            # can legitimately sit in between ("Maine kal Python
            # seekhna start kiya") -- so the object came out as "kal
            # Python" instead of "Python", even though "kal" was ALSO
            # (correctly) extracted separately as the event's own
            # `time` field. Strip a temporal word from the front of the
            # object when it's the SAME word already recognized as this
            # event's time, so it isn't duplicated into both fields.
            if time_value:
                raw = re.sub(rf"^{re.escape(time_value)}\s+", "", raw, flags=re.I)
            obj = raw
            events.append(SemanticEvent(event_type, "user", obj, time_value, 0.88, match.group(0)).as_dict())
            break
        return events

    def _extract_semantic_relations(self, events: List[Dict[str, Any]], temporal: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        relations: List[Dict[str, Any]] = []
        for event in events:
            subject = event.get("subject") or "user"
            obj = event.get("object")
            if obj:
                relations.append({"subject": subject, "predicate": event["event_type"], "value": obj,
                                  "confidence": event["confidence"], "source": "event_parser", "evidence": event["evidence"]})
            if event.get("time"):
                relations.append({"subject": event["event_type"], "predicate": "occurred_at", "value": event["time"],
                                  "confidence": 0.84, "source": "temporal_parser", "evidence": event["evidence"]})
        return relations

    def _infer(self, events: List[Dict[str, Any]], references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        inferences: List[Dict[str, Any]] = []
        for event in events:
            if event.get("event_type") == "learning_started" and event.get("object"):
                inferences.append({
                    "type": "current_learning_target",
                    "subject": "user",
                    "value": event["object"],
                    "confidence": round(float(event.get("confidence", 0.8)) * 0.90, 3),
                    "source": "semantic_inference",
                    "from_event": event["event_type"],
                })
        for ref in references:
            resolved = ref.get("resolved_to")
            if resolved:
                inferences.append({
                    "type": "resolved_reference",
                    "mention": ref["mention"],
                    "entity": resolved,
                    "confidence": ref.get("confidence", 0.0),
                    "source": "context_resolution",
                })
        return inferences
        
    @staticmethod
    def _detect_intent(text: str) -> Dict[str, Any]:
        if text.endswith("?") or SemanticUnderstandingEngine._QUESTION_PATTERNS.search(text):
            return {
                "name": "question",
                "confidence": 0.90,
                "source": "symbolic_parser",
            }

        for pattern in SemanticUnderstandingEngine._COMMAND_PATTERNS:
            if pattern.search(text):
                return {
                    "name": "command",
                    "confidence": 0.90,
                    "source": "symbolic_parser",
                }

        return {
        "name": "statement",
        "confidence": 0.72,
        "source": "symbolic_parser",
        }
        

    @staticmethod
    def _detect_language(text: str) -> str:
        if re.search(r"[\u0900-\u097F]", text):
            return "hi"
        if re.search(r"\b(yaar|kya|kyu|kyun|kaise|mujhe|mera|meri|hai|hain|ho|karna|usko|wahi)\b", text, re.I):
            return "hinglish"
        return "en"

    def _build_context_snapshot(self) -> Dict[str, Any]:
        return {
            "last_intent": self._recent_turns[-1].get("intent", {}).get("name") if self._recent_turns else None,
            "last_entities": list(self._last_entities),
            "last_events": list(self._last_events),
            "recent_turns": list(self._recent_turns),
        }

    def understand(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Produce the complete semantic contract without persisting knowledge."""
        started = time.time()
        normalized = self.normalize(text)
        # INLINE CORRECTION (2026-09-11, scoped addition -- the "risky"
        # multi-fact/correction extraction item, kept deliberately
        # narrow and purely ADDITIVE so none of the existing, already
        # carefully-tuned extractors below need to change). A message
        # like "nahi galat hai, uska naam Samir hai" has a correction
        # marker glued onto the front of what is otherwise an ordinary
        # fact statement. Stripping just that marker before everything
        # else runs means EVERY extractor below (name, location,
        # preference, etc.) sees a clean fact clause and behaves
        # exactly as it already does for a plain statement -- no new
        # fact-extraction logic needed, just remove the noise around
        # it. is_inline_correction is returned in the result so Brain/
        # knowledge_builder can tag the resulting fact with real,
        # deliberate-overwrite confidence rather than treating it as
        # just another ambiguous restatement.
        #
        # MID-SENTENCE case added (still 2026-09-11): "mera naam UK
        # hai, nahi galat, Deepak hai" has the correction marker in the
        # MIDDLE, not the front -- the corrected value is whatever
        # comes AFTER the marker, and the clause BEFORE it is the
        # thing being superseded, not a second fact to also extract.
        # Only the post-marker portion is kept in that case (the
        # pre-marker clause is deliberately dropped from extraction --
        # keeping it would create a contradicting fact in the SAME
        # turn, which is exactly what the correction was trying to
        # avoid).
        _INLINE_CORRECTION_MARKER = re.compile(
            r"(?:^\s*|,\s*)(?:(?:nahi+n?|galat(?:\s+hai)?|arey\s+nahi+n?|not\s+correct|wrong)\s*[,:]?\s*)+", re.I
        )
        match = _INLINE_CORRECTION_MARKER.search(normalized)
        is_inline_correction = False
        if match:
            after = normalized[match.end():].strip()
            if after:
                normalized = after
                is_inline_correction = True
        external_context: Mapping[str, Any] = context or {}
        intent = self._detect_intent(normalized)
        language = self._detect_language(normalized)
        entities = self._extract_entities_structured(normalized)
        temporal = self._extract_temporal(normalized)
        references = self._resolve_references(normalized, entities, external_context)
        events = self._extract_events(normalized, temporal, entities)

        facts: List[SemanticFact] = []
        seen = set()
        # _favourite_facts runs before _generic_facts and both add to the
        # same `seen` dedup set below, so once a "mera favourite X Y hai"
        # statement is captured cleanly here, the generic catch-all's
        # duplicate (subject, predicate, value) key is skipped rather
        # than double-counted.
        name_results = list(self._name_facts(normalized))
        # A real, explicit ask: a single compound sentence ("meri
        # girlfriend ka naam Akanksha hai, wo Hamirpur mein rehti hai")
        # should become MULTIPLE precise facts, not one run-on value or
        # a single fact that silently drops the second clause. If
        # _name_facts found a THIRD-PARTY subject (girlfriend/friend/
        # etc, not "user"), that same subject is who a later "X mein
        # rehta/rehti hai" clause in the SAME sentence is about -- not
        # the user -- so the location gets correctly attributed rather
        # than either attributed to the wrong person or dropped.
        inherited_subject = next((f.subject for f in name_results if f.subject != "user"), None)
        if inherited_subject is None:
            # No same-sentence subject (e.g. this message is JUST "wo
            # Hamirpur mein rehti hai" on its own, said in a later turn
            # than "meri girlfriend ka naam Akanksha hai"). Fall back
            # to cross-turn pronoun resolution: if this sentence opens
            # with wo/woh/jo/jise and `references` (built above from
            # self._last_entities) resolved that pronoun to a
            # previously-seen non-"user" entity, attribute the location
            # to THAT entity instead of silently defaulting to "user".
            # Partial by design: this only reaches back one turn (via
            # _last_entities), not full multi-turn coreference.
            resolved = next(
                (r.get("resolved_to") for r in references
                 if r.get("mention") in ("wo", "woh", "jo", "jise") and r.get("resolved_to")),
                None,
            )
            resolved_text = str((resolved or {}).get("text", "")).strip()
            inherited_subject = resolved_text if resolved_text and resolved_text.lower() != "user" else "user"
        location_results = list(self._location_facts(normalized, inherited_subject))
        for generator in (iter(name_results), self._preference_facts(normalized), self._favourite_facts(normalized), self._generic_facts(normalized), iter(location_results)):
            for fact in generator:
                key = (fact.subject, fact.predicate, str(fact.value).lower())
                if key not in seen:
                    seen.add(key)
                    facts.append(fact)

        # Action/event statements must not be persisted as identity facts.
        # Example: "I am learning Python" -> learning_started event,
        # not identity("learning Python").
        if any(
            event.get("event_type") == "learning_started"
            for event in events
        ):
            facts = [
                fact for fact in facts
                if not (
                    fact.predicate == "identity"
                    and fact.value
                    and re.match(
                        r"^(?:learning|studying)\\s+",
                        str(fact.value),
                        re.I,
                    )
                )
            ]

        semantic_relations = self._extract_semantic_relations(events, temporal)
        # Prevent action/state statements from being stored as identity facts.
        # Example: "I am learning Python" must produce a learning_started event,
        # never identity("learning Python").
        if any(e.get("event_type") == "learning_started" for e in events):
            facts = [
                fact for fact in facts
                if not (
                    getattr(fact, "predicate", None) == "identity"
                    and str(getattr(fact, "value", "")).strip().lower()
                    == "learning python"
                )
            ]

        relations = [fact.as_dict() for fact in facts] + semantic_relations
        inferences = self._infer(events, references)
        confidence_values = [intent.get("confidence", 0.0)] + [e.get("confidence", 0.0) for e in entities] + [e.get("confidence", 0.0) for e in events]
        confidence = max(confidence_values or [0.0])

        result = {
            "version": self.VERSION,
            "text": str(text or ""),
            "normalized": normalized,
            "language": language,
            "intent": intent,
            "tokens": normalized.split() if normalized else [],
            "entities": entities,
            "references": references,
            "temporal": temporal,
            "events": events,
            "relations": relations,
            "fact_candidates": [fact.as_dict() for fact in facts],
            "inferences": inferences,
            "confidence": round(confidence, 3),
            "uncertainty": round(1.0 - confidence, 3),
            "context": self._build_context_snapshot(),
            "context_keys": sorted(external_context.keys()),
            "processing_ms": round((time.time() - started) * 1000.0, 3),
            "is_inline_correction": is_inline_correction,
        }

        self._last_entities = list(entities)
        self._last_events = list(events)
        self._recent_turns.append({
            "timestamp": time.time(),
            "normalized": normalized,
            "intent": intent,
            "entities": entities,
            "events": events,
            "temporal": temporal,
        })
        self._recent_turns = self._recent_turns[-self.max_context_turns:]
        return result
