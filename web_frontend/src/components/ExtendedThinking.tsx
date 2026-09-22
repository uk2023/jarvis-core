import { useState, useEffect, useRef } from 'react';
import { Brain, ChevronDown, ChevronRight, Loader2, Check } from 'lucide-react';

/**
 * EXTENDED THINKING -- the control and the panel.
 *
 * Two components, one idea: show the reasoning that actually happened.
 *
 * ThinkingToggle cycles off -> auto -> on. AUTO is the mode UK asked for
 * where "JARVIS khud kar sake meri baat sun ke" -- the server decides per
 * message and reports back, so the icon can light up on its own with a
 * real reason attached rather than a guess made in the browser.
 *
 * ThinkingPanel renders stages as they stream in. It renders ONLY what
 * the server sent. There is no placeholder text, no invented "Analysing
 * your request..." line while waiting -- if a stage has not arrived, the
 * panel shows a spinner and nothing else. Fabricated reasoning would be
 * worse than no panel, because it would look exactly like the real thing.
 */

export type ThinkingMode = 'off' | 'auto' | 'on';

const MODE_ORDER: ThinkingMode[] = ['off', 'auto', 'on'];

const MODE_LABEL: Record<ThinkingMode, string> = {
  off: 'Thinking off',
  auto: 'Thinking auto — JARVIS khud decide karega',
  on: 'Thinking on — har turn soch kar',
};

export function ThinkingToggle({
  mode,
  onChange,
  activeThisTurn,
  reason,
}: {
  mode: ThinkingMode;
  onChange: (m: ThinkingMode) => void;
  activeThisTurn?: boolean;
  reason?: string;
}) {
  const next = () => onChange(MODE_ORDER[(MODE_ORDER.indexOf(mode) + 1) % MODE_ORDER.length]);

  const tone =
    mode === 'on'
      ? 'border-indigo-500/60 bg-indigo-500/15 text-indigo-200'
      : mode === 'auto'
      ? activeThisTurn
        ? 'border-indigo-500/40 bg-indigo-500/10 text-indigo-200'
        : 'border-slate-700 bg-slate-800/50 text-slate-400'
      : 'border-slate-800 bg-slate-900/50 text-slate-500';

  return (
    <button
      type="button"
      onClick={next}
      title={reason ? `${MODE_LABEL[mode]} — ${reason}` : MODE_LABEL[mode]}
      aria-label={MODE_LABEL[mode]}
      className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition ${tone}`}
    >
      <Brain className={`h-4 w-4 ${mode === 'auto' && activeThisTurn ? 'animate-pulse' : ''}`} />
      <span className="hidden sm:inline">
        {mode === 'off' ? 'Think' : mode === 'auto' ? 'Auto' : 'Think+'}
      </span>
    </button>
  );
}

export interface ThinkingStage {
  stage: string;
  content: string;
  duration_ms?: number;
  ok?: boolean;
}

const STAGE_LABEL: Record<string, string> = {
  understand: 'Samajh raha hun',
  explore: 'Options dekh raha hun',
  critique: 'Apne hi reasoning ko check kar raha hun',
  answer: 'Jawab likh raha hun',
};

export function ThinkingPanel({
  stages,
  currentStage,
  done,
  reason,
  defaultOpen = false,
}: {
  stages: ThinkingStage[];
  currentStage?: string | null;
  done?: boolean;
  reason?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Follow the newest stage while it streams, but stop once complete so
  // the user can read without the panel yanking them around.
  useEffect(() => {
    if (open && !done) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [stages.length, currentStage, open, done]);

  if (stages.length === 0 && !currentStage) return null;

  const totalMs = stages.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);

  return (
    <div className="mb-2 overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-400 transition hover:text-slate-200"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {done ? (
          <Check className="h-3.5 w-3.5 text-emerald-400" />
        ) : (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
        )}
        <span>
          {done
            ? `Socha — ${stages.length} step${totalMs ? `, ${(totalMs / 1000).toFixed(1)}s` : ''}`
            : currentStage
            ? STAGE_LABEL[currentStage] ?? currentStage
            : 'Soch raha hun'}
        </span>
        {reason && <span className="ml-auto hidden truncate text-slate-600 sm:inline">{reason}</span>}
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-800 px-3 py-2.5">
          {stages.map((s, i) => (
            <div key={`${s.stage}-${i}`}>
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-indigo-300/70">
                {STAGE_LABEL[s.stage] ?? s.stage}
                {typeof s.duration_ms === 'number' && (
                  <span className="text-slate-600">{Math.round(s.duration_ms)}ms</span>
                )}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                {s.content}
              </p>
            </div>
          ))}

          {/* In-flight stage: a spinner and the stage name only. No
              placeholder reasoning text -- see component docstring. */}
          {!done && currentStage && !stages.some((s) => s.stage === currentStage) && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              {STAGE_LABEL[currentStage] ?? currentStage}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

/**
 * Consumes the SSE stream from POST /api/think/stream.
 * Returns a cancel function so a new message can abort the previous run.
 */
export function streamThinking(
  body: { message: string; mode: ThinkingMode; context?: string; effort?: string },
  handlers: {
    onDecision?: (d: { think: boolean; mode: string; reason: string }) => void;
    onEffort?: (e: { level: string; label: string; max_steps: number; verify_retries: number; step_visibility: string }) => void;
    // WIDENED (2026-09-19) from (stage: string) to the full raw event.
    // Live per-step highlighting inside a chunk group needs to know
    // WHICH step just started (index/description/chunk_id), not just
    // the bare stage name -- see ThinkingSteps.tsx's StepsDetailSheet.
    onStageStart?: (e: { stage: string; index?: number; description?: string; chunk_id?: number }) => void;
    onStage?: (stage: ThinkingStage) => void;
    onRetry?: (reason: string) => void;
    onAborted?: (reason: string) => void;
    onAnswer?: (text: string) => void;
    onDone?: (result: any) => void;
    onError?: (err: string) => void;
    // CAPABILITY ROUTING EVENTS (2026-09-19). classify_capability()
    // (Conversation Intelligence Layer) streams which of
    // discussion/research/planning/full_build it chose for this turn,
    // and TaskLoop.stream_capability() ends a research/planning-only
    // run with a "capability_complete" event carrying the actual
    // finding/plan instead of a "done" (that event type is reserved
    // for the full_build loop). Both were previously unhandled here --
    // the switch below had no case for them -- so a research or
    // planning run's own conclusion silently never reached the UI at
    // all; only full_build's "done" event was ever wired up.
    onCapability?: (c: { capability: string; confidence?: number; source: string }) => void;
    onCapabilityComplete?: (c: { capability: string; content: any }) => void;
    // NARRATIVE + CHUNKING (2026-09-19). task_loop.py now yields prose
    // commentary at chunk boundaries (see its stream() docstring) plus
    // a chunk_id on every step event, so the UI can group steps under
    // collapsible "N steps" pills with real prose between them --
    // exactly the pattern UK pointed at in Claude's own UI.
    onNarrative?: (n: { content: string; chunk_id: number }) => void;
  },
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const token = sessionStorage.getItem('jarvis_token');
      const res = await fetch('/api/think/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        handlers.onError?.(`Stream shuru nahi hua (${res.status})`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line; the last chunk may
        // be partial, so it stays in the buffer until terminated.
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          try {
            const event = JSON.parse(line.slice(6));
            switch (event.type) {
              case 'decision': handlers.onDecision?.(event); break;
              case 'effort': handlers.onEffort?.(event); break;
              case 'stage_start': handlers.onStageStart?.(event); break;
              case 'stage': handlers.onStage?.(event); break;
              case 'capability': handlers.onCapability?.(event); break;
              case 'capability_complete': handlers.onCapabilityComplete?.(event); break;
              case 'narrative': handlers.onNarrative?.(event); break;
              case 'retry': handlers.onRetry?.(event.reason); break;
              case 'aborted': handlers.onAborted?.(event.reason); break;
              case 'answer': handlers.onAnswer?.(event.content); break;
              case 'done': handlers.onDone?.(event.result); break;
              case 'error': handlers.onError?.(event.error); break;
            }
          } catch {
            // A malformed frame is skipped rather than killing the run.
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') handlers.onError?.(err?.message ?? 'Stream fail hua.');
    }
  })();

  return () => controller.abort();
}
