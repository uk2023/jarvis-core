import { useState, useEffect, useRef, useCallback } from 'react';
import { X, Mic, MicOff, Loader2, AlertTriangle } from 'lucide-react';
import {
  speak, stopSpeaking, onAmplitude, onSpeakingChange,
  listenWithLevel, recognizeOnce,
} from '../voice/jarvisVoice';

/**
 * VOICE ENGINE SCREEN -- the dedicated surface for talking to JARVIS.
 *
 * The waveform is driven by REAL amplitude: the user's mic level while
 * listening, and synthesis boundary events while JARVIS speaks. It goes
 * flat when nothing is happening. A wave that animates on a timer would
 * look identical to a working one while telling you nothing, which is
 * the same failure as fake telemetry elsewhere in this project.
 *
 * Every exchange is handed back through onTranscript so it lands in the
 * normal chat session as text -- a voice conversation that vanishes
 * when you close the screen would be worse than typing it.
 */

interface Props {
  onClose: () => void;
  onTranscript: (text: string) => Promise<void> | void;
  isDark?: boolean;
}

type Phase = 'idle' | 'listening' | 'thinking' | 'speaking';

const BAR_COUNT = 36;

export default function VoiceEngineScreen({ onClose, onTranscript, isDark = true }: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [level, setLevel] = useState(0);
  const [interim, setInterim] = useState('');
  const [lines, setLines] = useState<{ who: 'user' | 'jarvis'; text: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  const micRef = useRef<{ stop: () => void } | null>(null);
  const recogStopRef = useRef<(() => void) | null>(null);
  const barsRef = useRef<number[]>(new Array(BAR_COUNT).fill(0.06));
  const [, forceRender] = useState(0);

  // Amplitude from the shared voice module drives the bars while JARVIS
  // speaks; the mic drives them while listening.
  useEffect(() => {
    const offAmp = onAmplitude((lvl) => setLevel(lvl));
    const offState = onSpeakingChange((speaking) => {
      setPhase((p) => (speaking ? 'speaking' : p === 'speaking' ? 'idle' : p));
    });
    return () => { offAmp(); offState(); };
  }, []);

  // Shift the bar history on each level change so the wave scrolls.
  useEffect(() => {
    const id = setInterval(() => {
      barsRef.current = [...barsRef.current.slice(1), Math.max(0.06, level)];
      forceRender((n) => n + 1);
    }, 55);
    return () => clearInterval(id);
  }, [level]);

  const cleanup = useCallback(() => {
    micRef.current?.stop();
    micRef.current = null;
    recogStopRef.current?.();
    recogStopRef.current = null;
    stopSpeaking();
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const handleFinal = useCallback(async (text: string) => {
    const clean = text.trim();
    if (!clean) return;

    setInterim('');
    setLines((l) => [...l, { who: 'user', text: clean }]);
    setPhase('thinking');

    // Straight into the normal chat pipeline, so the voice turn is
    // stored, traced and remembered exactly like a typed one.
    try {
      await onTranscript(clean);
    } catch {
      setError('Message bhejne mein dikkat aayi.');
      setPhase('idle');
    }
  }, [onTranscript]);

  /** Called by the parent when JARVIS's reply arrives. */
  const speakReply = useCallback(async (text: string) => {
    setLines((l) => [...l, { who: 'jarvis', text }]);
    setPhase('speaking');
    await speak(text);
    setPhase('idle');
  }, []);

  // Exposed so the parent can push replies in.
  useEffect(() => {
    (window as any).__jarvisSpeakReply = speakReply;
    return () => { delete (window as any).__jarvisSpeakReply; };
  }, [speakReply]);

  const startListening = async () => {
    setError(null);
    stopSpeaking();

    const mic = await listenWithLevel(setLevel);
    if (!mic) {
      setError('Mic access nahi mila. Browser permission check karo.');
      return;
    }
    micRef.current = mic;
    setPhase('listening');

    const stop = recognizeOnce(
      (text, isFinal) => {
        if (isFinal) {
          micRef.current?.stop();
          micRef.current = null;
          setLevel(0);
          handleFinal(text);
        } else {
          setInterim(text);
        }
      },
      (msg) => {
        setError(msg);
        micRef.current?.stop();
        micRef.current = null;
        setPhase('idle');
      },
    );
    recogStopRef.current = stop;
  };

  const stopListening = () => {
    recogStopRef.current?.();
    recogStopRef.current = null;
    micRef.current?.stop();
    micRef.current = null;
    setLevel(0);
    setPhase('idle');
  };

  const phaseLabel: Record<Phase, string> = {
    idle: 'Tap karke bolo',
    listening: 'Sun raha hun',
    thinking: 'Soch raha hun',
    speaking: 'Bol raha hun',
  };

  const accent =
    phase === 'listening' ? '#34d399' : phase === 'speaking' ? '#818cf8'
      : phase === 'thinking' ? '#fbbf24' : '#475569';

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-between p-6"
      style={{
        background: isDark
          ? 'radial-gradient(circle at 50% 35%, rgba(49,46,129,0.35), rgba(2,6,23,0.98) 65%)'
          : 'radial-gradient(circle at 50% 35%, rgba(199,210,254,0.6), rgba(248,250,252,0.98) 65%)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <div className="flex w-full items-center justify-between">
        <span className="text-xs uppercase tracking-[0.2em]" style={{ color: accent }}>
          JARVIS Voice
        </span>
        <button
          onClick={() => { cleanup(); onClose(); }}
          className="rounded-full p-2 text-slate-400 transition hover:bg-white/10 hover:text-slate-200"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Waveform -- real amplitude only. Flat when nothing is happening. */}
      <div className="flex w-full max-w-md flex-col items-center gap-6">
        <div className="flex h-28 w-full items-center justify-center gap-[3px]">
          {barsRef.current.map((v, i) => {
            const center = 1 - Math.abs(i - BAR_COUNT / 2) / (BAR_COUNT / 2);
            const height = Math.max(4, v * 100 * (0.45 + center * 0.55));
            return (
              <div
                key={i}
                className="w-[4px] rounded-full transition-all duration-75"
                style={{
                  height: `${height}%`,
                  background: `linear-gradient(180deg, ${accent}, ${accent}55)`,
                  opacity: 0.45 + center * 0.55,
                }}
              />
            );
          })}
        </div>

        <p className="text-sm" style={{ color: accent }}>
          {phase === 'thinking' ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> {phaseLabel[phase]}
            </span>
          ) : (
            phaseLabel[phase]
          )}
        </p>

        {interim && (
          <p className="max-w-sm text-center text-sm italic text-slate-400">{interim}</p>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-100">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}
      </div>

      {/* Live transcript -- the same text that lands in the chat session. */}
      <div className="max-h-40 w-full max-w-md overflow-y-auto px-1">
        {lines.slice(-6).map((l, i) => (
          <p
            key={i}
            className={`mb-1.5 text-xs ${l.who === 'user' ? 'text-right text-slate-300' : 'text-left text-indigo-200'}`}
          >
            {l.text}
          </p>
        ))}
      </div>

      <button
        onClick={phase === 'listening' ? stopListening : startListening}
        disabled={phase === 'thinking'}
        className="flex h-16 w-16 items-center justify-center rounded-full transition disabled:opacity-40"
        style={{
          backgroundColor: phase === 'listening' ? '#ef4444' : accent,
          boxShadow: phase === 'listening' ? `0 0 0 ${8 + level * 24}px ${accent}18` : 'none',
        }}
      >
        {phase === 'listening' ? (
          <MicOff className="h-6 w-6 text-white" />
        ) : (
          <Mic className="h-6 w-6 text-white" />
        )}
      </button>
    </div>
  );
}
