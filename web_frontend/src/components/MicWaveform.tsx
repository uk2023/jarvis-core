import { useEffect, useRef, useState } from 'react';
import { Loader2, AudioLines, MicOff, X } from 'lucide-react';
import type { RecognitionState } from '../voice/recognition';

/**
 * MIC STATE STRIP -- icons, not sentences.
 *
 * This showed the literal string "Mic taiyaar ho raha hai...", and
 * before that "Streaming raw audio to server Whisper STT
 * (Termux/FastAPI)...". Both were hardcoded prose sitting in a UI that
 * is otherwise iconographic, and the second one described internal
 * plumbing rather than anything UK could act on.
 *
 * State is now carried by the icon and colour; the wave carries
 * activity. The only text is a single short status word, and there is
 * an explicit abort control so the mic can always be stopped.
 *
 * Bars are driven by the recogniser's own activity (see
 * voice/recognition.ts). They go flat when nothing is heard, because a
 * wave that moves regardless would look the same whether or not the
 * microphone works -- which is exactly how the earlier bug stayed
 * hidden.
 */

const BARS = 32;

const STATE_META: Record<RecognitionState, {
  label: string;
  tone: string;
  bar: string;
  border: string;
  bg: string;
}> = {
  idle:     { label: 'Idle',      tone: 'text-slate-400',   bar: '#64748b', border: 'border-slate-500/25', bg: 'bg-slate-500/10' },
  starting: { label: 'Preparing', tone: 'text-amber-400',   bar: '#fbbf24', border: 'border-amber-500/30', bg: 'bg-amber-500/10' },
  ready:    { label: 'Listening', tone: 'text-emerald-400', bar: '#34d399', border: 'border-emerald-500/30', bg: 'bg-emerald-500/10' },
  hearing:  { label: 'Listening', tone: 'text-emerald-300', bar: '#34d399', border: 'border-emerald-500/40', bg: 'bg-emerald-500/15' },
  error:    { label: 'Mic error', tone: 'text-rose-400',    bar: '#f87171', border: 'border-rose-500/30',  bg: 'bg-rose-500/10' },
};

export default function MicWaveform({
  state,
  level,
  onAbort,
}: {
  state: RecognitionState;
  level: number;
  onAbort?: () => void;
}) {
  const barsRef = useRef<number[]>(new Array(BARS).fill(0.04));
  const [, tick] = useState(0);

  const active = state === 'ready' || state === 'hearing';
  const meta = STATE_META[state] ?? STATE_META.idle;

  useEffect(() => {
    const id = setInterval(() => {
      barsRef.current = [...barsRef.current.slice(1), active ? Math.max(0.04, level) : 0.04];
      tick((n) => n + 1);
    }, 65);
    return () => clearInterval(id);
  }, [level, active]);

  return (
    <div className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-xl border ${meta.border} ${meta.bg}`}>
      <span className={meta.tone}>
        {state === 'starting' ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : state === 'error' ? (
          <MicOff className="w-4 h-4" />
        ) : (
          <AudioLines className="w-4 h-4" />
        )}
      </span>

      <div className="flex h-5 flex-1 items-center gap-[2px]">
        {barsRef.current.map((v, i) => (
          <div
            key={i}
            className="flex-1 rounded-full transition-all duration-75"
            style={{
              height: `${Math.max(8, v * 100)}%`,
              minHeight: '2px',
              backgroundColor: meta.bar,
              opacity: active ? 0.35 + v * 0.6 : 0.2,
            }}
          />
        ))}
      </div>

      <span className={`shrink-0 text-[11px] font-medium tracking-wide ${meta.tone}`}>
        {meta.label}
      </span>

      {onAbort && active && (
        <button
          type="button"
          onClick={onAbort}
          aria-label="Stop listening"
          title="Stop"
          className="shrink-0 rounded-full p-1 text-slate-400 transition hover:bg-white/10 hover:text-slate-200"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
