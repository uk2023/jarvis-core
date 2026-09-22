import { useState, useEffect, useRef, useMemo } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  ChevronRight, ChevronDown, Check, Loader2, Sparkles, AlertTriangle,
  Brain, Layers, Settings, Terminal, Pencil, CheckCircle2, RotateCcw,
  FileSearch, Target,
} from 'lucide-react';
import MessageContent from './MessageContent';

/**
 * THINKING STEPS -- the Claude-style panel.
 *
 * UK asked for this repeatedly: "jaise Claude step by step think and
 * command run karta hai aur task complete karke last me saare turns ka
 * conclusion bhi deta hai + saath me jo steps liye jo kaam kiya wo
 * dikhe".
 *
 * REDESIGNED 2026-09-18 (UK, with a screenshot of Claude's own step
 * summary sheet: an icon in a small rounded box, a short action-verb
 * label -- "Running command", "Editing file" -- and tapping a row
 * opens the detail). Previously every step showed its FULL content
 * inline all the time, under a plain uppercase stage name ("WRITE",
 * "VERIFY") with no icon and no visual distinction between step
 * kinds. That is honest but not scannable -- a 6-step run reads as one
 * long wall of text, nothing like the tappable-row list UK pointed at.
 * Each step is now its own collapsible row: icon + Claude-style label
 * (mapped from the step's actual kind/stage, see STEP_ICON/STEP_LABEL
 * below) + a one-line preview, collapsed by default; tapping expands
 * it to the full content, rendered exactly as before (MessageContent,
 * so code still lands in a code box).
 *
 * WHAT THIS WILL NOT DO
 * =====================
 * It renders ONLY stages the server actually sent. There is no
 * placeholder step, no invented "Analysing your request…" while
 * waiting, no fabricated step count, no fabricated icon for a stage
 * that didn't happen. If JARVIS did one step, the panel shows one row.
 */

export interface ThinkingStep {
  stage: string;
  content: string;
  duration_ms?: number;
  ok?: boolean;
  // CHUNKING (2026-09-19). task_loop.py tags every execution-step
  // event with a chunk_id (increments after each verify step -- see
  // its stream() docstring). Undefined on older/legacy saved steps
  // and on thinking.py's plain stages -- treated as chunk 0.
  chunk_id?: number;
}

// Free-form deliberation stages (thinking.py) -- Claude-style English
// labels (2026-09-18, UK: "hinglish mat use karo, professional
// English term do"). "Samajh raha hun" -> "Understanding request", etc.
const STAGE_LABEL: Record<string, string> = {
  understand: 'Understanding request',
  explore: 'Exploring options',
  critique: 'Checking reasoning',
  answer: 'Composing answer',
};

// Coding/task-loop step kinds (task_loop.py, codebox.py, coding_agent/) --
// mapped to a Claude-style icon + short action-verb label. Falls back to
// STAGE_LABEL, then to the raw stage/kind string, for anything not
// listed here -- a step JARVIS actually took is never hidden just
// because its kind isn't in this table yet.
const STEP_ICON: Record<string, LucideIcon> = {
  understand: Brain,
  plan: Layers,
  system: Settings,
  code: Terminal,
  write: Pencil,
  run: Terminal,
  run_python: Terminal,
  verify: CheckCircle2,
  retry: RotateCcw,
  // CAPABILITY RESULTS (2026-09-19) -- research/planning-only runs
  // (see conversation_intelligence.py's classify_capability): these
  // used to arrive as a "capability_complete" event with no icon/label
  // mapping at all, since the event type wasn't even handled before
  // this fix -- see UserChatView.tsx's onCapabilityComplete.
  research: FileSearch,
  planning: Layers,
};

const STEP_LABEL: Record<string, string> = {
  understand: 'Understanding request',
  plan: 'Planning',
  system: 'Running system command',
  code: 'Writing code',
  write: 'Editing file',
  run: 'Running command',
  run_python: 'Running command',
  verify: 'Verifying',
  retry: 'Retrying',
  research: 'Research findings',
  planning: 'Plan',
};

function iconFor(stage: string): LucideIcon {
  return STEP_ICON[stage] ?? Sparkles;
}

function labelFor(stage: string): string {
  return STEP_LABEL[stage] ?? STAGE_LABEL[stage] ?? stage;
}

// EXECUTION_KINDS + TimelineEntry (2026-09-19) -- see the timeline
// useMemo in the default export below for how these combine narrative
// commentary with grouped step-chunks.
const EXECUTION_KINDS = new Set(['code', 'write', 'verify', 'system']);

type TimelineEntry =
  | { type: 'row'; step: ThinkingStep }
  | { type: 'narrative'; chunk_id: number; content: string }
  | { type: 'stepgroup'; chunk_id: number; steps: ThinkingStep[] };

// One-line preview shown on the collapsed row -- the content's first
// non-empty line, trimmed short. Markdown fences and leading symbols
// are stripped so the preview reads as plain text, not a truncated
// code block.
function previewFor(content: string): string {
  const firstLine = (content || '')
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l.length > 0) ?? '';
  const stripped = firstLine.replace(/^```[a-zA-Z0-9]*$/, '').replace(/^#+\s*/, '');
  if (stripped.length <= 90) return stripped;
  return stripped.slice(0, 90) + '…';
}

function StepRow({
  step,
  isDark,
  defaultOpen,
}: {
  step: ThinkingStep;
  isDark: boolean;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Icon = iconFor(step.stage);
  const label = labelFor(step.stage);
  const preview = previewFor(step.content);
  const failed = step.ok === false;

  return (
    <div
      className={`overflow-hidden rounded-xl border ${
        isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200 bg-white'
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center gap-2.5 px-2.5 py-2 text-left transition ${
          isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-slate-50'
        }`}
      >
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
            failed
              ? 'bg-amber-400/10 text-amber-400'
              : isDark
              ? 'bg-brand-400/10 text-brand-300'
              : 'bg-brand-50 text-brand-600'
          }`}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>

        <span className="min-w-0 flex-1">
          <span
            className={`block text-sm font-bold ${
              isDark ? 'text-slate-100' : 'text-slate-900'
            }`}
          >
            {label}
          </span>
          {!open && preview && (
            <span
              className={`block truncate text-[11px] ${
                isDark ? 'text-slate-500' : 'text-slate-500'
              }`}
            >
              {preview}
            </span>
          )}
        </span>

        {typeof step.duration_ms === 'number' && (
          <span className="shrink-0 text-[10px] text-slate-500">
            {Math.round(step.duration_ms)}ms
          </span>
        )}

        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform ${
            open ? 'rotate-90' : ''
          }`}
        />
      </button>

      {open && (
        <div
          className={`border-t px-3 py-2.5 text-xs leading-relaxed ${
            isDark ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-600'
          }`}
        >
          {/* MARKDOWN INSIDE STEPS TOO (2026-09-16). A [write] or
              [code] step's output is usually the actual code JARVIS
              produced -- same renderer as the chat body, so code
              lands in a code box here as well. */}
          <MessageContent text={step.content} isDark={isDark} />
        </div>
      )}
    </div>
  );
}

export default function ThinkingSteps({
  steps,
  currentStage,
  done,
  reason,
  error,
  conclusion,
  complete,
  stepCounts,
  narratives,
  liveStep,
  isDark = true,
}: {
  steps: ThinkingStep[];
  currentStage?: string | null;
  done?: boolean;
  reason?: string;
  error?: string | null;
  // REAL CONCLUSION (2026-09-19) -- see UserChatView.tsx's taskConclusion
  // doc comment. When present, this REPLACES the generic "N steps chale"
  // line below with what JARVIS actually found/concluded, grounded in
  // the real step record (task_loop.py's _conclude()), not invented here.
  conclusion?: string;
  complete?: boolean;
  stepCounts?: { completed: number; total: number };
  // NARRATIVE + LIVE CHUNKING (2026-09-19) -- see UserChatView.tsx's
  // narratives/runningStepMeta doc comments and task_loop.py's
  // stream() docstring. narratives are the prose interludes between
  // step chunks; liveStep is the ONE step currently in flight
  // (undefined once it completes and joins `steps` instead).
  narratives?: { content: string; chunk_id: number }[];
  liveStep?: { stage: string; index?: number; description?: string; chunk_id?: number } | null;
  isDark?: boolean;
}) {
  // OPEN BY DEFAULT (2026-09-16). UK: "steps bhi dikhe jaise Claude
  // mein dikhte hain." A collapsed panel hides exactly the thing he
  // asked to watch -- he still gets a summary line to collapse it back
  // down, but he should not have to click to see work in progress.
  // This is the PANEL-level toggle (all steps at once); each
  // individual step ALSO has its own collapse/expand -- see StepRow
  // above -- for the Claude-style "tap a row for detail" behaviour.
  const [open, setOpen] = useState(true);
  // SUMMARY VIEW (2026-09-19, UK: screenshot of Claude's own "Summary"
  // bottom sheet -- a vertical dot-timeline, icon-boxed nodes for tool
  // steps, bold headings, lighter subtext, ending on a highlighted
  // final node). A SEPARATE view from the inline step list above --
  // this is the "tap to see the whole run at a glance" summary, shown
  // only once the run is done, built from the exact same `steps` array
  // (never a re-generated or re-worded version of it).
  const [showSummary, setShowSummary] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState(0);

  // Live timer while working. Stops on completion so the number settles
  // instead of ticking forever.
  useEffect(() => {
    if (done) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 200);
    return () => clearInterval(id);
  }, [done]);

  useEffect(() => {
    if (open && !done) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [steps.length, currentStage, open, done]);

  // CHUNKED TIMELINE (2026-09-19) -- groups consecutive execution-kind
  // steps (code/write/verify/system -- the ones task_loop.py actually
  // tags with chunk_id) into a single collapsible "N steps" entry, with
  // any narrative for that chunk placed right before it. Reasoning
  // stages (understand/plan/research/planning/retry/answer) are NOT
  // grouped -- they render as their own row exactly as before, since
  // they aren't part of task_loop's chunking scheme and already read
  // fine standalone.
  const timeline = useMemo<TimelineEntry[]>(() => {
    const narrativeByChunk = new Map<number, string>();
    (narratives || []).forEach((n) => narrativeByChunk.set(n.chunk_id, n.content));

    const entries: TimelineEntry[] = [];
    let currentGroup: ThinkingStep[] | null = null;
    let currentChunk: number | null = null;

    const flush = () => {
      if (currentGroup && currentGroup.length > 0) {
        entries.push({ type: 'stepgroup', chunk_id: currentChunk ?? 0, steps: currentGroup });
      }
      currentGroup = null;
      currentChunk = null;
    };

    for (const step of steps) {
      if (EXECUTION_KINDS.has(step.stage)) {
        const cid = step.chunk_id ?? 0;
        if (currentChunk !== cid) {
          flush();
          const narr = narrativeByChunk.get(cid);
          if (narr) entries.push({ type: 'narrative', chunk_id: cid, content: narr });
          currentChunk = cid;
          currentGroup = [];
        }
        currentGroup!.push(step);
      } else {
        flush();
        entries.push({ type: 'row', step });
      }
    }
    flush();
    return entries;
  }, [steps, narratives]);

  if (steps.length === 0 && !currentStage && !error) return null;

  const totalMs = steps.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  const stepWord = steps.length === 1 ? 'step' : 'steps';
  const stepCountLabel = stepCounts ? `${stepCounts.completed}/${stepCounts.total}` : `${steps.length}`;

  const summary = error
    ? 'Thinking rukk gayi'
    : done
    ? `Socha — ${stepCountLabel} ${stepWord}${totalMs ? `, ${(totalMs / 1000).toFixed(1)}s` : ''}`
    : `Soch raha hun… ${elapsed.toFixed(1)}s`;

  // ONLY THE MOST RECENT ROW starts expanded while the run is still in
  // progress -- see the timeline render below (defaultOpen uses the
  // entry's own position in `timeline`, not this raw step count).

  return (
    <div
      className={`mb-2 overflow-hidden rounded-2xl border text-left ${
        isDark ? 'border-white/10 bg-white/[0.03]' : 'border-slate-200 bg-slate-50'
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center gap-2 px-3 py-2 text-xs transition ${
          isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-800'
        }`}
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
        />
        {error ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
        ) : done ? (
          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
        ) : (
          <Sparkles className="h-3.5 w-3.5 shrink-0 animate-pulse text-brand-400" />
        )}
        <span className="text-[13.5px] font-bold">{summary}</span>
        {reason && (
          <span className="ml-auto hidden truncate pl-3 text-[11px] opacity-60 sm:inline">
            {reason}
          </span>
        )}
      </button>

      {/* SUMMARY TOGGLE (2026-09-19) -- separate row, only once the run
          is done and there's something worth summarizing. Opens the
          dot-timeline view below instead of/alongside the step list. */}
      {done && steps.length > 0 && (
        <button
          type="button"
          onClick={() => setShowSummary((s) => !s)}
          className={`flex w-full items-center gap-2 border-t px-3 py-1.5 text-[11.5px] font-semibold transition ${
            isDark
              ? 'border-white/10 text-brand-300 hover:bg-white/[0.03]'
              : 'border-slate-200 text-brand-600 hover:bg-slate-100'
          }`}
        >
          <Target className="h-3 w-3 shrink-0" />
          {showSummary ? 'Hide summary' : 'View summary'}
          {showSummary ? (
            <ChevronDown className="ml-auto h-3 w-3" />
          ) : (
            <ChevronRight className="ml-auto h-3 w-3" />
          )}
        </button>
      )}

      {showSummary && done && (
        <div
          className={`border-t px-3 py-3 ${
            isDark ? 'border-white/10 bg-black/10' : 'border-slate-200 bg-white'
          }`}
        >
          <SummaryTimeline
            steps={steps}
            conclusion={conclusion}
            complete={complete}
            isDark={isDark}
          />
        </div>
      )}

      {open && (
        <div
          className={`space-y-1.5 border-t px-2.5 py-2.5 ${
            isDark ? 'border-white/10' : 'border-slate-200'
          }`}
        >
          {timeline.map((entry, i) => {
            if (entry.type === 'narrative') {
              // PROSE INTERLUDE (2026-09-19) -- UK's screenshot ask:
              // "Found a deeper root cause..." style paragraphs between
              // collapsed step groups. Plain text, no box, no icon --
              // this is JARVIS's own commentary, not a step.
              return (
                <p
                  key={`narrative-${entry.chunk_id}-${i}`}
                  className={`px-1 py-1.5 text-[13px] font-semibold leading-snug ${
                    isDark ? 'text-slate-200' : 'text-slate-800'
                  }`}
                >
                  {entry.content}
                </p>
              );
            }
            if (entry.type === 'stepgroup') {
              const isLiveGroup = !done && liveStep?.chunk_id === entry.chunk_id;
              return (
                <ChunkGroupPill
                  key={`chunk-${entry.chunk_id}-${i}`}
                  chunkSteps={entry.steps}
                  isDark={isDark}
                  isLive={isLiveGroup}
                  liveStep={isLiveGroup ? liveStep : null}
                />
              );
            }
            return (
              <StepRow
                key={`${entry.step.stage}-${i}`}
                step={entry.step}
                isDark={isDark}
                defaultOpen={!done && i === timeline.length - 1}
              />
            );
          })}

          {/* In-flight stage: spinner and the stage name ONLY. No
              placeholder reasoning -- see the component note above. */}
          {!done && currentStage && !steps.some((s) => s.stage === currentStage) && (
            <div className="flex items-center gap-2 px-1 py-1 text-xs text-slate-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              {labelFor(currentStage)}
            </div>
          )}

          {error && (
            <p className="px-1 py-1 text-xs text-amber-300">
              {error}
            </p>
          )}

          {/* Conclusion: what was actually done. Uses the REAL
              conclusion from task_loop.py's _conclude() when the
              server sent one (grounded in the actual step record);
              falls back to the old generic count-based line only when
              no real conclusion arrived (e.g. thinking.py's staged
              reasoner, which has no _conclude() equivalent). */}
          {done && steps.length > 0 && (
            <div
              className={`mt-1 border-t pt-2 px-1 text-[11.5px] leading-relaxed ${
                isDark ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-600'
              }`}
            >
              {conclusion ? (
                <>
                  <span className={`mr-1 font-semibold ${complete === false ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {complete === false ? 'Incomplete:' : 'Done:'}
                  </span>
                  {conclusion}
                </>
              ) : (
                <>
                  {stepCountLabel} {stepWord} chale
                  {totalMs ? ` (${(totalMs / 1000).toFixed(1)}s)` : ''}
                  {steps.some((s) => s.ok === false) && ' — kuch step fail hue'}
                  . Jawab neeche hai.
                </>
              )}
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

// SUMMARY TIMELINE (2026-09-19) -- the vertical dot-timeline UK asked
// for, matching Claude's own "Summary" sheet: an icon-in-a-box node
// per tool-kind step, a plain dot for narrative-only steps, a BOLD
// heading (the step's label) with a lighter one-line subtext beneath,
// connected by a vertical rail, ending on a highlighted final node for
// the conclusion. Built from the exact same `steps` prop the inline
// panel already renders -- nothing here is re-derived or reworded,
// only laid out differently.
// CHUNK GROUP PILL (2026-09-19) -- the collapsed "N steps >" link from
// UK's screenshots. Tapping it opens StepsDetailSheet, a bottom sheet
// showing this ONE chunk's steps in full -- icons, live highlight for
// whichever step is still in flight, complete (non-truncated) output
// per step. Collapsed by default, same as Claude's own reference UI;
// pulses when this is the chunk currently executing.
function ChunkGroupPill({
  chunkSteps,
  isDark,
  isLive,
  liveStep,
}: {
  chunkSteps: ThinkingStep[];
  isDark: boolean;
  isLive: boolean;
  liveStep?: { stage: string; description?: string } | null;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const n = chunkSteps.length + (liveStep ? 1 : 0);
  const anyFailed = chunkSteps.some((s) => s.ok === false);

  return (
    <>
      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        className={`flex w-full items-center gap-2 rounded-xl border px-2.5 py-2 text-left transition ${
          isLive
            ? isDark
              ? 'border-brand-400/40 bg-brand-400/[0.06]'
              : 'border-brand-300 bg-brand-50'
            : isDark
            ? 'border-white/10 bg-white/[0.02] hover:bg-white/[0.04]'
            : 'border-slate-200 bg-white hover:bg-slate-50'
        }`}
      >
        {isLive ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand-400" />
        ) : anyFailed ? (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
        )}
        <span className={`text-[12.5px] font-semibold ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
          {n} step{n === 1 ? '' : 's'}
        </span>
        {isLive && (
          <span className="text-[11px] text-brand-400">running…</span>
        )}
        <ChevronRight className="ml-auto h-3.5 w-3.5 shrink-0 text-slate-500" />
      </button>

      {sheetOpen && (
        <StepsDetailSheet
          chunkSteps={chunkSteps}
          liveStep={liveStep}
          isDark={isDark}
          onClose={() => setSheetOpen(false)}
        />
      )}
    </>
  );
}

// STEPS DETAIL SHEET (2026-09-19) -- the bottom sheet UK's screenshots
// show: an "X" close button, a centered title, and a scrollable list of
// steps below. Unlike the collapsed inline pill, every step here shows
// its FULL content (no truncation) and the currently-running step (if
// any, in this chunk) gets a distinct pulsing/live treatment instead of
// a static icon -- built from `liveStep`, which is only ever set for a
// step that has not completed yet (see UserChatView.tsx: cleared the
// instant that step's own completion event arrives).
function StepsDetailSheet({
  chunkSteps,
  liveStep,
  isDark,
  onClose,
}: {
  chunkSteps: ThinkingStep[];
  liveStep?: { stage: string; description?: string } | null;
  isDark: boolean;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={`relative z-10 max-h-[80vh] w-full overflow-y-auto rounded-t-2xl border-t sm:max-w-md sm:rounded-2xl sm:border ${
          isDark ? 'border-white/10 bg-slate-950' : 'border-slate-200 bg-white'
        }`}
      >
        <div
          className={`sticky top-0 flex items-center justify-between border-b px-4 py-3 ${
            isDark ? 'border-white/10 bg-slate-950' : 'border-slate-200 bg-white'
          }`}
        >
          <button
            type="button"
            onClick={onClose}
            className={`rounded-full p-1 transition ${isDark ? 'text-slate-400 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'}`}
            aria-label="Close"
          >
            <ChevronDown className="h-5 w-5" />
          </button>
          <span className={`text-base font-bold ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
            Steps
          </span>
          <span className="w-7" aria-hidden />
        </div>

        <div className="space-y-2.5 px-4 py-4">
          {chunkSteps.map((step, i) => {
            const Icon = iconFor(step.stage);
            const failed = step.ok === false;
            return (
              <div
                key={`${step.stage}-detail-${i}`}
                className={`rounded-xl border p-3 ${
                  isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200 bg-slate-50'
                }`}
              >
                <div className="mb-1.5 flex items-center gap-2">
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                      failed
                        ? 'bg-amber-400/10 text-amber-400'
                        : isDark
                        ? 'bg-brand-400/10 text-brand-300'
                        : 'bg-brand-50 text-brand-600'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <span className={`text-sm font-bold ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
                    {labelFor(step.stage)}
                  </span>
                  {typeof step.duration_ms === 'number' && (
                    <span className="ml-auto shrink-0 text-[10px] text-slate-500">
                      {Math.round(step.duration_ms)}ms
                    </span>
                  )}
                </div>
                <div className={`text-xs leading-relaxed ${isDark ? 'text-slate-400' : 'text-slate-600'}`}>
                  <MessageContent text={step.content} isDark={isDark} />
                </div>
              </div>
            );
          })}

          {/* LIVE STEP -- currently in flight, hasn't completed (and
              therefore isn't in chunkSteps at all yet). Pulsing icon,
              no content box (there is none yet), just the description
              it started with. */}
          {liveStep && (
            <div
              className={`rounded-xl border p-3 ${
                isDark ? 'border-brand-400/40 bg-brand-400/[0.06]' : 'border-brand-300 bg-brand-50'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-400/15 text-brand-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                </span>
                <span className={`text-sm font-bold ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
                  {labelFor(liveStep.stage)}
                </span>
                <span className="text-[11px] text-brand-400">running…</span>
              </div>
              {liveStep.description && (
                <p className={`mt-1.5 text-xs leading-relaxed ${isDark ? 'text-slate-400' : 'text-slate-600'}`}>
                  {liveStep.description}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryTimeline({
  steps,
  conclusion,
  complete,
  isDark,
}: {
  steps: ThinkingStep[];
  conclusion?: string;
  complete?: boolean;
  isDark: boolean;
}) {
  const railColor = isDark ? 'bg-white/10' : 'bg-slate-200';

  return (
    <div className="relative">
      {steps.map((step, i) => {
        const Icon = iconFor(step.stage);
        const label = labelFor(step.stage);
        const preview = previewFor(step.content);
        const failed = step.ok === false;
        const isLast = i === steps.length - 1 && !conclusion;

        return (
          <div key={`${step.stage}-summary-${i}`} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast && (
              <span
                className={`absolute left-[13px] top-7 h-[calc(100%-0.5rem)] w-px ${railColor}`}
                aria-hidden
              />
            )}
            <span
              className={`z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${
                failed
                  ? 'border-amber-400/40 bg-amber-400/10 text-amber-400'
                  : isDark
                  ? 'border-brand-400/30 bg-brand-400/10 text-brand-300'
                  : 'border-brand-200 bg-brand-50 text-brand-600'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className={`text-sm font-bold ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
                {label}
              </p>
              {preview && (
                <p className={`mt-0.5 truncate text-[12px] ${isDark ? 'text-slate-500' : 'text-slate-500'}`}>
                  {preview}
                </p>
              )}
            </div>
          </div>
        );
      })}

      {/* Final, highlighted node -- the real conclusion, styled to
          stand out the way Claude's last "Reckoning" dot does (an
          accent color, not just another gray row). Only rendered when
          a real conclusion string arrived -- never a placeholder. */}
      {conclusion && (
        <div className="relative flex gap-3">
          <span
            className={`z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${
              complete === false
                ? 'border-amber-400/50 bg-amber-400/15 text-amber-400'
                : 'border-emerald-400/50 bg-emerald-400/15 text-emerald-400'
            }`}
          >
            <Check className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <p className={`text-sm font-bold ${complete === false ? 'text-amber-400' : 'text-emerald-400'}`}>
              {complete === false ? 'Incomplete' : 'Conclusion'}
            </p>
            <p className={`mt-0.5 text-[12.5px] leading-relaxed ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
              {conclusion}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
