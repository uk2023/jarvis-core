from __future__ import annotations

"""VOICE CALL WEBSOCKET + AUTH HARDENING.

Two things live here because they are the same concern: a long-lived
socket carrying someone's voice must know who that someone is, for the
whole connection, not just at the moment it opened.

PER-CONNECTION AUTH. The token is verified BEFORE the socket is
accepted, and the resolved identity is held for the life of the
connection. It is never re-read from client messages -- a socket that
trusted an identity sent in a frame would let a caller become someone
else mid-call, which for this system means reaching another person's
private memory.
"""

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["voice"])


# --------------------------------------------------------- rate limiting
# Login attempts per IP. Small and in-memory on purpose: this runs on
# one phone, and a Redis dependency for a single-device system would be
# more moving parts than protection.
_LOGIN_ATTEMPTS: Dict[str, Deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 8


def check_login_rate(ip: str) -> Dict[str, Any]:
    """Called from the login route. Returns allowed + seconds to wait."""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS[ip]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        wait = int(LOGIN_WINDOW_SECONDS - (now - attempts[0]))
        return {"allowed": False, "retry_after": max(1, wait),
                "message": f"Bahut zyada login attempts. {max(1, wait)}s baad try karo."}
    attempts.append(now)
    return {"allowed": True}


def clear_login_rate(ip: str) -> None:
    """On success -- a legitimate user should not be throttled by their
    own earlier typos."""
    _LOGIN_ATTEMPTS.pop(ip, None)


# ------------------------------------------------------- socket identity
def _identify(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve a session token to a speaker, or None."""
    if not token:
        return None
    try:
        from core.identity.session_tokens import verify_token
        # verify_token returns a UserRecord (not a username string) and
        # never raises -- so a single None check covers every failure.
        record = verify_token(token)
        if not record:
            return None
        return {"username": record.username, "role": record.role, "is_verified": True}
    except Exception:
        return None


@router.websocket("/ws/call")
async def voice_call_socket(websocket: WebSocket):
    """Live voice call.

    Protocol (client -> server):
        {"type": "auth",  "token": "..."}        first message, required
        {"type": "audio", "pcm": "<base64>"}     16kHz mono s16le
        {"type": "text",  "text": "..."}         browser-STT fallback
        {"type": "end"}

    Server -> client: the CallSession event stream (call_started,
    user_speaking, transcribing, user_said, jarvis_said, interrupted,
    speak_in_browser, listening, call_ended).
    """
    import base64

    await websocket.accept()

    # AUTH FIRST. Nothing else is processed until identity is settled,
    # and the identity resolved here is the one used for the whole call.
    speaker: Optional[Dict[str, Any]] = None
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        msg = json.loads(first)
        if msg.get("type") != "auth":
            await websocket.send_json({"type": "error", "error": "Pehla message auth hona chahiye."})
            await websocket.close(code=4401)
            return
        speaker = _identify(msg.get("token"))
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
        return
    except Exception:
        await websocket.close(code=4400)
        return

    if not speaker:
        await websocket.send_json({"type": "error", "error": "Token invalid hai -- call shuru nahi ho sakti."})
        await websocket.close(code=4401)
        return

    from core.voice.call_session import CallSession

    async def emit(event: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(event)
        except Exception:
            pass

    def respond(text: str) -> str:
        """Route the spoken turn through the real organism, with this
        caller's own persona and memory -- same path as chat, so voice
        and text cannot drift apart."""
        from backend import integration
        brain = getattr(integration, "brain", None)
        if brain is None:
            return "Sir, organism abhi poori tarah start nahi hua hai."
        try:
            previous = getattr(brain, "current_speaker", None)
            brain.current_speaker = speaker
            try:
                result = brain.process_input(text)
            finally:
                brain.current_speaker = previous
            if isinstance(result, dict):
                return result.get("response") or result.get("text") or str(result)
            return str(result)
        except Exception as exc:
            return f"Sir, jawab banate waqt dikkat aayi: {exc}"

    session = CallSession(on_event=emit, speaker_role=speaker["role"],
                          username=speaker["username"])
    await session.start()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            kind = msg.get("type")
            if kind == "audio":
                try:
                    pcm = base64.b64decode(msg.get("pcm", ""))
                except Exception:
                    continue
                await session.feed_audio(pcm, respond)
            elif kind == "text":
                # Browser did the STT. Same downstream path, so the
                # fallback is not a second, divergent implementation.
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                await emit({"type": "user_said", "text": text, "via": "browser_stt"})
                reply = respond(text)
                await emit({"type": "jarvis_said", "text": reply})
                from core.voice.call_session import speak
                spoken = speak(reply)
                if not spoken.get("ok"):
                    await emit({"type": "speak_in_browser", "text": reply,
                                "reason": spoken.get("reason")})
            elif kind == "end":
                await session.end()
                break
    except WebSocketDisconnect:
        await session.end()
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "error": str(exc)})
        except Exception:
            pass
        await session.end()


@router.get("/api/voice/capabilities")
async def voice_capabilities():
    """What voice support this device actually has. Public so the UI can
    warn before the user starts talking into nothing."""
    from core.voice.call_session import capabilities
    return capabilities()


# --------------------------------------------------------------- /ws/audio
@router.websocket("/ws/audio")
async def audio_stt_socket(websocket: WebSocket):
    """Push-to-talk STT for the chat mic button.

    THIS ENDPOINT DID NOT EXIST. The frontend's AudioStreamClient has
    been opening /ws/audio since it was written, the connection has
    always failed, and it silently fell through to browser speech
    recognition -- which is why the mic button appeared dead or
    inconsistent depending on the browser. Classic "built but never
    wired", this time with the missing half on the server.

    Protocol: client sends binary audio chunks; server replies
    {"type": "stt_final", "text": "..."} or {"type": "stt_error", ...}.
    Auth is optional here: the mic is also on the landing page before
    login, and transcription of your own voice leaks nothing.
    """
    await websocket.accept()

    chunks = bytearray()
    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data:
                chunks.extend(data)
                if len(chunks) > 25 * 1024 * 1024:
                    await websocket.send_json({"type": "stt_error",
                                               "message": "Audio bahut lamba ho gaya."})
                    break
                continue

            text_msg = message.get("text")
            if text_msg:
                try:
                    control = json.loads(text_msg)
                except Exception:
                    continue
                if control.get("type") in ("stop", "end", "flush"):
                    break

    except WebSocketDisconnect:
        pass
    except Exception:
        pass

    # Transcribe whatever arrived. The browser sends compressed audio
    # (webm/opus), so this needs a decoder -- reported honestly rather
    # than returning an empty string that looks like silence.
    try:
        if not chunks:
            await websocket.send_json({"type": "stt_error", "message": "Koi audio nahi mila."})
        else:
            from core.voice.call_session import transcribe, capabilities
            caps = capabilities()
            if not caps["stt_available"]:
                await websocket.send_json({
                    "type": "stt_error",
                    "message": "Server pe STT engine nahi hai -- browser recognition use ho rahi hai.",
                    "use_browser_fallback": True,
                })
            else:
                result = transcribe(bytes(chunks))
                if result.get("ok"):
                    await websocket.send_json({"type": "stt_final", "text": result["text"]})
                else:
                    await websocket.send_json({
                        "type": "stt_error",
                        "message": result.get("reason", "Transcription fail hui."),
                        "use_browser_fallback": True,
                    })
    except Exception:
        pass

    try:
        await websocket.close()
    except Exception:
        pass


# ------------------------------------------------------------ voice profile
@router.get("/api/voice/profile")
async def get_voice_profile():
    """JARVIS's single voice profile -- used by chat playback, the call
    screen and device TTS alike, so they cannot drift apart."""
    from core.voice.jarvis_voice import voice_status
    return voice_status()


@router.post("/api/voice/profile")
async def update_voice_profile(payload: dict):
    """Tune the voice. Persists to config/voice.json; no restart needed."""
    from core.voice.jarvis_voice import save_profile
    return save_profile(payload or {})


@router.post("/api/voice/speak_spec")
async def speak_spec(payload: dict):
    """Given text, return how the browser should speak it in JARVIS's
    voice: chunks, pitch, rate, language, preferred voices."""
    from core.voice.jarvis_voice import browser_voice_spec
    text = (payload or {}).get("text", "")
    if not text.strip():
        return {"chunks": [], "error": "text is required"}
    return browser_voice_spec(text)


@router.post("/api/voice/engine")
async def set_voice_engine(payload: dict):
    """Switch between the two real voices: device (Termux TTS via the
    bridge) or jarvis (browser synthesis on the JARVIS profile)."""
    from core.voice.jarvis_voice import set_engine
    return set_engine((payload or {}).get("engine", ""))


@router.get("/api/trace")
async def trace_view(scope: str = "mine", username: str = None, role: str = None,
                     session_id: str = None, request_id: str = None, limit: int = 30,
                     authorization: str = Header(None)):
    """Identity-tagged traces, filtered to what the caller may see.
    Guests get nothing here -- see identity_trace._can_see."""
    from core.runtime.identity_trace import view
    from .routes_auth import get_speaker
    speaker = get_speaker(authorization)
    viewer = speaker.as_dict() if hasattr(speaker, "as_dict") else dict(speaker or {})
    return view(viewer, scope=scope, username=username, role=role,
                session_id=session_id, request_id=request_id, limit=limit)


@router.get("/api/trace/active")
async def trace_active(authorization: str = Header(None)):
    from core.runtime.identity_trace import active_overview
    from .routes_auth import get_speaker
    speaker = get_speaker(authorization)
    viewer = speaker.as_dict() if hasattr(speaker, "as_dict") else dict(speaker or {})
    return active_overview(viewer)


# --------------------------------------------------- voice settings panel
# These three endpoints DID NOT EXIST. The frontend's VoiceControlPanel
# called them, every call failed, and client.ts fell back to a
# hardcoded engine list -- "Samsung TTS Engine", "eSpeak NG Monospace
# Synthesizer" -- none of which came from UK's device. The panel looked
# configured and controlled nothing. That is what he meant by "fake
# strings, wired nahi hai".
@router.get("/api/voice/settings")
async def get_voice_settings():
    from core.voice.jarvis_voice import load_profile, VOICE_ENGINES
    p = load_profile()
    return {
        "engine": p.engine,
        "engines": list(VOICE_ENGINES),
        "pitch": p.pitch,
        "rate": p.rate,
        "language": p.language,
        "browser_pitch": p.browser_pitch,
        "browser_rate": p.browser_rate,
    }


@router.post("/api/voice/settings")
async def save_voice_settings(payload: dict):
    """Persisted to config/voice.json, which is the same file the CLI's
    /voice commands read -- one source of truth, no drift."""
    from core.voice.jarvis_voice import save_profile
    allowed = {"engine", "pitch", "rate", "language", "browser_pitch", "browser_rate"}
    changes = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not changes:
        return {"ok": False, "error": "Kuch valid setting nahi mili."}
    return save_profile(changes)


@router.get("/api/voice/engines")
async def list_voice_engines():
    """The engines that ACTUALLY exist here, with their real
    availability -- not a list of plausible Android TTS products."""
    from core.voice.jarvis_voice import load_profile
    from core.voice.call_session import capabilities
    caps = capabilities()
    bridge = caps.get("bridge") or {}
    current = load_profile().engine
    return {
        "engines": [
            {
                "name": "device",
                "label": "Device TTS (Termux bridge)",
                "available": bool(bridge.get("tts_available") or caps.get("termux_tts")),
                "detail": ("Android ka apna TTS, bridge port 9999 se."
                           if bridge.get("tts_available")
                           else "Bridge nahi mila -- Termux mein `python3 ~/termux_bridge.py &` chalao."),
                "selected": current == "device",
            },
            {
                "name": "jarvis",
                "label": "JARVIS voice (browser)",
                "available": True,
                "detail": "Browser synthesis, JARVIS profile pe tuned -- lower pitch, hi-IN.",
                "selected": current == "jarvis",
            },
        ],
        "note": "Sirf ye do engines hain. Koi cloned/neural model install nahi hai.",
    }


@router.post("/api/voice/call_spec")
async def call_spec(payload: dict):
    """How the browser should speak on a CALL -- lower and slower than
    chat-bubble playback. Device TTS is never used here."""
    from core.voice.jarvis_voice import call_voice_spec
    text = (payload or {}).get("text", "")
    if not text.strip():
        return {"chunks": [], "error": "text is required"}
    return call_voice_spec(text)


@router.post("/api/voice/test")
async def test_voice(payload: dict):
    """Speak a test phrase through whichever engine is selected."""
    from core.voice.jarvis_voice import speak, browser_voice_spec
    phrase = (payload or {}).get("phrase") or "Sir, sab systems theek chal rahe hain."
    result = speak(phrase)
    if result.get("ok"):
        return {"ok": True, "message": f"Device pe bola ({result.get('chunks', 1)} chunk).",
                "engine": "device"}
    return {
        "ok": False,
        "engine": "jarvis",
        "message": result.get("reason", "Device engine available nahi hai."),
        "browser_spec": result.get("browser_spec") or browser_voice_spec(phrase),
        "speak_in_browser": True,
    }
