from __future__ import annotations

"""UK'S TERMUX BRIDGES -- the STT/TTS that already works on his device.

UK runs two helper processes from start-kali.sh, before JARVIS starts:

  termux_bridge.py     TCP :9999
      Send "LISTEN_STT"  -> runs `termux-speech-to-text`, returns the
                            transcript as plain text (30s timeout).
      Send anything else -> passed to `termux-tts-speak` as arguments.

  stt_bridge_host.py   HTTP :9998
      POST /record?seconds=N -> records with termux-microphone-record,
                                converts to 16kHz mono PCM WAV via
                                ffmpeg, returns the path.

WHY THIS MATTERS
================
JARVIS runs inside proot (Kali), which has no Termux:API access at all
-- `termux-tts-speak` and `termux-microphone-record` do not exist in
that filesystem. Everything I built assumed they were directly callable,
so capabilities() correctly reported "no STT, no TTS" and the whole
voice stack fell back to the browser. UK had ALREADY solved this by
running the bridges in Termux proper and exposing them over localhost,
and I was not using them.

That is the same mistake this project keeps producing from the other
side: a working component sitting there, uncalled.

`termux-speech-to-text` is also a far better fit than the Whisper path
I wrote -- it is Android's own recogniser, it handles Hindi properly,
and it needs no model download on a phone.

WHAT THIS DOES NOT DO
=====================
The bridge listens on 127.0.0.1 with no authentication, which is
appropriate for a loopback helper on a single-user phone but means any
process on the device can drive the mic and speaker. Worth knowing;
not something this file can fix.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from ..runtime.log import log_event

BRIDGE_HOST = "127.0.0.1"
TTS_STT_PORT = 9999          # termux_bridge.py
RECORD_PORT = 9998           # stt_bridge_host.py

CONNECT_TIMEOUT = 2.0        # probing must never stall a turn
STT_TIMEOUT = 35.0           # termux-speech-to-text allows itself 30s
TTS_TIMEOUT = 10.0

_STT_FAILURE_MARKERS = ("[!] Speech cancelled", "STT Error:")


def _probe(port: int) -> bool:
    """Is a bridge listening? Short timeout on purpose: this runs on the
    capabilities path, which the UI calls on load."""
    try:
        with socket.create_connection((BRIDGE_HOST, port), timeout=CONNECT_TIMEOUT):
            return True
    except Exception:
        return False


def bridge_status() -> Dict[str, Any]:
    """What is actually listening.

    UK runs termux_bridge.py (port 9999) and DOES NOT start
    stt_bridge_host.py (port 9998). Both are probed separately so the
    absence of the recorder never makes the TTS bridge look down --
    previously stt_available was simply mirrored from the TTS probe,
    which claimed a capability he had deliberately not enabled.

    Port 9999 does serve LISTEN_STT, but that path blocks for up to 30
    seconds waiting on Android's recogniser and is unsuitable for a
    live call. Browser recognition handles listening; the bridge is
    used for SPEAKING, which is the part the browser does worse.
    """
    tts = _probe(TTS_STT_PORT)
    recorder = _probe(RECORD_PORT)
    return {
        "tts_available": tts,
        # Push-to-talk STT over the bridge is possible but not used for
        # calls -- see the note above.
        "stt_available": recorder,
        "bridge_stt_possible": tts,
        "recorder_available": recorder,
        "tts_stt_port": TTS_STT_PORT,
        "record_port": RECORD_PORT,
        "note": (
            "Termux bridges chal rahe hain -- JARVIS ab device ka apna STT/TTS use karega."
            if tts else
            "Termux bridge (port 9999) nahi mila. Termux mein `python3 ~/termux_bridge.py &` "
            "chalao -- proot ke andar termux-api commands available nahi hote, isliye bridge "
            "hi raasta hai."
        ),
    }


def speak(text: str, *, pitch: Optional[float] = None, rate: Optional[float] = None,
          lang: Optional[str] = None) -> Dict[str, Any]:
    """Speak through termux-tts-speak via the bridge.

    The bridge shlex-splits whatever it receives and appends it to
    `termux-tts-speak`, so flags and the text go in one line. The text
    is quoted so a sentence is one argument rather than many -- and so
    a stray quote in JARVIS's reply cannot inject extra flags.
    """
    if not (text or "").strip():
        return {"ok": False, "reason": "kuch bolne ko nahi hai"}

    try:
        from .jarvis_voice import load_profile, prepare_for_speech
        profile = load_profile()
        pitch = profile.pitch if pitch is None else pitch
        rate = profile.rate if rate is None else rate
        lang = profile.language if lang is None else lang
        spoken = prepare_for_speech(text)
    except Exception:
        spoken = text
        pitch = pitch if pitch is not None else 0.72
        rate = rate if rate is not None else 0.95
        lang = lang or "hi-IN"

    if not spoken.strip():
        return {"ok": False, "reason": "bolne layak text nahi bacha"}

    # shlex.split on the bridge side: one quoted argument, quotes inside
    # escaped, so the reply text can never become extra CLI flags.
    safe = spoken.replace("\\", "\\\\").replace('"', '\\"')
    payload = f'-l {lang} -p {pitch} -r {rate} "{safe}"'

    try:
        with socket.create_connection((BRIDGE_HOST, TTS_STT_PORT), timeout=TTS_TIMEOUT) as sock:
            sock.sendall(payload.encode("utf-8"))
            sock.settimeout(TTS_TIMEOUT)
            try:
                ack = sock.recv(64).decode("utf-8", errors="ignore").strip()
            except Exception:
                ack = ""
        return {"ok": True, "engine": "termux_bridge", "ack": ack or "sent",
                "pitch": pitch, "rate": rate, "lang": lang}
    except Exception as exc:
        return {"ok": False, "reason": f"bridge tak nahi pahuncha: {exc}", "fallback": "browser"}


def listen(timeout: float = STT_TIMEOUT) -> Dict[str, Any]:
    """Capture one utterance via Android's own speech recogniser.

    Blocking by design -- it is push-to-talk, and the bridge itself
    blocks for up to 30s. Callers on an async path should run it in a
    thread.
    """
    try:
        with socket.create_connection((BRIDGE_HOST, TTS_STT_PORT), timeout=CONNECT_TIMEOUT) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"LISTEN_STT")
            chunks = []
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
        text = b"".join(chunks).decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        return {"ok": False, "text": "", "reason": f"bridge tak nahi pahuncha: {exc}"}

    if not text:
        return {"ok": False, "text": "", "reason": "Kuch suna nahi gaya."}

    # The bridge returns its own error strings in the same channel as a
    # transcript, so they must be recognised rather than treated as
    # something UK said.
    for marker in _STT_FAILURE_MARKERS:
        if text.startswith(marker):
            return {"ok": False, "text": "", "reason": text}

    return {"ok": True, "text": text, "engine": "termux-speech-to-text"}


def record_wav(seconds: int = 3) -> Dict[str, Any]:
    """Record via the HTTP bridge and get a 16kHz mono WAV path.

    Used when raw audio is wanted rather than a transcript -- the
    recorder caps at 5s, matching stt_bridge_host.py.
    """
    seconds = max(1, min(int(seconds), 5))
    url = f"http://{BRIDGE_HOST}:{RECORD_PORT}/record?seconds={seconds}"
    try:
        request = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(request, timeout=seconds + 20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("status") != "success":
            return {"ok": False, "reason": data.get("message", "recorder failed")}
        return {
            "ok": True, "path": data.get("path"),
            "sample_rate": data.get("sample_rate", 16000),
            "size_bytes": data.get("size_bytes"),
        }
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            return {"ok": False, "reason": body.get("message", str(exc))}
        except Exception:
            return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"recorder bridge tak nahi pahuncha: {exc}"}


def read_wav_bytes(path: str) -> Optional[bytes]:
    """Read a WAV the recorder produced. Separate from record_wav so a
    caller that only wants the path does not pay the read."""
    try:
        return Path(path).read_bytes()
    except Exception:
        return None
