from __future__ import annotations

""""HAAN" / "OK" MUST MEAN SOMETHING -- WHAT JARVIS ITSELF JUST OFFERED.

UK's exact complaint, verified against his trace: he asks JARVIS to do
X, JARVIS answers and appends a question ("Web se check karun?", "Kya
hum iske capabilities test karein?"). UK replies "haan" or "theek hai".
The trace shows perception treating that as a brand-new, nearly
contentless turn -- confidence 0.0-0.2, intent {}, unknowns:
['meaning','language','intent'] -- because nothing in the pipeline ever
recorded what JARVIS itself was waiting to hear back.

Recent-turns context (recent_experiences, last_intent) already exists
and is real, but it is symmetric: it remembers what the USER said, not
what JARVIS asked FOR. A short affirmative has almost no content of its
own -- resolving it requires looking at JARVIS's own last utterance,
which nothing was doing.

THE FIX
=======
Every response is scanned for the shape of an offer or a question
("Web se check karun?", "Kya aap chahte hain ki...", a yes/no ending).
If found, it is stored as a pending_expectation with the SPECIFIC thing
being offered extracted out (not just "yes/no was asked" but "offered:
search the web for <topic>"). The next turn, if it is a short
affirmative/negative, is expanded using that stored expectation before
perception ever sees it -- so perception gets "haan, is baare mein web
search karo" instead of the bare "haan" that produced confidence 0.0 in
the trace.

This is intentionally narrow. It does not try to solve general
coreference -- it solves the one concrete, verified failure: JARVIS
asking a question and then not knowing what its own question was about.
"""

import re
from dataclasses import dataclass
from typing import Optional

# A short reply is almost certainly a bare acknowledgement rather than
# new content of its own -- the case that needs the expansion.
_SHORT_REPLY_WORD_LIMIT = 4

_AFFIRMATIVE = re.compile(
    r"^\s*(haan|han|ha|yes|yep|yup|ok|okay|theek hai|thik hai|sahi hai|sure|bilkul|zaroor)"
    r"[\s,]*(kar do|kar dijiye|kro|karo|karlo|kar dena)?\s*[.!]?\s*$",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"^\s*(nahi|nahin|no|nope|mat karo|rehne do|na)\s*[.!]?\s*$",
    re.IGNORECASE,
)

# Patterns that mean JARVIS's OWN last sentence was an offer or
# question worth remembering. Captures the substantive part after the
# marker so the expansion has something concrete to attach to, not just
# "yes to the question".
_OFFER_PATTERNS = [
    re.compile(r"(?:kya\s+(?:aap|main))?[^.?!]*\b(web se|internet se|online)\b[^.?!]*\bcheck\b[^.?!]*\?", re.IGNORECASE),
    re.compile(r"\bweb se[^.?!]*(?:check|dekh|verify)[^.?!]*\?", re.IGNORECASE),
    re.compile(r"kya\s+(?:hum|aap|main)[^.?!]*\?", re.IGNORECASE),
    re.compile(r"[^.?!]*\bchaheinge\b[^.?!]*\?", re.IGNORECASE),
    re.compile(r"[^.?!]*\bchahenge\b[^.?!]*\?", re.IGNORECASE),
    re.compile(r"[^.?!]+\?\s*$"),   # fallback: any sentence ending the reply in '?'
]


@dataclass
class PendingExpectation:
    """What JARVIS is waiting to hear back about."""
    jarvis_said: str          # JARVIS's full prior response, for context
    offer_text: str           # the specific question/offer extracted
    source_user_input: str    # what the user originally asked, for grounding

    def as_context_line(self) -> str:
        return (
            f'JARVIS ne pichhle turn mein yeh poocha/offer kiya tha: "{self.offer_text}" '
            f"-- yeh us baat ka context hai jis par user ab haan/nahi bol raha hai."
        )


def detect_offer(response_text: str) -> Optional[str]:
    """Does this response end in a question/offer worth remembering?
    Returns the extracted offer text, or None if the response was just
    a plain statement."""
    if not response_text or "?" not in response_text:
        return None
    text = response_text.strip()
    for pattern in _OFFER_PATTERNS:
        match = pattern.search(text)
        if match:
            extracted = match.group(0).strip()
            if len(extracted) >= 6:
                return extracted
    return None


def classify_short_reply(user_input: str) -> Optional[str]:
    """'affirmative', 'negative', or None if this is not a short bare
    reply at all (i.e. it has real content of its own and should be
    perceived normally, not expanded)."""
    text = (user_input or "").strip()
    if not text or len(text.split()) > _SHORT_REPLY_WORD_LIMIT:
        return None
    if _AFFIRMATIVE.match(text):
        return "affirmative"
    if _NEGATIVE.match(text):
        return "negative"
    return None


def expand_short_reply(user_input: str, pending: Optional[PendingExpectation]) -> str:
    """The actual fix: turn a bare 'haan' into something perception can
    work with, by attaching what JARVIS itself was asking about.

    Returns user_input UNCHANGED if there is nothing to expand against
    -- an expansion invented from nothing would be worse than the
    original low-confidence turn, because it would look confident while
    being wrong.
    """
    classification = classify_short_reply(user_input)
    if not classification or pending is None:
        return user_input

    if classification == "affirmative":
        return f"{user_input.strip()} -- {pending.offer_text}"
    return f"{user_input.strip()} -- (mana kiya: {pending.offer_text})"
