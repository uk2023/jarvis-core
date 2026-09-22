from __future__ import annotations

"""LIVE VOICE CALL -- continuous speaking companion.

UK (2026-09-13): "camera aur JARVIS ka speaker wala option live ho jana
chahiye, I need a call like feature, instant speaking companion like
ChatGPT."

WHAT THIS ACTUALLY DOES, AND WHAT IT DOES NOT
=============================================
Being precise here matters more than usual, because a voice feature
that half-works is indistinguishable from one that works until you are
mid-sentence and it stops.

REAL, and running in this file:
  * A call session with proper turn-taking state (listening -> thinking
    -> speaking -> listening), so the two sides do not talk over each
    other.
  * Energy-based voice activity detection over raw PCM: detects when
    speech starts, and when a pause is long enough to count as
    end-of-turn. No model needed, no download, works on Termux.
  * BARGE-IN: if the user starts speaking while JARVIS is talking,
    JARVIS stops. This is the single thing that makes a voice assistant
    feel like a call rather than a walkie-talkie, and it is why the
    state machine exists at all.
  * Adapter layer for STT and TTS that reports honestly which backends
    are actually present on the device.

NOT REAL, and deliberately not faked:
  * SPEAKER IDENTIFICATION ("kaun bol raha hai", "kitne log hain").
    This needs a speaker-embedding model (ECAPA/x-vector class) plus
    enrolment recordings per person. It is a genuine ML problem, not a
    wiring problem. The hooks are here and clearly marked; they return
    "unknown" rather than guessing, because a companion that confidently
    misidentifies who it is talking to would leak one person's private
    memory to another -- the exact thing user_memory.py exists to
    prevent.
  * CAMERA PRESENCE / FACE RECOGNITION. Same reasoning. A stub that
    returned a plausible face count would be worse than nothing.

STT/TTS on Termux come from termux-api if installed; Whisper is used if
present. If neither exists, capabilities() says so plainly instead of
the call silently producing nothing.
"""

import array
import asyncio
import base64
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event

def _rms(frame: bytes) -> int:
    """Root-mean-square level of a 16-bit PCM frame.

    Pure Python on purpose. This used `audioop.rms()`, which Python 3.14
    REMOVED (PEP 594 deprecated the module in 3.11 and deleted it in
    3.13+). My build runs 3.12, where audioop still exists and only
    warns -- so the import succeeded here and exploded on UK's Termux,
    taking the whole voice subsystem with it: the module-level import
    raised, /api/voice/capabilities returned 500, and the frontend saw
    "Failed to fetch" and disabled voice.

    A stdlib module that exists in my environment but not the target is
    exactly the class of bug that testing here cannot catch, so the
    dependency is removed rather than guarded.
    """
    if len(frame) < 2:
        return 0
    try:
        samples = array.array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return 0
        total = 0
        for s in samples:
            total += s * s
        return int((total / len(samples)) ** 0.5)
    except Exception:
        return 0


SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2                      # 16-bit PCM
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * SAMPLE_WIDTH * FRAME_MS / 1000)

# Tuning. These are the numbers that decide whether the call feels
# natural or maddening, so they are named rather than buried.
SILENCE_RMS_THRESHOLD = 500           # below this, treat as silence
SPEECH_FRAMES_TO_START = 5            # ~100ms of speech to open a turn
SILENCE_FRAMES_TO_END = 35            # ~700ms pause ends the user's turn
BARGE_IN_FRAMES = 6                   # ~120ms of speech interrupts JARVIS
MAX_TURN_SECONDS = 30

CALL_AUDIO_DIR = Path("data/call_audio")


class CallState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDED = "ended"


def capabilities() -> Dict[str, Any]:
    """What voice support this device ACTUALLY has, checked at runtime.

    Reported honestly so the UI can say "STT missing" rather than
    presenting a working-looking call that transcribes nothing.
    """
    has_termux_mic = shutil.which("termux-microphone-record") is not None
    has_termux_tts = shutil.which("termux-tts-speak") is not None
    has_whisper = False
    try:
        import whisper  # noqa: F401
        has_whisper = True
    except Exception:
        try:
            import faster_whisper  # noqa: F401
            has_whisper = True
        except Exception:
            has_whisper = False

    # UK runs termux_bridge.py in Termux proper, OUTSIDE this proot.
    # Inside proot no termux-api binary exists, so the direct checks
    # above are always False on his setup -- the bridges on localhost
    # ARE the capability, and ignoring them is why voice reported
    # "unavailable" on a device where it worked.
    bridge = {"tts_available": False, "stt_available": False}
    try:
        from .termux_bridge_client import bridge_status
        bridge = bridge_status()
    except Exception:
        pass

    stt_ok = has_whisper or has_termux_mic or bridge.get("stt_available", False)
    return {
        "bridge": bridge,
        "stt_available": stt_ok,
        "tts_available": has_termux_tts or bridge.get("tts_available", False),
        "whisper": has_whisper,
        "termux_tts": has_termux_tts,
        "termux_mic": has_termux_mic,
        "browser_fallback": True,
        # These two are stated explicitly so nothing downstream assumes
        # they exist. See module docstring.
        "speaker_identification": False,
        "camera_presence": False,
        "notes": (
            "Speaker identification aur camera presence abhi NAHI hai -- unke liye "
            "embedding model chahiye jo abhi install nahi hai. Jab tak nahi hai, JARVIS "
            "'unknown speaker' bolega, andaza nahi lagayega."
        ),
    }


@dataclass
class CallTurn:
    speaker: str                      # "user" | "jarvis"
    text: str
    at: float = field(default_factory=time.time)
    interrupted: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"speaker": self.speaker, "text": self.text, "at": self.at,
                "interrupted": self.interrupted}


class VoiceActivityDetector:
    """Energy-based VAD over 20ms PCM frames.

    Deliberately simple. A neural VAD would be more accurate in noise,
    but it would also be one more model to install before the call works
    at all -- and this runs on a phone. If it proves too noisy in
    practice, the threshold is one constant above.
    """

    def __init__(self) -> None:
        self.speech_run = 0
        self.silence_run = 0
        self.in_speech = False

    def feed(self, frame: bytes) -> Dict[str, Any]:
        if len(frame) < 2:
            return {"speech": self.in_speech, "event": None}
        try:
            rms = _rms(frame)
        except Exception:
            return {"speech": self.in_speech, "event": None}

        loud = rms >= SILENCE_RMS_THRESHOLD
        event = None

        if loud:
            self.speech_run += 1
            self.silence_run = 0
            if not self.in_speech and self.speech_run >= SPEECH_FRAMES_TO_START:
                self.in_speech = True
                event = "speech_start"
        else:
            self.silence_run += 1
            self.speech_run = 0
            if self.in_speech and self.silence_run >= SILENCE_FRAMES_TO_END:
                self.in_speech = False
                event = "speech_end"

        return {"speech": self.in_speech, "event": event, "rms": rms}

    def reset(self) -> None:
        self.speech_run = 0
        self.silence_run = 0
        self.in_speech = False


def transcribe(pcm: bytes) -> Dict[str, Any]:
    """PCM -> text. Returns honestly when no backend exists."""
    caps = capabilities()
    if not pcm:
        return {"text": "", "ok": False, "reason": "empty audio"}

    if caps["whisper"]:
        try:
            import wave
            CALL_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            path = CALL_AUDIO_DIR / f"turn_{uuid.uuid4().hex[:8]}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(SAMPLE_WIDTH)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(pcm)
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("base", device="cpu", compute_type="int8")
                segments, _ = model.transcribe(str(path), language=None)
                text = " ".join(s.text for s in segments).strip()
            except Exception:
                import whisper
                model = whisper.load_model("base")
                text = str(model.transcribe(str(path)).get("text", "")).strip()
            path.unlink(missing_ok=True)
            return {"text": text, "ok": bool(text), "engine": "whisper"}
        except Exception as exc:
            log_event("voice", f"whisper transcription failed: {exc}", level="warning")
            return {"text": "", "ok": False, "reason": f"whisper failed: {exc}"}

    return {
        "text": "", "ok": False,
        "reason": ("Is device pe STT backend nahi hai. Browser ka speech recognition "
                   "use karo, ya whisper install karo."),
    }


def speak(text: str, *, pitch: float = 0.55, rate: float = 1.1,
          lang: str = "hi-IN") -> Dict[str, Any]:
    """Text -> speech via Termux TTS. Non-blocking; returns the handle so
    the caller can kill it for barge-in."""
    if not (text or "").strip():
        return {"ok": False, "reason": "empty text"}
    if not shutil.which("termux-tts-speak"):
        return {"ok": False, "reason": "termux-tts-speak nahi mila -- browser TTS use karo.",
                "fallback": "browser"}
    try:
        proc = subprocess.Popen(
            ["termux-tts-speak", "-l", lang, "-p", str(pitch), "-r", str(rate), text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "engine": "termux-tts", "pid": proc.pid, "_proc": proc}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def identify_speaker(pcm: bytes) -> Dict[str, Any]:
    """Placeholder, and honest about it.

    Returns unknown ALWAYS. It does not guess, and it must not start
    guessing later without enrolment, because per-user memory is keyed
    on identity: a wrong guess here would hand one person's private
    facts to another. Wiring this to a real embedding model is a
    deliberate, separate piece of work.
    """
    return {
        "speaker": "unknown",
        "confidence": 0.0,
        "implemented": False,
        "note": ("Speaker identification abhi implement nahi hai. Iske liye enrolment "
                 "recordings + embedding model chahiye. Tab tak JARVIS session ke login "
                 "se hi jaanta hai ki kaun baat kar raha hai."),
    }


class CallSession:
    """One live call. Owns turn-taking and barge-in."""

    def __init__(self, *, on_event: Callable[[Dict[str, Any]], Any],
                 speaker_role: str = "user", username: Optional[str] = None):
        self.id = uuid.uuid4().hex[:12]
        self.state = CallState.IDLE
        self.on_event = on_event
        self.vad = VoiceActivityDetector()
        self.buffer = bytearray()
        self.turns: List[CallTurn] = []
        self.speaker_role = speaker_role
        self.username = username
        self.started_at = time.time()
        self._tts_proc = None
        self._barge_frames = 0

    async def _emit(self, event: Dict[str, Any]) -> None:
        try:
            result = self.on_event({**event, "session": self.id, "state": self.state.value})
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            log_event("voice", f"call event emit failed: {exc}", level="warning")

    def _stop_tts(self) -> None:
        """Kill in-flight speech. This is barge-in -- without it the call
        feels like a walkie-talkie."""
        if self._tts_proc is not None:
            try:
                self._tts_proc.terminate()
            except Exception:
                pass
            self._tts_proc = None
        if shutil.which("termux-tts-speak"):
            try:
                subprocess.run(["pkill", "-f", "termux-tts-speak"],
                               capture_output=True, timeout=2)
            except Exception:
                pass

    async def start(self) -> None:
        self.state = CallState.LISTENING
        caps = capabilities()
        await self._emit({"type": "call_started", "capabilities": caps})
        if not caps["stt_available"] or not caps["tts_available"]:
            # Say this at the START, not after the user has spoken into
            # a void for thirty seconds.
            await self._emit({
                "type": "capability_warning",
                "stt": caps["stt_available"], "tts": caps["tts_available"],
                "message": ("Is device pe "
                            + ("STT " if not caps["stt_available"] else "")
                            + ("TTS " if not caps["tts_available"] else "")
                            + "missing hai -- browser fallback use hoga."),
            })

    async def feed_audio(self, chunk: bytes, respond: Callable) -> None:
        """Feed raw PCM from the client. Drives the whole state machine."""
        if self.state in (CallState.ENDED, CallState.IDLE):
            return

        for i in range(0, len(chunk), FRAME_BYTES):
            frame = chunk[i:i + FRAME_BYTES]

            # BARGE-IN: user speaking while JARVIS speaks -> stop JARVIS.
            if self.state == CallState.SPEAKING:
                try:
                    if _rms(frame) >= SILENCE_RMS_THRESHOLD:
                        self._barge_frames += 1
                    else:
                        self._barge_frames = 0
                except Exception:
                    continue
                if self._barge_frames >= BARGE_IN_FRAMES:
                    self._stop_tts()
                    self._barge_frames = 0
                    if self.turns and self.turns[-1].speaker == "jarvis":
                        self.turns[-1].interrupted = True
                    self.state = CallState.LISTENING
                    self.vad.reset()
                    self.buffer.clear()
                    await self._emit({"type": "interrupted",
                                      "note": "Aap bol pade -- JARVIS chup ho gaya."})
                continue

            if self.state != CallState.LISTENING:
                continue

            result = self.vad.feed(frame)
            if result["event"] == "speech_start":
                self.buffer.clear()
                await self._emit({"type": "user_speaking"})
            if result["speech"]:
                self.buffer.extend(frame)
                if len(self.buffer) > SAMPLE_RATE * SAMPLE_WIDTH * MAX_TURN_SECONDS:
                    await self._end_user_turn(respond)
            elif result["event"] == "speech_end":
                await self._end_user_turn(respond)

    async def _end_user_turn(self, respond: Callable) -> None:
        pcm = bytes(self.buffer)
        self.buffer.clear()
        self.vad.reset()
        if len(pcm) < FRAME_BYTES * 10:
            return                     # too short to be a real turn

        self.state = CallState.THINKING
        await self._emit({"type": "transcribing"})

        stt = transcribe(pcm)
        if not stt.get("ok"):
            self.state = CallState.LISTENING
            await self._emit({"type": "stt_failed", "reason": stt.get("reason")})
            return

        text = stt["text"]
        self.turns.append(CallTurn(speaker="user", text=text))
        await self._emit({"type": "user_said", "text": text,
                          "speaker_identity": identify_speaker(pcm)})

        try:
            reply = respond(text)
            if asyncio.iscoroutine(reply):
                reply = await reply
            reply = str(reply or "").strip()
        except Exception as exc:
            reply = f"Maaf kijiye sir, jawab banate waqt dikkat aayi: {exc}"

        self.turns.append(CallTurn(speaker="jarvis", text=reply))
        self.state = CallState.SPEAKING
        await self._emit({"type": "jarvis_said", "text": reply})

        spoken = speak(reply)
        self._tts_proc = spoken.get("_proc")
        if not spoken.get("ok"):
            # No device TTS: tell the client to speak it in the browser
            # rather than silently producing nothing.
            await self._emit({"type": "speak_in_browser", "text": reply,
                              "reason": spoken.get("reason")})

        # Return to listening once speech finishes, unless barge-in
        # already moved us there.
        if self._tts_proc is not None:
            async def _wait_done(proc):
                while proc.poll() is None:
                    await asyncio.sleep(0.1)
                if self.state == CallState.SPEAKING:
                    self.state = CallState.LISTENING
                    self.vad.reset()
                    await self._emit({"type": "listening"})
            asyncio.create_task(_wait_done(self._tts_proc))
        else:
            self.state = CallState.LISTENING
            await self._emit({"type": "listening"})

    async def end(self) -> Dict[str, Any]:
        self._stop_tts()
        self.state = CallState.ENDED
        summary = {
            "session": self.id,
            "duration_s": round(time.time() - self.started_at, 1),
            "turns": [t.as_dict() for t in self.turns],
            "turn_count": len(self.turns),
        }
        await self._emit({"type": "call_ended", **summary})
        return summary
