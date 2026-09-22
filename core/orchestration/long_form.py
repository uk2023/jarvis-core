from __future__ import annotations

"""LONG-FORM OUTPUT BEYOND ONE CALL'S CEILING.

UK's requirement: "mai chahu to 500 kya 50000 lines bhi generate karwa
saku aur le saku chat response me".

Why this file has to exist: raising max_output_tokens_per_turn (already
done, 2700 -> 16000) only widens ONE call. Every model has a hard
per-response cap regardless of budget, so a genuinely long document can
never arrive in a single completion no matter how much budget is left.
The honest answer is to generate it in pieces and assemble them -- which
is also how a person writes something long: outline first, then section
by section, each section aware of what came before.

Design decisions worth stating:

  * OUTLINE FIRST. Asking for "part 2 of 10" without a plan produces
    drift and repetition, because the model has no idea what part 3 is
    supposed to cover. One cheap planning call buys coherence across
    every later chunk.

  * EACH CHUNK SEES THE PLAN AND A TAIL OF WHAT EXISTS. Feeding the
    entire accumulated text back would blow the context window on long
    runs, so only the last ~1500 characters go back as continuity
    context -- enough to join cleanly without quadratic growth.

  * BUDGET IS CHECKED BEFORE EVERY CHUNK, not just at the start. A long
    run that exhausts the turn budget halfway must return what it has
    WITH an honest note, never a silent truncation that reads like a
    finished document.

  * PARTIAL OUTPUT IS ALWAYS RETURNED. If chunk 7 of 12 fails, the
    caller gets chunks 1-6 plus a clear statement of where it stopped.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event

# Roughly how much prose one generation call can reliably produce.
# Deliberately conservative: a chunk that gets truncated mid-sentence
# costs more (a broken seam) than one extra call.
TOKENS_PER_CHUNK = 3000
CHARS_PER_TOKEN = 4              # rough Hinglish/English average
CONTINUITY_TAIL_CHARS = 1500
MAX_CHUNKS = 40                  # hard stop -- prevents a runaway loop burning the whole budget


@dataclass
class LongFormResult:
    text: str
    chunks_generated: int
    chunks_planned: int
    complete: bool
    stopped_reason: Optional[str] = None
    outline: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chunks_generated": self.chunks_generated,
            "chunks_planned": self.chunks_planned,
            "complete": self.complete,
            "stopped_reason": self.stopped_reason,
            "outline": self.outline,
            "length_chars": len(self.text),
            "approx_lines": self.text.count("\n") + 1,
        }


def estimate_chunks_needed(requested_lines: Optional[int] = None,
                           requested_chars: Optional[int] = None) -> int:
    """How many calls a request of this size needs."""
    if requested_chars:
        total_chars = requested_chars
    elif requested_lines:
        total_chars = requested_lines * 60      # ~60 chars per line of prose
    else:
        return 1
    per_chunk_chars = TOKENS_PER_CHUNK * CHARS_PER_TOKEN
    return max(1, min(MAX_CHUNKS, -(-total_chars // per_chunk_chars)))


def _plan_outline(generate: Callable, system_prompt: str, request: str, chunk_count: int) -> List[str]:
    """One planning call. Failure is survivable -- a generic sectioning
    still beats generating blind, so this never raises."""
    if chunk_count <= 1:
        return []
    try:
        raw = str(generate(
            system_prompt=(
                "You are planning a long document before writing it. Return ONLY a numbered list of "
                f"exactly {chunk_count} section headings that together cover the request completely, "
                "in a sensible order, with no overlap between sections. No preamble, no commentary."
            ),
            user_input=f"Request: {request}\n\nGive exactly {chunk_count} section headings.",
            max_tokens=600,
            level="response_generation",
        )).strip()
    except Exception as exc:
        log_event("longform", f"outline planning failed, falling back to generic sections: {exc}", level="warning")
        return [f"Part {i + 1}" for i in range(chunk_count)]

    sections: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in (". ", ") ", "- ", ": "):
            head, found, tail = line.partition(sep)
            if found and head.strip().rstrip(".").isdigit():
                line = tail.strip()
                break
        if line:
            sections.append(line)
    if not sections:
        return [f"Part {i + 1}" for i in range(chunk_count)]
    # Normalise length: pad or trim so section count matches chunk count.
    while len(sections) < chunk_count:
        sections.append(f"Part {len(sections) + 1}")
    return sections[:chunk_count]


def generate_long_form(
    generate: Callable,
    *,
    system_prompt: str,
    request: str,
    chunk_count: int,
    budget_remaining: Optional[Callable[[], int]] = None,
) -> LongFormResult:
    """Generate a document across several calls and assemble it.

    `generate` is the same bridge method used everywhere else
    (llm.generate_response). `budget_remaining` is an optional callable
    returning tokens left this turn; when supplied, generation stops
    cleanly before overrunning rather than raising mid-document.
    """
    chunk_count = max(1, min(int(chunk_count), MAX_CHUNKS))
    outline = _plan_outline(generate, system_prompt, request, chunk_count)

    parts: List[str] = []
    stopped_reason: Optional[str] = None

    for index in range(chunk_count):
        # Budget check BEFORE the call, so we stop with a complete
        # sentence rather than a truncated one.
        if budget_remaining is not None:
            try:
                remaining = int(budget_remaining())
            except Exception:
                remaining = TOKENS_PER_CHUNK
            if remaining < TOKENS_PER_CHUNK // 2:
                stopped_reason = (
                    f"Turn ka token budget khatam ho gaya -- {index} section likhe ja chuke the "
                    f"{chunk_count} mein se. Baaki maang lo, agle turn mein wahin se continue karunga."
                )
                break

        heading = outline[index] if index < len(outline) else f"Part {index + 1}"
        continuity = ("".join(parts))[-CONTINUITY_TAIL_CHARS:] if parts else ""

        try:
            piece = str(generate(
                system_prompt=(
                    f"{system_prompt}\n\nYou are writing section {index + 1} of {chunk_count} of one "
                    "continuous document. Write ONLY this section's content -- do not repeat earlier "
                    "sections, do not summarise the whole document, and do not write a closing "
                    "paragraph unless this is the final section. Continue naturally from the text "
                    "shown; do not re-introduce the topic."
                ),
                user_input=(
                    f"Overall request: {request}\n\n"
                    f"Full outline: {'; '.join(outline) if outline else '(single section)'}\n\n"
                    f"This section: {heading}\n\n"
                    + (f"Text so far ends with:\n...{continuity}\n\n" if continuity else "")
                    + "Write this section now."
                ),
                max_tokens=TOKENS_PER_CHUNK,
                level="response_generation",
            )).strip()
        except Exception as exc:
            stopped_reason = (
                f"Section {index + 1} generate karte waqt dikkat aayi ({exc}). "
                f"Jo {index} section ban chuke the woh upar hain."
            )
            log_event("longform", f"chunk {index + 1}/{chunk_count} failed: {exc}", level="warning")
            break

        if not piece or piece.startswith("[LLM unavailable:") or piece.startswith("[Model Generation Error"):
            stopped_reason = f"Section {index + 1} khali aaya -- wahin ruk gaya."
            break

        if chunk_count > 1 and heading and not piece.lower().startswith(heading.lower()[:20]):
            parts.append(f"\n\n## {heading}\n\n{piece}")
        else:
            parts.append(("\n\n" if parts else "") + piece)

    text = "".join(parts).strip()
    generated = len(parts)
    complete = generated >= chunk_count and stopped_reason is None

    if stopped_reason and text:
        # Honest, visible boundary -- never a silent truncation that
        # reads like a finished document.
        text += f"\n\n---\n_{stopped_reason}_"

    log_event("longform", f"long-form generation: {generated}/{chunk_count} sections, complete={complete}", level="info")

    return LongFormResult(
        text=text, chunks_generated=generated, chunks_planned=chunk_count,
        complete=complete, stopped_reason=stopped_reason, outline=outline,
    )
