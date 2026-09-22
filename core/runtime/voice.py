from __future__ import annotations

"""Voice I/O for JARVIS -- genuine text-to-speech (JARVIS speaks) and
speech-to-text (UK speaks to JARVIS), using Termux:API.

HONEST DEPENDENCY, STATED UP FRONT: this requires the separate
Termux:API *app* (not just the `termux-api` package) to be installed
from F-Droid or Play Store, in addition to `pkg install termux-api`
in Termux itself. Without both, termux-tts-speak/termux-speech-to-text
do not exist as commands -- this module detects that and degrades
gracefully (returns False / empty string) rather than crashing the
whole CLI, since voice is an OPTIONAL enhancement, never something
the rest of JARVIS should depend on to function.

This could NOT be tested end-to-end in the sandbox this was built in
(no real Android device/Termux environment available there) -- what
IS verified: the subprocess construction, timeout handling, and
graceful-degradation logic. The actual audio behavior needs
confirming on UK's real device.

VOICE QUALITY, NOT JUST "A" VOICE: Android's default TTS voice on most
devices genuinely does sound flat/robotic -- that is the phone's
built-in engine's baseline voice, not something JARVIS's own code
controls directly. What IS controllable, and genuinely helps: (1)
listing every voice/engine actually installed on THIS device via
`termux-tts-engines` -- many phones have more than one TTS engine
installed (Google's, Samsung's, etc.), and some sound noticeably
better/more natural than others -- and letting UK pick the best-
sounding one available, rather than always using whatever the system
default happens to be; (2) pitch/rate tuned toward a calmer, more
composed delivery (slightly lower pitch, unhurried rate) instead of
the default's flatter cadence, matching the steady, understated
character established for JARVIS earlier in this project. This
cannot manufacture a voice the device doesn't have installed --
finding and choosing the best AVAILABLE one is the honest, real
lever here.
"""

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

# Tuned by UK directly on-device with a dedicated tuner script, then
# further refined live via /voice pitch and /voice rate during actual
# use -- these are UK's own FINAL chosen values (0.55/1.1/hi-IN), not
# the tuner script's initial starting point (which was 1.35/1.15 and
# got explicitly reverted).
_DEFAULT_PITCH = 0.55
_DEFAULT_RATE = 1.1
_DEFAULT_LANG = "hi-IN"

_voice_config: Dict[str, Any] = {"engine": None, "voice": None, "pitch": _DEFAULT_PITCH, "rate": _DEFAULT_RATE, "lang": _DEFAULT_LANG}


def _load_shared_profile() -> None:
    """Pull pitch/rate/lang from config/voice.json.

    THE DRIFT BUG (fixed 2026-09-13). This module kept its settings in
    the in-memory dict above, while core/voice/jarvis_voice.py kept the
    real profile in config/voice.json. Two stores for one voice meant:
    changing pitch in the CLI did nothing to the web UI, changing it in
    the UI did nothing to the CLI, and BOTH were lost on restart because
    the dict was never written anywhere.

    config/voice.json is now the single source of truth; this dict is a
    cache of it.
    """
    try:
        from ...core.voice.jarvis_voice import load_profile  # type: ignore
    except Exception:
        try:
            from core.voice.jarvis_voice import load_profile  # type: ignore
        except Exception:
            return
    try:
        profile = load_profile()
        _voice_config["pitch"] = profile.pitch
        _voice_config["rate"] = profile.rate
        _voice_config["lang"] = profile.language
    except Exception:
        pass


_load_shared_profile()


def voice_available() -> bool:
    """True only if the actual termux-tts-speak binary is on PATH --
    never assumed, always checked, since Termux:API being installed is
    a real external dependency that may or may not be present."""
    return shutil.which("termux-tts-speak") is not None


def speech_input_available() -> bool:
    return shutil.which("termux-speech-to-text") is not None


def list_voices(timeout_seconds: float = 10.0) -> List[Dict[str, Any]]:
    """List every TTS engine+voice actually installed on this device,
    via termux-tts-engines. Returns [] (never raises) if Termux:API
    isn't installed or the call fails -- this is how UK finds out
    what's genuinely available to pick from, rather than guessing."""
    if shutil.which("termux-tts-engines") is None:
        return []
    try:
        result = subprocess.run(["termux-tts-engines"], timeout=timeout_seconds, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        parsed = json.loads(result.stdout)
        return parsed if isinstance(parsed, list) else []
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, Exception):
        return []


def set_voice(engine: Optional[str] = None, voice: Optional[str] = None, pitch: Optional[float] = None, rate: Optional[float] = None, lang: Optional[str] = None) -> None:
    """Persist a chosen engine/voice/pitch/rate/lang for future speak()
    calls this process lifetime. None for any field leaves that field
    unchanged from its current setting."""
    if engine is not None:
        _voice_config["engine"] = engine
    if voice is not None:
        _voice_config["voice"] = voice
    if pitch is not None:
        _voice_config["pitch"] = float(pitch)
    if rate is not None:
        _voice_config["rate"] = float(rate)
    if lang is not None:
        _voice_config["lang"] = lang

    # PERSIST. Previously this only mutated the in-memory dict, so every
    # /voice pitch change was forgotten on restart and never reached the
    # frontend at all.
    try:
        try:
            from core.voice.jarvis_voice import save_profile  # type: ignore
        except Exception:
            from ...core.voice.jarvis_voice import save_profile  # type: ignore
        changes: Dict[str, Any] = {}
        if pitch is not None:
            changes["pitch"] = float(pitch)
            changes["browser_pitch"] = float(pitch)
        if rate is not None:
            changes["rate"] = float(rate)
            changes["browser_rate"] = float(rate)
        if lang is not None:
            changes["language"] = lang
        if changes:
            save_profile(changes)
    except Exception:
        pass


def get_voice_config() -> Dict[str, Any]:
    # Re-read the shared file so a change made in the web UI is visible
    # here without restarting, and vice versa.
    _load_shared_profile()
    return dict(_voice_config)


def speak(text: str, timeout_seconds: float = 30.0) -> bool:
    """Speak text aloud via Android's TTS engine, using whatever
    engine/voice/pitch/rate is currently configured (see set_voice()).
    Returns True only on genuine success -- False (never an exception)
    if Termux:API isn't installed, the call times out, or anything
    else goes wrong. Text is truncated to a sane length first: TTS
    reading out a multi-paragraph response is a bad experience and can
    hang for a very long time on a phone."""
    if not text or not text.strip():
        return False
    if not voice_available():
        return False
    spoken_text = text.strip()
    if len(spoken_text) > 500:
        spoken_text = spoken_text[:497] + "..."
    cmd = ["termux-tts-speak"]
    if _voice_config.get("engine"):
        cmd += ["-e", str(_voice_config["engine"])]
    if _voice_config.get("voice"):
        cmd += ["-v", str(_voice_config["voice"])]
    cmd += ["-p", str(_voice_config.get("pitch", _DEFAULT_PITCH))]
    cmd += ["-r", str(_voice_config.get("rate", _DEFAULT_RATE))]
    if _voice_config.get("lang"):
        cmd += ["-l", str(_voice_config["lang"])]
    cmd.append(spoken_text)
    try:
        result = subprocess.run(cmd, timeout=timeout_seconds, capture_output=True)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError, Exception):
        return False


def _whisper_transcribe(audio_path: str, timeout_seconds: float = 20.0) -> Optional[str]:
    """Send a recorded audio file to Groq's Whisper transcription
    endpoint. Reuses the SAME GROQ_API_KEY env var (comma-separated,
    first key only here -- this is a rare fallback path, not worth
    the full rotation logic llm_bridge.py has for its much higher-
    volume chat calls) as the rest of JARVIS's LLM usage, so no new
    configuration is needed. Never raises."""
    api_key = (os.environ.get("GROQ_API_KEY") or os.environ.get("GROK_API_KEY") or "").split(",")[0].strip()
    if not api_key:
        return None
    try:
        import requests
        with open(audio_path, "rb") as audio_file:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (os.path.basename(audio_path), audio_file, "audio/wav")},
                data={"model": "whisper-large-v3-turbo"},
                timeout=timeout_seconds,
            )
        if response.status_code == 200:
            text = (response.json() or {}).get("text", "").strip()
            return text or None
        return None
    except Exception:
        return None


def _record_audio(timeout_seconds: float = 8.0) -> Optional[str]:
    """Capture raw audio via Termux:API's microphone recorder (a
    DIFFERENT command from termux-speech-to-text, which does its own
    capture+transcribe internally and gives no way to also get the raw
    audio out) -- needed because Whisper needs an actual audio FILE to
    transcribe, not just a text result. Returns the file path, or None
    if termux-microphone-record isn't available or recording fails."""
    if shutil.which("termux-microphone-record") is None:
        return None
    import tempfile
    audio_path = os.path.join(tempfile.gettempdir(), f"jarvis_listen_{int(time.time())}.wav")
    try:
        subprocess.run(
            ["termux-microphone-record", "-f", audio_path, "-l", str(int(timeout_seconds))],
            timeout=timeout_seconds + 3, capture_output=True,
        )
        subprocess.run(["termux-microphone-record", "-q"], timeout=5, capture_output=True)
        return audio_path if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0 else None
    except Exception:
        return None


def listen(timeout_seconds: float = 15.0, allow_whisper_fallback: bool = True) -> Optional[str]:
    """Capture one spoken utterance. Tries Termux's own local speech
    recognizer FIRST (zero network latency, works offline) -- only
    falls back to recording audio + Groq's Whisper API (better at
    mixed Hindi/English speech, but adds real network latency) if the
    local attempt genuinely fails AND allow_whisper_fallback is True.
    UK's explicit preference: local first, cloud only as a genuine
    fallback, never the default path. Never raises."""
    if not speech_input_available():
        if allow_whisper_fallback:
            audio_path = _record_audio(min(timeout_seconds, 10.0))
            if audio_path:
                text = _whisper_transcribe(audio_path)
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
                return text
        return None
    cmd = ["termux-speech-to-text"]
    if _voice_config.get("lang"):
        cmd += ["-l", str(_voice_config["lang"])]
    try:
        result = subprocess.run(
            cmd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if allow_whisper_fallback:
            audio_path = _record_audio(min(timeout_seconds, 10.0))
            if audio_path:
                text = _whisper_transcribe(audio_path)
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
                return text
        return None
    except (subprocess.TimeoutExpired, OSError, Exception):
        return None

