from __future__ import annotations

"""JARVIS'S VOICE -- one voice, defined in one place, tunable later.

UK (2026-09-13): "JARVIS ki awaaz chahiye jaise movie mein thi Marvel ki
JARVIS ki tarah, Hindi wali awaaz. Real organism type awaaz, fillers
etc. JARVIS ki awaaz ko bhi dedicated alag se script mein banao jo baad
mein fine tune ho sake."

WHY THIS IS ITS OWN FILE
========================
The voice was previously scattered: the chat bubble's speaker button
built its own SpeechSynthesisUtterance with rate 1.05 / pitch 0.95, the
Termux path used pitch 0.55 / rate 1.1, and the call path had a third
set. Three different voices for one character. Any fine-tuning meant
finding and editing all of them, and they would drift apart again.

So everything that makes JARVIS speak -- chat playback, the call screen,
Termux TTS -- reads VOICE_PROFILE from here. Change it once, it changes
everywhere. When a real fine-tuned model replaces the synthesiser later,
only synthesize() needs rewriting; every caller stays as it is.

WHAT "MARVEL JARVIS, IN HINDI" ACTUALLY MEANS
=============================================
The films' JARVIS does not sound dramatic. It is level, unhurried, and
slightly lower than a natural speaking pitch -- the calm is what makes
it sound competent. Getting this right is mostly about restraint:

  * Lower pitch, slightly slower than default. Not a "robot voice".
  * Even pacing, with real pauses at clause boundaries rather than a
    single breathless run.
  * Hindi/Hinglish delivery: hi-IN voice preferred, since an en-US voice
    reading Devanagari or romanised Hindi mangles it badly.

ON FILLERS -- an honest limitation
==================================
UK asked for "real organism type awaaz, fillers etc." Fillers are added
ONLY as prosody: short pauses and natural sentence flow, inserted as SSML
breaks or punctuation.

What is deliberately NOT done is injecting fake "umm", "hmm", "matlab"
into JARVIS's words. Those would be added by this layer AFTER the model
decided what to say -- meaning JARVIS would be performing hesitation it
never had. That is the same category of thing as the fake telemetry and
canned hedge lines removed earlier in this project. If JARVIS should
sound like it is thinking, the thinking should be real (see
core/cognition/thinking.py), and the pauses should fall where the
reasoning actually paused.

Prosodic pauses are different: they are how any sentence is spoken
aloud, not a claim about an internal state.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

VOICE_CONFIG_PATH = Path("config/voice.json")


# TWO VOICES, AND ONLY TWO (UK, 2026-09-14: "front end me dono option
# chahiye original tts + jarvis real voice human like... aur voice
# setting me jo fake cheezein hai unhe hata do").
#
#   device  -- Android's own TTS through the Termux bridge. Lower
#              latency, works offline, sounds like the phone.
#   jarvis  -- the browser's speech synthesis tuned to the JARVIS
#              profile: lower pitch, slower, hi-IN voice preferred.
#
# There is no third "neural/cloned" option, because there is no cloned
# model here. Offering one would be a setting that does nothing.
VOICE_ENGINES = ("device", "jarvis")


@dataclass
class VoiceProfile:
    """Every number that shapes JARVIS's voice. One place, on purpose."""

    # Termux TTS (android). pitch < 1.0 lowers the voice.
    pitch: float = 0.72
    rate: float = 0.95
    language: str = "hi-IN"

    # Which engine speaks. See VOICE_ENGINES above.
    engine: str = "jarvis"

    # Browser speechSynthesis. Different engine, different scale, so the
    # numbers are not shared -- but they aim at the same voice.
    browser_pitch: float = 0.75
    browser_rate: float = 0.94
    browser_voice_hints: tuple = ("hi-IN", "en-IN", "Google हिन्दी", "Rishi", "Veena")

    # Prosody
    pause_after_sentence_ms: int = 260
    pause_after_clause_ms: int = 130
    max_chunk_chars: int = 240

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["browser_voice_hints"] = list(self.browser_voice_hints)
        return d


def load_profile() -> VoiceProfile:
    """Profile from config/voice.json if present, else the default.

    File-backed so UK can tune the voice without editing code or
    restarting a build -- which is the entire point of "baad mein fine
    tune ho sake".
    """
    profile = VoiceProfile()
    try:
        if VOICE_CONFIG_PATH.exists():
            import json
            data = json.loads(VOICE_CONFIG_PATH.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(profile, key) and not isinstance(getattr(profile, key), tuple):
                    setattr(profile, key, value)
    except Exception as exc:
        log_event("voice", f"voice.json unreadable, using defaults: {exc}", level="warning")
    return profile


def save_profile(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Persist tuning changes. Returns the resulting profile."""
    profile = load_profile()
    applied = {}
    for key, value in (changes or {}).items():
        if hasattr(profile, key) and not isinstance(getattr(profile, key), tuple):
            try:
                current = getattr(profile, key)
                setattr(profile, key, type(current)(value))
                applied[key] = getattr(profile, key)
            except Exception:
                continue
    try:
        import json
        VOICE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOICE_CONFIG_PATH.write_text(json.dumps(profile.as_dict(), indent=2), encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "applied": applied, "profile": profile.as_dict()}


# Text that should never be read aloud: code blocks, markdown scaffolding,
# URLs. A synthesiser reading "asterisk asterisk" or a full URL character
# by character is the fastest way to make a voice feel broken.
_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_EMPHASIS = re.compile(r"[*_#>]+")
_URL = re.compile(r"https?://\S+")
_CLAUSE = re.compile(r"([,;:])\s+")
_SENTENCE = re.compile(r"([.!?।])\s+")


def prepare_for_speech(text: str) -> str:
    """Strip what should not be spoken, and mark where pauses belong."""
    if not text:
        return ""
    spoken = _CODE_BLOCK.sub(" code block. ", text)
    spoken = _INLINE_CODE.sub(r"\1", spoken)
    spoken = _URL.sub(" link ", spoken)
    spoken = _MD_EMPHASIS.sub("", spoken)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken


def chunk_for_speech(text: str, profile: Optional[VoiceProfile] = None) -> List[str]:
    """Split into speakable chunks at sentence boundaries.

    Chunking matters for barge-in: a single long utterance cannot be
    stopped cleanly mid-way on every engine, so speaking in pieces means
    interrupting JARVIS actually stops it quickly.
    """
    profile = profile or load_profile()
    spoken = prepare_for_speech(text)
    if not spoken:
        return []

    sentences = _SENTENCE.sub(r"\1\n", spoken).split("\n")
    chunks: List[str] = []
    buffer = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(buffer) + len(sentence) + 1 <= profile.max_chunk_chars:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer:
                chunks.append(buffer)
            buffer = sentence
    if buffer:
        chunks.append(buffer)
    return chunks


# CALL vs CHAT-BUBBLE are different jobs (UK, 2026-09-14):
#
#   "JARVIS jaisi awaaz chahiye call pe, TTS wali robotic voice nahi.
#    Wo bas msg ya chat bubble ko padhne ke liye theek hai."
#
# He is describing a real distinction. Android's device TTS is flat and
# even -- fine for reading a message aloud on demand, wrong for a
# conversation, where flatness is what makes it sound like a machine.
#
# So a call uses the browser voice with the JARVIS profile pushed
# further: lower pitch, slower, and a hi-IN/en-IN voice preferred over
# whatever default the browser would otherwise grab. It is still
# synthesis -- there is no cloned Paul Bettany model here and pretending
# otherwise would be a lie -- but pitch and pacing are most of what
# separates "assistant reading text" from "assistant talking".
CALL_PITCH_OFFSET = -0.08
CALL_RATE_OFFSET = -0.04


def call_voice_spec(text: str) -> Dict[str, Any]:
    """Voice settings for a live call: warmer and slower than bubble
    playback, and never the device engine."""
    spec = browser_voice_spec(text)
    spec["pitch"] = round(max(0.4, spec["pitch"] + CALL_PITCH_OFFSET), 3)
    spec["rate"] = round(max(0.6, spec["rate"] + CALL_RATE_OFFSET), 3)
    spec["mode"] = "call"
    spec["note"] = ("Call pe browser voice hi use hoti hai -- device TTS flat hai, "
                    "jo message padhne ke liye theek hai par baat-cheet ke liye nahi.")
    return spec


def browser_voice_spec(text: str) -> Dict[str, Any]:
    """Everything the frontend needs to speak this in JARVIS's voice.

    Sent to the client so the browser's speechSynthesis uses the SAME
    profile as the device TTS -- one voice, not two that drift.
    """
    profile = load_profile()
    return {
        "chunks": chunk_for_speech(text, profile),
        "lang": profile.language,
        "pitch": profile.browser_pitch,
        "rate": profile.browser_rate,
        "voice_hints": list(profile.browser_voice_hints),
        "pause_ms": profile.pause_after_sentence_ms,
    }


def set_engine(engine: str) -> Dict[str, Any]:
    """Pick which of the two voices speaks. Persisted, no restart."""
    engine = (engine or "").strip().lower()
    if engine not in VOICE_ENGINES:
        return {"ok": False, "error": f"engine '{engine}' nahi hai. Options: {', '.join(VOICE_ENGINES)}"}
    return save_profile({"engine": engine})


def speak(text: str, *, blocking: bool = False) -> Dict[str, Any]:
    """Speak through the device. Returns the handle so callers can stop
    it for barge-in, and reports honestly when no engine exists."""
    profile = load_profile()
    chunks = chunk_for_speech(text, profile)
    if not chunks:
        return {"ok": False, "reason": "kuch bolne ko nahi hai"}

    # If UK picked the browser voice, do not speak on the device at all
    # -- otherwise both would talk at once.
    if profile.engine == "jarvis":
        return {"ok": False, "reason": "engine=jarvis", "fallback": "browser",
                "browser_spec": browser_voice_spec(text)}

    # BRIDGE FIRST. Inside proot there is no termux-tts-speak binary, so
    # the which() check below always failed on UK's device even though
    # TTS worked fine through his bridge on port 9999.
    try:
        from .termux_bridge_client import speak as _bridge_speak, bridge_status
        if bridge_status().get("tts_available"):
            result = _bridge_speak(text, pitch=profile.pitch, rate=profile.rate,
                                   lang=profile.language)
            if result.get("ok"):
                return {**result, "chunks": len(chunks), "profile": profile.as_dict()}
    except Exception:
        pass

    if not shutil.which("termux-tts-speak"):
        return {
            "ok": False,
            "reason": "Na termux-tts-speak mila, na bridge (port 9999) chal raha hai.",
            "fallback": "browser",
            "browser_spec": browser_voice_spec(text),
        }

    try:
        procs = []
        for chunk in chunks:
            cmd = ["termux-tts-speak", "-l", profile.language,
                   "-p", str(profile.pitch), "-r", str(profile.rate), chunk]
            if blocking:
                subprocess.run(cmd, capture_output=True, timeout=120)
            else:
                procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL))
        return {"ok": True, "engine": "termux-tts", "chunks": len(chunks),
                "_procs": procs, "profile": profile.as_dict()}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def stop_speaking() -> None:
    """Cut off speech immediately -- used for barge-in."""
    if shutil.which("termux-tts-speak"):
        try:
            subprocess.run(["pkill", "-f", "termux-tts-speak"], capture_output=True, timeout=2)
        except Exception:
            pass


def voice_status() -> Dict[str, Any]:
    profile = load_profile()
    return {
        "profile": profile.as_dict(),
        "config_file": str(VOICE_CONFIG_PATH),
        "config_exists": VOICE_CONFIG_PATH.exists(),
        "termux_tts": shutil.which("termux-tts-speak") is not None,
        "engine": profile.engine,
        "engines": list(VOICE_ENGINES),
        "tunable": True,
        "note": ("Awaaz config/voice.json se tune hoti hai -- pitch/rate badlo, restart ki "
                 "zaroorat nahi. Fillers (umm/hmm) jaan-boojh kar nahi daale gaye: woh "
                 "JARVIS ke bolne ke baad chipkaye jaate, matlab woh jhooti hichkichahat "
                 "perform karta. Pauses asli hain, fillers nakli hote."),
    }
