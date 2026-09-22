import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot, Loader2, Play, ShieldAlert, Check, X, FileCode, GitBranch,
  CheckCircle2, XCircle, Package, ChevronRight, Wrench, Search,
  AlertTriangle, CircleDot, Circle,
} from 'lucide-react';
import { api } from '../api/client';
import { TabHeader } from './TabHeader';

/**
 * CODING AGENT WORKSPACE -- the repo-scale surface.
 *
 * Deliberately separate from CodeBoxScreen, which stays what it is: ONE
 * script, write-run-fix, in your own sandbox. This panel is the other
 * depth of the same capability -- a whole project, many files, plan ->
 * tools -> tests -> fix -> verify -> package.
 *
 * AUTHORITY NOTE: every button here calls the SAME Brain methods that
 * cli.py's /coding_agent and codebase.py's REPL call
 * (brain.run_coding_agent / resume_coding_agent). This is an interface
 * onto JARVIS's capability, never a second agent implementation -- if
 * the loop or the approval rules change in core/skills/coding_agent/,
 * this panel picks that up with no change here.
 *
 * Everything rendered below comes from the server's real task record.
 * When there is no run yet, this shows an honest empty state -- never a
 * fabricated plan or invented progress.
 */

interface ToolCall { id: string; tool_name: string; arguments: Record<string, any>; reason?: string }
interface ToolResult { ok: boolean; output?: string; skipped?: boolean; skip_reason?: string; duration_ms?: number; detail?: any }
interface Observation { step_index: number; phase: string; tool_call?: ToolCall | null; result?: ToolResult | null; note?: string }
interface Verification { method: string; passed: boolean; output?: string }
interface AgentTask {
  id: string; objective: string; status: string; phase: string;
  repo_path?: string; iteration?: number; max_iterations?: number;
  plan?: ToolCall[]; observations?: Observation[]; verifications?: Verification[];
  errors?: string[]; artifacts?: string[]; subtasks?: string[];
  result_summary?: string | null;
  pending_approval?: { call: ToolCall; reason: string } | null;
}
interface ToolSpec { name: string; description: string; risk: string; destructive: boolean; read_only: boolean }

const STATUS_STYLE: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  COMPLETED: { bg: 'bg-emerald-500/10 border-emerald-500/30', text: 'text-emerald-300', dot: 'bg-emerald-400', label: 'Completed' },
  RUNNING: { bg: 'bg-indigo-500/10 border-indigo-500/30', text: 'text-indigo-300', dot: 'bg-indigo-400 animate-pulse', label: 'Running' },
  PLANNING: { bg: 'bg-indigo-500/10 border-indigo-500/30', text: 'text-indigo-300', dot: 'bg-indigo-400 animate-pulse', label: 'Planning' },
  VERIFYING: { bg: 'bg-sky-500/10 border-sky-500/30', text: 'text-sky-300', dot: 'bg-sky-400 animate-pulse', label: 'Verifying' },
  WAITING_APPROVAL: { bg: 'bg-amber-500/10 border-amber-500/40', text: 'text-amber-300', dot: 'bg-amber-400 animate-pulse', label: 'Needs your approval' },
  FAILED: { bg: 'bg-red-500/10 border-red-500/30', text: 'text-red-300', dot: 'bg-red-400', label: 'Failed' },
  BLOCKED: { bg: 'bg-red-500/10 border-red-500/30', text: 'text-red-300', dot: 'bg-red-400', label: 'Blocked' },
  CANCELLED: { bg: 'bg-slate-500/10 border-slate-500/30', text: 'text-slate-300', dot: 'bg-slate-400', label: 'Cancelled' },
  PENDING: { bg: 'bg-slate-500/10 border-slate-500/30', text: 'text-slate-300', dot: 'bg-slate-400', label: 'Pending' },
};

const PHASES = ['understand', 'discover', 'plan', 'approve', 'execute', 'verify', 'fix', 'package', 'done'];

const RISK_COLOR: Record<string, string> = {
  read_only: 'text-slate-400 border-slate-700',
  low: 'text-emerald-300 border-emerald-500/30',
  medium: 'text-amber-300 border-amber-500/30',
  high: 'text-red-300 border-red-500/30',
};

/** Renders a unified diff with per-line colouring -- adapted from the
 *  Claude Code source's StructuredDiff concept, kept dependency-free. */
function DiffView({ diff }: { diff: string }) {
  const lines = diff.split('\n');
  return (
    <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[11px] leading-relaxed">
      {lines.map((line, i) => {
        let cls = 'text-slate-400';
        if (line.startsWith('+++') || line.startsWith('---')) cls = 'text-slate-500';
        else if (line.startsWith('@@')) cls = 'text-sky-400';
        else if (line.startsWith('+')) cls = 'bg-emerald-500/10 text-emerald-300';
        else if (line.startsWith('-')) cls = 'bg-red-500/10 text-red-300';
        return <div key={i} className={`${cls} px-1`}>{line || ' '}</div>;
      })}
    </pre>
  );
}

function ToolCallRow({ obs }: { obs: Observation }) {
  const [open, setOpen] = useState(false);
  const call = obs.tool_call;
  const result = obs.result;
  if (!call) {
    return (
      <div className="flex items-start gap-2 px-3 py-1.5 text-xs text-slate-500">
        <CircleDot className="mt-0.5 h-3 w-3 shrink-0" />
        <span className="uppercase tracking-wide opacity-60">{obs.phase}</span>
        <span className="min-w-0 flex-1">{obs.note}</span>
      </div>
    );
  }
  const ok = result?.ok;
  const skipped = result?.skipped;
  const diff = result?.detail?.diff as string | undefined;

  return (
    <div className="border-b border-slate-800/60 last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left transition hover:bg-slate-800/40"
      >
        <ChevronRight className={`mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500 transition ${open ? 'rotate-90' : ''}`} />
        {skipped ? <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
          : ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-xs font-medium text-slate-200">{call.tool_name}</span>
            {call.arguments?.path && (
              <span className="truncate font-mono text-[11px] text-slate-500">{call.arguments.path}</span>
            )}
          </div>
          {call.reason && <p className="mt-0.5 truncate text-[11px] text-slate-500">{call.reason}</p>}
        </div>
        {typeof result?.duration_ms === 'number' && (
          <span className="shrink-0 text-[11px] text-slate-600">{Math.round(result.duration_ms)}ms</span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 pl-9">
          <div className="rounded-lg bg-slate-950/60 p-2">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Arguments</p>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-400">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          </div>
          {diff && (<><p className="mt-2 text-[11px] uppercase tracking-wide text-slate-500">Diff</p><DiffView diff={diff} /></>)}
          {result?.output && !diff && (
            <>
              <p className="mt-2 text-[11px] uppercase tracking-wide text-slate-500">Output</p>
              <pre className={`mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-2 font-mono text-[11px] ${ok ? 'text-slate-300' : 'text-red-300'}`}>
                {result.output}
              </pre>
            </>
          )}
          {skipped && <p className="mt-2 text-[11px] text-amber-300">Skipped: {result?.skip_reason}</p>}
        </div>
      )}
    </div>
  );
}

/** Claude-style plan checklist: the current plan's tool calls rendered
 *  as a task list, each item's checkmark filling in live as its
 *  matching observation arrives -- pending (hollow circle), running
 *  (spinner, only for the very next unstarted item while the task is
 *  active), done (check), failed (x). This is an ORIGINAL component
 *  built for JARVIS -- Claude Code's own todo/plan rendering lives in
 *  a terminal (Ink) renderer with dependencies (bun:bundle, internal
 *  AppState/keybinding modules) that do not exist outside that repo,
 *  so the visual PATTERN is reproduced here in real, compiling
 *  Tailwind/React rather than the source copied in. */
function PlanChecklist({ task }: { task: AgentTask }) {
  const plan = task.plan ?? [];
  if (plan.length === 0) return null;

  // Match each planned call to its outcome by call id, in the order
  // observations actually arrived -- a call can appear more than once
  // across fix iterations, so id lookup (not index) keeps each planned
  // item pointed at ITS OWN result.
  const resultByCallId = new Map<string, ToolResult | undefined>();
  (task.observations ?? []).forEach((o) => {
    if (o.tool_call) resultByCallId.set(o.tool_call.id, o.result ?? undefined);
  });

  const isLive = ['RUNNING', 'PLANNING', 'VERIFYING'].includes(task.status);
  let nextPendingMarked = false;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <p className="mb-2 text-[11px] uppercase tracking-wide text-slate-500">
        Plan -- iteration {task.iteration}
      </p>
      <div className="space-y-1.5">
        {plan.map((call) => {
          const result = resultByCallId.get(call.id);
          const done = result != null;
          const ok = result?.ok && !result?.skipped;
          const failed = done && !ok;
          const isNextPending = isLive && !done && !nextPendingMarked;
          if (isNextPending) nextPendingMarked = true;

          return (
            <div key={call.id} className="flex items-start gap-2 text-sm">
              {failed ? (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
              ) : done ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
              ) : isNextPending ? (
                <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-indigo-400" />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-slate-600" />
              )}
              <div className="min-w-0 flex-1">
                <span className={`font-mono text-xs ${done ? 'text-slate-300' : 'text-slate-500'}`}>
                  {call.tool_name}
                </span>
                {call.arguments?.path && (
                  <span className="ml-1.5 truncate font-mono text-[11px] text-slate-500">
                    {call.arguments.path}
                  </span>
                )}
                {call.reason && (
                  <p className="mt-0.5 truncate text-[11px] text-slate-600">{call.reason}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function CodingAgentWorkspace() {
  const [objective, setObjective] = useState('');
  const [repoPath, setRepoPath] = useState('');
  const [running, setRunning] = useState(false);
  const [approving, setApproving] = useState(false);
  const [task, setTask] = useState<AgentTask | null>(null);
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTools, setShowTools] = useState(false);
  const traceEnd = useRef<HTMLDivElement>(null);

  const loadState = useCallback(async () => {
    try {
      const res = await api.codingAgentState();
      setTask(res?.task ?? null);
      setTools(res?.tools ?? []);
      setWorkspace(res?.workspace ?? null);
      setError(null);
    } catch (err: any) {
      setError(err?.message ?? 'Agent state load nahi hua.');
    }
  }, []);

  useEffect(() => { loadState(); }, [loadState]);

  // Poll only while something is genuinely in flight -- no background
  // polling on an idle or finished task.
  useEffect(() => {
    const live = running || (task && !['COMPLETED', 'FAILED', 'CANCELLED', 'WAITING_APPROVAL'].includes(task.status));
    if (!live) return;
    const id = setInterval(loadState, 2000);
    return () => clearInterval(id);
  }, [running, task, loadState]);

  useEffect(() => { traceEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [task?.observations?.length]);

  const handleRun = async () => {
    if (!objective.trim()) return;
    setRunning(true); setError(null);
    try {
      await api.codingAgentRun({ objective, repo_path: repoPath.trim() || null, max_iterations: 6 });
      await loadState();
    } catch (err: any) {
      setError(err?.message ?? 'Coding agent run fail hua.');
    } finally { setRunning(false); }
  };

  const handleApproval = async (approve: boolean) => {
    setApproving(true); setError(null);
    try {
      await api.codingAgentApprove(approve);
      await loadState();
    } catch (err: any) {
      setError(err?.message ?? 'Approval bheji nahi ja saki.');
    } finally { setApproving(false); }
  };

  const style = STATUS_STYLE[task?.status ?? 'PENDING'] ?? STATUS_STYLE.PENDING;
  const lastVerification = task?.verifications?.[task.verifications.length - 1];
  const filesTouched = useMemo(() => {
    const s = new Set<string>();
    (task?.observations ?? []).forEach((o) => { const p = o.tool_call?.arguments?.path; if (p) s.add(p); });
    return [...s];
  }, [task?.observations]);
  const phaseIndex = PHASES.indexOf(task?.phase ?? '');

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 md:p-6">
      <TabHeader
        icon={Bot}
        category="CODING AGENT"
        title="Repo-scale Coding Agent"
        subtitle={workspace ? `Workspace: ${workspace}` : 'Poora project — plan, edit, test, fix, package'}
        controls={
          <button
            onClick={() => setShowTools((s) => !s)}
            className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-200 transition hover:border-indigo-500/60"
          >
            <Wrench className="h-3.5 w-3.5" /> {tools.length} tools
          </button>
        }
      />

      {showTools && tools.length > 0 && (
        <div className="grid gap-1.5 rounded-xl border border-slate-800 bg-slate-900/60 p-3 sm:grid-cols-2">
          {tools.map((t) => (
            <div key={t.name} className="flex items-start gap-2 rounded-lg bg-slate-950/40 p-2">
              <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase ${RISK_COLOR[t.risk] ?? RISK_COLOR.low}`}>
                {t.risk}
              </span>
              <div className="min-w-0">
                <p className="font-mono text-xs text-slate-200">{t.name}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{t.description}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Objective input */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
        <textarea
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          placeholder="Kya banana/fix karna hai? Jaise: 'ek FastAPI todo backend banao tests ke saath' ya 'is project ke failing tests fix karo'"
          className="h-20 w-full resize-none rounded-lg bg-slate-800/60 p-2.5 text-sm text-slate-200 outline-none placeholder:text-slate-500 focus:ring-1 focus:ring-indigo-500"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={repoPath}
            onChange={(e) => setRepoPath(e.target.value)}
            placeholder="Existing project path (khaali chhodo = naya sandbox project)"
            className="min-w-0 flex-1 rounded-lg bg-slate-800/60 px-2.5 py-1.5 font-mono text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:ring-1 focus:ring-indigo-500"
          />
          <button
            onClick={handleRun}
            disabled={running || !objective.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-40"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Chal raha hai...' : 'Run agent'}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">Agent se baat nahi ho paayi</p><p className="mt-1 opacity-90">{error}</p></div>
        </div>
      )}

      {/* APPROVAL GATE -- the one thing that must never be missable */}
      {task?.status === 'WAITING_APPROVAL' && task.pending_approval && (
        <div className="rounded-xl border-2 border-amber-500/50 bg-amber-500/10 p-4">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-amber-200">Aapki permission chahiye</h3>
              <p className="mt-1 text-xs text-amber-100/80">{task.pending_approval.reason}</p>
              <div className="mt-2 rounded-lg bg-black/30 p-2">
                <p className="font-mono text-xs text-amber-200">{task.pending_approval.call.tool_name}</p>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-amber-100/70">
                  {JSON.stringify(task.pending_approval.call.arguments, null, 2)}
                </pre>
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => handleApproval(true)} disabled={approving}
                  className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-500 disabled:opacity-40"
                >
                  {approving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Approve
                </button>
                <button
                  onClick={() => handleApproval(false)} disabled={approving}
                  className="flex items-center gap-1.5 rounded-lg border border-slate-600 bg-slate-800 px-4 py-1.5 text-xs font-medium text-slate-200 transition hover:border-red-500/50 disabled:opacity-40"
                >
                  <X className="h-3.5 w-3.5" /> Deny
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!task ? (
        <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 p-10 text-center">
          <Bot className="h-8 w-8 text-slate-700" />
          <p className="mt-3 text-sm text-slate-400">Abhi tak koi coding-agent run nahi hua.</p>
          <p className="mt-1 max-w-md text-xs text-slate-600">
            Upar objective likho, ya normal chat mein bolo — JARVIS khud agent chala dega.
            CLI se: <span className="font-mono">/coding_agent &lt;objective&gt;</span>, terminal se: <span className="font-mono">python3 codebase.py</span>
          </p>
        </div>
      ) : (
        <>
          {/* Status + phase rail */}
          <div className={`rounded-xl border p-3 ${style.bg}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${style.dot}`} />
                <span className={`text-sm font-semibold ${style.text}`}>{style.label}</span>
                <span className="text-xs text-slate-500">
                  iteration {task.iteration}/{task.max_iterations}
                </span>
              </div>
              {task.repo_path && <span className="font-mono text-[11px] text-slate-500">{task.repo_path}</span>}
            </div>
            <p className="mt-2 text-sm text-slate-200">{task.objective}</p>
            {task.result_summary && <p className="mt-1 text-xs text-slate-400">{task.result_summary}</p>}

            <div className="mt-3 flex flex-wrap gap-1">
              {PHASES.map((p, i) => (
                <span
                  key={p}
                  className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                    i === phaseIndex ? 'bg-indigo-500/30 text-indigo-200'
                      : i < phaseIndex ? 'bg-slate-700/40 text-slate-400' : 'text-slate-700'
                  }`}
                >{p}</span>
              ))}
            </div>
          </div>

          <PlanChecklist task={task} />

          {/* Summary strip */}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
              <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-slate-500">
                <FileCode className="h-3.5 w-3.5" /> Files touched
              </p>
              {filesTouched.length === 0 ? (
                <p className="mt-1.5 text-xs text-slate-600">Koi file nahi</p>
              ) : (
                <ul className="mt-1.5 max-h-24 space-y-0.5 overflow-y-auto">
                  {filesTouched.map((f) => <li key={f} className="truncate font-mono text-xs text-slate-300">{f}</li>)}
                </ul>
              )}
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
              <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-slate-500">
                <GitBranch className="h-3.5 w-3.5" /> Verification
              </p>
              {!lastVerification ? (
                <p className="mt-1.5 text-xs text-slate-600">Abhi nahi chali</p>
              ) : (
                <>
                  <p className={`mt-1.5 flex items-center gap-1.5 text-xs ${lastVerification.passed ? 'text-emerald-300' : 'text-red-300'}`}>
                    {lastVerification.passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                    {lastVerification.method}: {lastVerification.passed ? 'PASSED' : 'FAILED'}
                  </p>
                  {!lastVerification.passed && lastVerification.output && (
                    <pre className="mt-1 max-h-20 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-red-300/70">
                      {lastVerification.output}
                    </pre>
                  )}
                </>
              )}
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
              <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-slate-500">
                <Package className="h-3.5 w-3.5" /> Artifacts
              </p>
              {(task.artifacts?.length ?? 0) === 0 ? (
                <p className="mt-1.5 text-xs text-slate-600">Koi package nahi bana</p>
              ) : (
                <ul className="mt-1.5 space-y-0.5">
                  {task.artifacts!.map((a) => <li key={a} className="truncate font-mono text-xs text-emerald-300">{a}</li>)}
                </ul>
              )}
            </div>
          </div>

          {/* Live trace */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            <div className="flex items-center gap-1.5 border-b border-slate-800 px-3 py-2">
              <Search className="h-3.5 w-3.5 text-slate-500" />
              <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                Execution trace
              </span>
              <span className="text-xs text-slate-600">({task.observations?.length ?? 0} steps)</span>
            </div>
            <div className="min-h-[200px] flex-1 overflow-y-auto">
              {(task.observations ?? []).map((o) => <ToolCallRow key={o.step_index} obs={o} />)}
              <div ref={traceEnd} />
            </div>
          </div>

          {(task.errors?.length ?? 0) > 0 && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-3">
              <p className="text-[11px] uppercase tracking-wide text-red-400">Errors</p>
              <ul className="mt-1 space-y-0.5">
                {task.errors!.map((e, i) => <li key={i} className="text-xs text-red-200">{e}</li>)}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
