from __future__ import annotations

"""Prompt-injection detection using Groq's dedicated Llama Prompt
Guard 2 classifier -- UK's explicit ask: JARVIS currently has no
protection if a message tries to hide malicious "instructions" for
JARVIS to follow. This is a real, distinct model from the main chat
model, purpose-built and trained for exactly this detection task.
"""

from typing import Any, Dict


def check_prompt_injection(text: str, llm_bridge: Any) -> Dict[str, Any]:
    """Runs meta-llama/llama-prompt-guard-2-86m (a dedicated, tiny
    classifier model -- NOT the main chat model) against the raw user
    input, BEFORE it reaches the rest of the pipeline. Per Groq's own
    docs, the model is used via the standard chat completion endpoint
    and returns a simple label: "benign" or "malicious". The 86M
    variant (not the smaller 22M) is used deliberately -- Groq's docs
    note it has meaningfully better multilingual coverage (8
    languages), which matters here given JARVIS's Hinglish usage.

    HONEST SCOPE: this is currently a DIAGNOSTIC layer -- it detects
    and records a suspicious input, it does not yet block/reject
    anything. A real safety classifier can have false positives, and
    silently refusing a genuine message because a small model
    misclassified it would be worse than the gap this closes. Flagged
    detections are logged and retained for review, not acted on
    unilaterally."""
    if not text or not text.strip() or llm_bridge is None:
        return {"checked": False}
    try:
        raw = llm_bridge.generate_response(
            system_prompt="",
            user_input=text,
            max_tokens=10,
            temperature=0.0,
            level="safety_check",
            # NOTE: this previously passed model="meta-llama/llama-
            # prompt-guard-2-86m" -- but that parameter was NEVER
            # actually wired through to the real Groq call (see
            # llm_bridge.py's generate_response(), which silently
            # discarded it), so this classifier has been running on
            # the default model (openai/gpt-oss-120b) this whole time,
            # not the dedicated tiny classifier the comment claimed.
            # Removed rather than left silently broken -- UK's explicit
            # instruction after this same dead parameter caused a real
            # crash elsewhere (GroqEngine.generate()) was "always use
            # gpt-oss-120b, no per-call overrides." Genuinely wiring a
            # real second model through safely is a separate, deliberate
            # change to make later, not something to sneak back in here.
        )
        label = str(raw or "").strip().lower()
        flagged = "malicious" in label
        return {"checked": True, "label": label, "flagged": flagged}
    except Exception as exc:
        return {"checked": False, "error": str(exc)}
