import { useState, useEffect, useRef, useCallback } from 'react';
import { X, Mic, MicOff, Loader2, AlertTriangle, Volume2, AudioLines } from 'lucide-react';
import { speakForCall as speak, stopSpeaking, onAmplitude } from '../voice/jarvisVoice';
import { api } from '../api/client';
import { startRecognition, recognitionSupported } from '../voice/recognition';
import type { RecognitionSession } from '../voice/recognition';
import '../styles/jarvis-call.css';

/**
 * LIVE CALL -- speak, JARVIS answers, out loud.
 *
 * This differs from the chat mic on purpose, and the difference is the
 * whole point:
 *
 *   CHAT MIC -- dictation. Text lands in the input box, UK reads it,
 *               edits it, sends it himself. Never auto-sends.
 *   CALL     -- conversation. A natural pause ends the turn, the
 *               message goes immediately, and the reply is spoken.
 *
 * WHAT WAS BROKEN BEFORE
 * ----------------------
 * The old screen streamed raw PCM over a WebSocket to server-side STT
 * that does not exist on this device, so nothing was transcribed and no
 * reply ever came. Worse, /api/voice/capabilities was returning HTTP
 * 500 because call_session.py imported `audioop`, which Python 3.14
 * removed -- so even the fallback check failed and the whole screen sat
 * dead.
 *
 * It also stuttered. The waveform kept audio level in React state and
 * re-rendered on every audio frame -- hundreds of renders a second.
 * The bars are now painted on a canvas from a ref, so audio never
 * triggers a React render at all. That was the "glitch kar raha hai,
 * atak raha hai".
 */

type Phase = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking';

// THE LOOP BUG (fixed 2026-09-14). UK's screenshots show JARVIS stuck
// repeating "Namaste sir, aapka sandesh clear nahi hua" back and forth
// with a near-identical transcript. The cause: the self-echo guard
// before this fix was a FIXED 900ms timer that only muted the opening
// burst of playback. JARVIS's actual sentence takes several seconds to
// speak through TTS, so after 900ms the guard lifted while he was
// still talking -- his own voice kept leaking into the mic for the
// rest of the reply, got transcribed, and (critically) onFinal had NO
// gating at all, so that leaked transcript was sent straight back to
// JARVIS as a new question. He answered "not clear" to his own echo,
// spoke that reply, which leaked again, forever.
//
// The fix has two parts:
//   1. The guard is now tied to the ACTUAL 'speaking' phase, not a
//      fixed duration -- it covers the whole reply, however long TTS
//      takes to say it, not just the first second.
//   2. onFinal is gated too, not just onInterim. Previously a barge-in
//      check only ran on interim results (for the "stop talking"
//      behaviour); the FINAL text -- the thing that actually starts a
//      new turn -- went straight to handleTurn() unconditionally. That
//      is the one line that turned an echo into an infinite loop.
//
// UK's own spec for the desired behaviour: "jab tak JARVIS bol raha ho
// tab tak mic capturing on ho, lekin data na sune jab tak mic mein
// koi khalbali (genuine speech) na ho -- tabhi speaker band ho aur
// interrupt ho, phir user jo bolna chahta hai wo sune." That is exactly
// what genuineInterrupt() below decides, applied to BOTH interim (for
// stopping playback) and final (for deciding whether to act on it).

// Minimum mic amplitude (0..1, from onLevel) to treat speech as a
// person talking rather than speaker bleed-through. Tuned
// conservatively low so real, quieter speech still interrupts; it only
// needs to clear what a phone's own speaker typically re-injects into
// its own mic without a headset.
const BARGE_IN_LEVEL_FLOOR = 0.12;

// A single leaked word/syllable is far more likely to be echo than an
// intentional interruption -- a real "ruko" or "sunno" is one word,
// but genuine speech almost always continues past it. Two catches most
// real interruptions while filtering single-word echo fragments.
const BARGE_IN_MIN_WORDS = 2;

// How many consecutive growing interim updates count as a real
// interruption. Speaker echo arrives as short isolated bursts; a person
// talking over you produces a steadily lengthening transcript. Three
// ticks is roughly a second of continuous speech -- enough to be
// deliberate, short enough that "are suno" still cuts through.
const BARGE_IN_SUSTAIN_TICKS = 3;

interface Turn {
  who: 'user' | 'jarvis';
  text: string;
}

interface Props {
  onClose?: () => void;
  onExchange?: (userText: string, jarvisText: string) => void;
}

export default function VoiceCallScreen({ onClose, onExchange }: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Audio level lives in a ref, NOT state -- see the stutter note above.
  const levelRef = useRef(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phaseRef = useRef<Phase>('idle');
  const recognitionRef = useRef<RecognitionSession | null>(null);
  const rafRef = useRef(0);
  const busyRef = useRef(false);
  // Tracks whether a genuine barge-in has already fired for the CURRENT
  // speaking turn, so resetBuffer() is called once per interruption,
  // not on every subsequent interim result while the user keeps
  // talking.
  const bargedInRef = useRef(false);
  // Sustained-interruption tracking -- see onInterim below.
  const interruptTicksRef = useRef(0);
  const interruptProgressRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [turns]);

  // JARVIS's own speech amplitude drives the wave while he talks.
  useEffect(() => onAmplitude((lvl) => { levelRef.current = lvl; }), []);

  // One animation loop, entirely outside React.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const history: number[] = new Array(56).fill(0.04);
    let frame = 0;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (w === 0 || h === 0) {
        rafRef.current = requestAnimationFrame(draw);
        return;
      }
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr);
        canvas.height = Math.floor(h * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      frame += 1;
      if (frame % 3 === 0) {
        history.push(Math.max(0.04, levelRef.current));
        history.shift();
      }

      ctx.clearRect(0, 0, w, h);

      const p = phaseRef.current;
      const accent =
        p === 'listening' ? [52, 211, 153] :
        p === 'speaking' ? [129, 140, 248] :
        p === 'thinking' ? [251, 191, 36] : [100, 116, 139];

      const mid = h / 2;
      const barW = w / history.length;

      for (let i = 0; i < history.length; i++) {
        const centre = 1 - Math.abs(i - history.length / 2) / (history.length / 2);
        const amp = history[i] * (h * 0.4) * (0.3 + centre * 0.7);
        const alpha = 0.2 + centre * 0.65;
        ctx.fillStyle = `rgba(${accent[0]},${accent[1]},${accent[2]},${alpha})`;
        const bh = Math.max(2, amp * 2);
        const x = i * barW + barW * 0.2;
        const bw = barW * 0.6;
        ctx.beginPath();
        if (typeof (ctx as any).roundRect === 'function') {
          (ctx as any).roundRect(x, mid - bh / 2, bw, bh, Math.min(bw / 2, 2));
        } else {
          ctx.rect(x, mid - bh / 2, bw, bh);
        }
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  const cleanup = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    stopSpeaking();
    levelRef.current = 0;
    bargedInRef.current = false;
    interruptTicksRef.current = 0;
    interruptProgressRef.current = 0;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  /** One exchange: send, speak the reply, resume listening. */
  const handleTurn = useCallback(async (text: string) => {
    if (busyRef.current) return;
    busyRef.current = true;

    setInterim('');
    setTurns((t) => [...t, { who: 'user', text }]);
    setPhase('thinking');

    let reply = '';
    try {
      // WHY THIS IS api.sendMessage AND NOT A RAW fetch (fixed
      // 2026-09-14). Two bugs lived in the old version:
      //
      //   1. It read data.response / data.message / data.text. The
      //      endpoint returns {status, jarvisMessage:{sender, text}}.
      //      None of those keys existed, so reply was ALWAYS '' and the
      //      function returned silently right after showing "thinking"
      //      -- UK's exact report: "thinking dikha kar band ho jata
      //      hai". Nothing was ever spoken because nothing was ever
      //      read.
      //   2. It used a relative '/api/chat', bypassing the client's
      //      resolved backend URL, so it depended on a dev proxy that
      //      does not exist in every deployment.
      //
      // Going through the shared client fixes both and keeps the call
      // on the same path as typed chat -- so the turn is persisted,
      // traced and attributed identically.
      // sendChat() already normalises the endpoint's
      // {status, jarvisMessage:{text}} shape into {reply}, and sends
      // the auth header so the turn is attributed to the right person.
      const data = await api.sendChat(text, 'main_session', 'web');
      reply = (data?.reply ?? '').trim();
    } catch (err: any) {
      setError(err?.message ?? 'Jawab nahi aaya -- server se connection toot gaya.');
    }

    if (!reply) {
      // Say so rather than sliding back to listening as if nothing
      // happened -- a silent failure here is indistinguishable from
      // JARVIS choosing not to answer.
      setPhase('listening');
      busyRef.current = false;
      if (!error) setError('Khali jawab mila -- kuch bola nahi ja saka.');
      return;
    }

    setTurns((t) => [...t, { who: 'jarvis', text: reply }]);
    onExchange?.(text, reply);

    // MUTE-BY-PHASE, NOT BY TIMER (see the note above the constants).
    // Setting phase to 'speaking' IS the guard now -- the interim/final
    // handlers below both check phaseRef.current === 'speaking' for
    // the entire duration of playback, however long the reply actually
    // takes to say, not a fixed 900ms.
    bargedInRef.current = false;
    interruptTicksRef.current = 0;
    interruptProgressRef.current = 0;
    setPhase('speaking');
    await speak(reply);
    // If a genuine barge-in already moved us to 'listening' mid-reply,
    // do not stomp it back to 'listening' redundantly, but do NOT
    // revert to 'speaking' either -- speak() has returned either way
    // because stopSpeaking() aborts the browser's utterance queue.
    setPhase('listening');
    busyRef.current = false;
  }, [onExchange]);

  const startCall = () => {
    setError(null);
    setPhase('connecting');

    if (!recognitionSupported()) {
      setError('Is browser mein speech recognition nahi hai.');
      setPhase('idle');
      return;
    }

    // ONE microphone. The previous version opened a second getUserMedia
    // stream for the level meter, which on Android silently kills the
    // recogniser -- the wave moved, and nothing was ever transcribed or
    // sent. That was the "wave chalti hai par auto-send nahi hota".
    const session = startRecognition({
      onState: (state) => {
        if (state === 'ready' || state === 'hearing') {
          // Do not stomp on 'thinking'/'speaking' -- the recogniser
          // keeps running through both so barge-in still works.
          setPhase((p) => (p === 'thinking' || p === 'speaking' ? p : 'listening'));
        } else if (state === 'error') {
          setPhase('idle');
        }
      },
      onLevel: (lvl) => { levelRef.current = lvl; },
      onInterim: (text) => {
        // BARGE-IN, REWORKED (2026-09-16, UK's spec). His exact ask:
        // while JARVIS speaks the mic STAYS ON and keeps hearing, but
        // nothing reaches JARVIS and he does not stop -- unless the
        // interruption is genuine. Then he stops FIRST, and only after
        // he has stopped does anything get recorded as a turn.
        //
        // The previous version interrupted on any 2-word interim above
        // an amplitude floor, which the phone speaker's own echo
        // cleared easily -- so JARVIS heard himself, stopped himself,
        // and answered himself in a loop.
        //
        // Now an interruption must be SUSTAINED: several consecutive
        // interim updates that keep growing, which is what a person
        // talking over you produces and what a burst of speaker echo
        // does not. A single stray phrase no longer cuts him off
        // mid-sentence.
        const words = text.trim().split(/\s+/).filter(Boolean);

        if (phaseRef.current === 'speaking') {
          const loudEnough = levelRef.current > BARGE_IN_LEVEL_FLOOR;
          const longEnough = words.length >= BARGE_IN_MIN_WORDS;

          if (loudEnough && longEnough && text.length > interruptProgressRef.current) {
            // Growing text at real volume -- count it as one more tick
            // of a possible interruption.
            interruptTicksRef.current += 1;
            interruptProgressRef.current = text.length;
          }

          if (interruptTicksRef.current >= BARGE_IN_SUSTAIN_TICKS) {
            // Genuine. Stop speaking FIRST, discard whatever the
            // buffer holds (it may contain JARVIS's own echo captured
            // while he was still talking), and only then start
            // listening for what UK actually wants to say.
            stopSpeaking();
            bargedInRef.current = true;
            interruptTicksRef.current = 0;
            interruptProgressRef.current = 0;
            session?.resetBuffer();
            setInterim('');
            setPhase('listening');
          }
          // Not yet sustained: show nothing, send nothing. The mic is
          // still recording -- it just does not reach JARVIS.
          return;
        }

        setInterim(text);
      },
      // THE LOOP FIX. A finished phrase used to go to handleTurn()
      // UNCONDITIONALLY -- no phase check at all. If JARVIS's own
      // speech leaked into the mic and the recogniser's silence-gap
      // logic finalised it as an utterance, THIS is the line that sent
      // it back to him as a new question, producing the exact loop in
      // UK's screenshots. Now: while still in 'speaking' with no
      // genuine barge-in on record for this turn, the final is
      // discarded outright.
      onFinal: (text) => {
        if (phaseRef.current === 'speaking' && !bargedInRef.current) {
          return;
        }
        bargedInRef.current = false;
        handleTurn(text);
      },
      onError: (msg) => {
        setError(msg);
        setPhase('idle');
      },
    }, {
      // Wait for a genuine pause before treating the utterance as
      // finished. Without this every phrase fired a send, so however
      // much UK said, only the first fragment reached JARVIS -- his
      // report: "bas keval ek word wahan pahunchta hai".
      continuous: true,
      utteranceSilenceMs: 1100,
    });

    recognitionRef.current = session;
    if (!session) setPhase('idle');
  };

  const endCall = () => {
    cleanup();
    setPhase('idle');
    setInterim('');
  };

  const active = phase !== 'idle';
  // Icons carry the state; the word is a short label, not a sentence.
  // "Sun raha hun" as hardcoded prose looked like a canned reply from
  // JARVIS rather than a UI state, which is why it had to go.
  const label: Record<Phase, string> = {
    idle: 'Tap to start',
    connecting: 'Preparing',
    listening: 'Listening',
    thinking: 'Thinking',
    speaking: 'Speaking',
  };
  const accent =
    phase === 'listening' ? '#34d399' :
    phase === 'speaking' ? '#818cf8' :
    phase === 'thinking' ? '#fbbf24' : '#64748b';

  return (
    <div className="jarvis-call-screen">
      <header className="jarvis-call-header">
        <span style={{ color: accent }}>JARVIS VOICE</span>
        {onClose && (
          <button onClick={() => { endCall(); onClose(); }} aria-label="Close call">
            <X size={20} />
          </button>
        )}
      </header>

      <div className="jarvis-call-core">
        {/* The landing page's core orb, reacting rather than decorating. */}
        <div
          className={`jarvis-call-orb ${active ? 'is-active' : ''}`}
          style={{ ['--call-accent' as any]: accent }}
        >
          <div className="jarvis-call-orb-ring" />
          <div className="jarvis-call-orb-core" />
        </div>

        <canvas ref={canvasRef} className="jarvis-call-wave" />

        <p className="jarvis-call-label" style={{ color: accent }}>
          <span className="jarvis-call-label-row">
            {phase === 'thinking' ? (
              <Loader2 size={14} className="jarvis-spin" />
            ) : phase === 'connecting' ? (
              <Loader2 size={14} className="jarvis-spin" />
            ) : phase === 'speaking' ? (
              <Volume2 size={14} />
            ) : phase === 'listening' ? (
              <AudioLines size={14} className="jarvis-pulse" />
            ) : (
              <Mic size={14} />
            )}
            {label[phase]}
          </span>
        </p>

        {interim && <p className="jarvis-call-interim">{interim}</p>}

        {error && (
          <p className="jarvis-call-error">
            <AlertTriangle size={13} /> {error}
          </p>
        )}
      </div>

      <div className="jarvis-call-transcript">
        {turns.slice(-8).map((t, i) => (
          <p key={i} className={t.who === 'user' ? 'is-user' : 'is-jarvis'}>{t.text}</p>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="jarvis-call-controls">
        <button
          onClick={active ? endCall : startCall}
          className={`jarvis-call-button ${active ? 'is-active' : ''}`}
          style={{ backgroundColor: active ? '#ef4444' : accent }}
          aria-label={active ? 'End call' : 'Start call'}
        >
          {active ? <MicOff size={24} /> : <Mic size={24} />}
        </button>
      </div>
    </div>
  );
}
