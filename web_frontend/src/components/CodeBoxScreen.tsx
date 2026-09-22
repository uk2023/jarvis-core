import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Play, Upload, FileCode, Terminal as TerminalIcon, Loader2, AlertTriangle,
  ShieldCheck, Sparkles, Trash2, FolderOpen,
} from 'lucide-react';
import { api } from '../api/client';

/**
 * CODEBOX -- a dedicated surface, deliberately not the chat.
 *
 * UK's point (2026-09-13): chat should always keep a copy-pasteable code
 * block, but real coding needs its own page with an editor, a terminal
 * and files that persist. Mixing the two makes both worse -- a chat
 * transcript is a bad place to iterate on a file, and an editor is a bad
 * place to have a conversation.
 *
 * Everything here runs in the caller's OWN sandbox, decided server-side
 * from their session. The UI never sends a username or role; if it did,
 * anyone could type someone else's name and land in their directory.
 */

interface RunResult {
  ok?: boolean;
  // The backend returns ONE combined `output` field (codebox.Step.as_dict()
  // -- stderr is already appended into it server-side under an "[stderr]"
  // marker). This used to declare stdout/stderr, which the API never sends,
  // so the Output panel rendered nothing even on a successful run.
  output?: string;
  qa?: { layers?: Record<string, boolean | null>; danger_flags?: string[]; resource_flags?: string[] };
  exit_code?: number | null;
  duration_ms?: number;
  workdir?: string;
  files?: string[];
  error?: string;
}

interface ScanFinding {
  file: string;
  label: string;
  severity: string;
  line: number;
}

interface UploadResult {
  ok: boolean;
  file_count?: number;
  files?: string[];
  findings?: ScanFinding[];
  refused_entries?: { entry: string; reason: string }[];
  needs_review?: boolean;
  note?: string;
  error?: string;
}

const STARTER = `# CodeBox -- apne sandbox mein chalta hai.
# Yahan jo likhoge woh sirf aapki directory mein rahega.

def greet(name):
    return f"Hello, {name}"

print(greet("UK"))
`;

export default function CodeBoxScreen() {
  const [code, setCode] = useState(STARTER);
  const [filename, setFilename] = useState('main.py');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [workdir, setWorkdir] = useState<string>('');
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [task, setTask] = useState('');
  const [taskRunning, setTaskRunning] = useState(false);
  const [taskResult, setTaskResult] = useState<any>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refreshFiles = useCallback(async () => {
    try {
      const res = await api.codeboxFiles();
      setFiles(res?.files ?? []);
      setWorkdir(res?.workdir ?? '');
      setReadinessError(null);
    } catch (err: any) {
      // SURFACE THIS (fixed 2026-09-15). This used to swallow the
      // error entirely and just show an empty file panel -- reasoned
      // at the time as "honest, no fabricated entries", but an empty
      // panel and a genuinely-broken connection look IDENTICAL to a
      // person looking at the screen. If the organism isn't reachable
      // (503, "Organism abhi ready nahi hai") or the request 401s,
      // that is exactly why the Build button then silently does
      // nothing -- and there was no way to tell that from a screenshot.
      setFiles([]);
      setReadinessError(err?.message ?? 'CodeBox backend se connect nahi ho paya.');
    }
  }, []);

  useEffect(() => { refreshFiles(); }, [refreshFiles]);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await api.codeboxRun({ code, filename });
      setResult(res);
      setWorkdir(res?.workdir ?? workdir);
      setFiles(res?.files ?? files);
    } catch (err: any) {
      setResult({ ok: false, error: err?.message ?? 'Run fail hua.' });
    } finally {
      setRunning(false);
    }
  };

  const handleUpload = async (e: import('react').ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUpload(null);
    try {
      const res = await api.uploadFile(file);
      setUpload(res);
      await refreshFiles();
    } catch (err: any) {
      setUpload({ ok: false, error: err?.message ?? 'Upload fail hua.' });
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const handleTask = async () => {
    if (!task.trim()) return;
    setTaskRunning(true);
    setTaskResult(null);
    try {
      const res = await api.codeboxTask({ task, max_steps: 4 });
      setTaskResult(res);
      setReadinessError(null);
      await refreshFiles();
    } catch (err: any) {
      const message = err?.message ?? 'Task fail hua.';
      setTaskResult({ error: message });
      // Same failure class as refreshFiles() -- if this is a 503/401,
      // it is worth showing as the persistent banner too, not just a
      // one-line result under the button that scrolls away.
      setReadinessError(message);
    } finally {
      setTaskRunning(false);
    }
  };

  const highSeverity = (upload?.findings ?? []).filter((f) => f.severity === 'high');

  return (
    <div className="flex h-full flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
            <FileCode className="h-5 w-5 text-indigo-400" />
            CodeBox
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">
            {workdir ? `Sandbox: ${workdir}` : 'Apna isolated sandbox'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            onChange={handleUpload}
            className="hidden"
            /* No accept filter. This list silently blocked mp3, pdf,
               images and anything else UK wanted to attach -- the file
               picker would not even offer them, so the button looked
               broken. What is SAFE is decided server-side in
               upload_guard.py, which is the only place that can
               actually inspect the bytes. */
          />
          <button
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-1.5 text-sm text-slate-200 transition hover:border-indigo-500/60 disabled:opacity-50"
          >
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Attach file / archive
          </button>
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run
          </button>
        </div>
      </header>

      {readinessError && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-100">
          <p className="font-medium">CodeBox abhi kaam nahi kar raha:</p>
          <p className="mt-1 opacity-90">{readinessError}</p>
          <p className="mt-1 opacity-60">
            Agar yeh "Organism abhi ready nahi hai" bol raha hai, CLI mein JARVIS chal raha hai check karo.
          </p>
        </div>
      )}

      {/* Upload outcome -- shown in full, including what was refused. */}
      {upload && (
        <div
          className={`rounded-xl border p-3 text-sm ${
            !upload.ok
              ? 'border-red-500/40 bg-red-500/5 text-red-200'
              : upload.needs_review
              ? 'border-amber-500/40 bg-amber-500/5 text-amber-100'
              : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
          }`}
        >
          <div className="flex items-start gap-2">
            {!upload.ok ? (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            ) : upload.needs_review ? (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <p>{upload.note ?? upload.error}</p>

              {highSeverity.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs">
                  {highSeverity.map((f, i) => (
                    <li key={i} className="font-mono">
                      {f.file}:{f.line} — {f.label}
                    </li>
                  ))}
                </ul>
              )}

              {(upload.refused_entries?.length ?? 0) > 0 && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer opacity-80">
                    {upload.refused_entries!.length} entry refuse hui
                  </summary>
                  <ul className="mt-1 space-y-0.5 font-mono opacity-80">
                    {upload.refused_entries!.map((r, i) => (
                      <li key={i}>{r.entry} — {r.reason}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_380px]">
        {/* Editor */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
          <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-2">
            <input
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              className="w-48 rounded bg-slate-800/70 px-2 py-1 font-mono text-xs text-slate-200 outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <span className="text-xs text-slate-500">{code.split('\n').length} lines</span>
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            spellCheck={false}
            className="min-h-[240px] flex-1 resize-none bg-transparent p-3 font-mono text-sm leading-relaxed text-slate-200 outline-none"
          />
        </div>

        {/* Right rail: files + JARVIS task */}
        <div className="flex min-h-0 flex-col gap-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
            <h2 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              <FolderOpen className="h-3.5 w-3.5" /> Sandbox files
            </h2>
            {files.length === 0 ? (
              <p className="mt-2 text-xs text-slate-500">Abhi koi file nahi.</p>
            ) : (
              <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto">
                {files.map((f) => (
                  <li key={f} className="truncate font-mono text-xs text-slate-300">{f}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
            <h2 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              <Sparkles className="h-3.5 w-3.5" /> JARVIS se likhwao
            </h2>
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Kya banana hai? JARVIS likhega, chalayega, error aaye toh khud theek karega."
              className="mt-2 h-20 w-full resize-none rounded-lg bg-slate-800/60 p-2 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:ring-1 focus:ring-indigo-500"
            />
            <button
              onClick={handleTask}
              disabled={taskRunning || !task.trim()}
              className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-200 transition hover:bg-indigo-500/20 disabled:opacity-40"
            >
              {taskRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {taskRunning ? 'Kaam chal raha hai...' : 'Build karo'}
            </button>

            {taskResult && (
              <div className="mt-2 rounded-lg bg-slate-800/50 p-2 text-xs">
                {taskResult.error ? (
                  <p className="text-red-300">{taskResult.error}</p>
                ) : (
                  <>
                    <p className={taskResult.solved ? 'text-emerald-300' : 'text-amber-300'}>
                      {taskResult.solved ? 'Kaam ho gaya' : 'Poora nahi hua'}
                      {typeof taskResult.attempts === 'number' && ` — ${taskResult.attempts} attempt`}
                    </p>
                    {taskResult.summary && (
                      <p className="mt-1 whitespace-pre-wrap text-slate-300">{taskResult.summary}</p>
                    )}
                    {taskResult.blocked_reason && (
                      <p className="mt-1 text-amber-300/80">Kyun ruka: {taskResult.blocked_reason}</p>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Terminal */}
      <div className="flex max-h-64 min-h-[120px] flex-col overflow-hidden rounded-xl border border-slate-800 bg-black/50">
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
          <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
            <TerminalIcon className="h-3.5 w-3.5" /> Output
          </span>
          {result && (
            <span className="flex items-center gap-2 text-xs text-slate-500">
              {typeof result.duration_ms === 'number' && `${Math.round(result.duration_ms)}ms`}
              <button onClick={() => setResult(null)} className="hover:text-slate-300">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed">
          {!result ? (
            <p className="text-slate-600">Run dabao — output yahan aayega.</p>
          ) : (
            <>
              {result.output && (
                <pre className={`whitespace-pre-wrap ${result.ok ? 'text-slate-200' : 'text-red-300'}`}>
                  {result.output}
                </pre>
              )}
              {result.error && <pre className="whitespace-pre-wrap text-red-300">{result.error}</pre>}
              {!result.output && !result.error && (
                <p className="text-slate-500">
                  (koi output nahi{typeof result.exit_code === 'number' ? ` — exit ${result.exit_code}` : ''})
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
