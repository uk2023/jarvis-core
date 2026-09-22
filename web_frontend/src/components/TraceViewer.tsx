import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Loader2, ShieldOff, Users, Filter, EyeOff } from 'lucide-react';
import { api } from '../api/client';

/**
 * TRACE VIEWER -- scoped to whoever is signed in.
 *
 * UK's report: on the new role routes (/owner/<id>, /admin/<id>, ...)
 * no trace fetched at all, and only the bare localhost:5173 root showed
 * anything.
 *
 * The cause was not the routes. The old inspector called
 * getActivityHistory()/getTurnTrace(), which read a single GLOBAL "last
 * turn" off the brain object. With several people connected that is one
 * shared value: everyone saw the same turn, nothing was attributed, and
 * nothing could be filtered by role -- so on a role route there was
 * simply nothing role-aware to show.
 *
 * This calls /api/trace instead, which applies the permission rules
 * server-side (core/runtime/identity_trace.py):
 *
 *     owner / co-owner  -- everyone, full content
 *     admin             -- own turns full; normal users' OPERATIONAL
 *                          only (content redacted); owner's not at all
 *     user              -- own turns only
 *     guest             -- no trace viewer
 *
 * The filters below are a convenience. They cannot widen access: asking
 * for scope=all as a normal user still returns only that user's rows,
 * because the server decides, not this component.
 */

type Scope = 'mine' | 'all' | 'user' | 'role' | 'session' | 'request';

interface TraceEntry {
  request_id: string;
  timestamp: string;
  username: string;
  role: string;
  channel: string;
  session_id?: string | null;
  duration_ms?: number | null;
  user_input?: string;
  response?: string;
  ip?: string;
}

export default function TraceViewer({
  viewerRole,
  isDark = true,
}: {
  viewerRole: string;
  isDark?: boolean;
}) {
  const [scope, setScope] = useState<Scope>('mine');
  const [filterValue, setFilterValue] = useState('');
  const [entries, setEntries] = useState<TraceEntry[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeUsers, setActiveUsers] = useState<any[]>([]);

  const canSeeOthers = viewerRole === 'owner' || viewerRole === 'co_owner' || viewerRole === 'admin';
  const isGuest = viewerRole === 'guest' || !viewerRole;

  const load = useCallback(async () => {
    if (isGuest) return;
    setLoading(true);
    setError(null);
    try {
      const params: any = { scope, limit: 40 };
      if (scope === 'user') params.username = filterValue;
      if (scope === 'role') params.role = filterValue;
      if (scope === 'session') params.session_id = filterValue;
      if (scope === 'request') params.request_id = filterValue;

      const res = await api.getTraces(params);
      if (!res?.allowed) {
        setError(res?.reason ?? 'Trace dekhne ki permission nahi hai.');
        setEntries([]);
        return;
      }
      setEntries(res.entries ?? []);
      setNote(res.note ?? null);
    } catch (err: any) {
      setError(err?.message ?? 'Trace fetch fail hua.');
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [scope, filterValue, isGuest]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!canSeeOthers) return;
    api.getActiveTraceUsers()
      .then((r) => setActiveUsers(r?.users ?? []))
      .catch(() => setActiveUsers([]));
  }, [canSeeOthers, entries.length]);

  if (isGuest) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <ShieldOff className="h-8 w-8 text-slate-500" />
        <p className="text-sm text-slate-400">Guest ke liye trace viewer nahi hai.</p>
        <p className="max-w-xs text-xs text-slate-500">
          Chat pura kaam karta hai. Trace dekhne ke liye login karo.
        </p>
      </div>
    );
  }

  const scopes: { key: Scope; label: string; needsValue?: boolean }[] = [
    { key: 'mine', label: 'Mera' },
    ...(canSeeOthers
      ? ([
          { key: 'all' as Scope, label: 'Sab' },
          { key: 'user' as Scope, label: 'User', needsValue: true },
          { key: 'role' as Scope, label: 'Role', needsValue: true },
          { key: 'session' as Scope, label: 'Session', needsValue: true },
        ])
      : []),
    { key: 'request', label: 'Request', needsValue: true },
  ];

  const activeScope = scopes.find((s) => s.key === scope);

  return (
    <div className="flex h-full flex-col gap-3 p-3 md:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {scopes.map((s) => (
            <button
              key={s.key}
              onClick={() => { setScope(s.key); setFilterValue(''); }}
              className={`rounded-lg px-2.5 py-1 text-xs transition ${
                scope === s.key
                  ? 'bg-brand-500/20 text-brand-300'
                  : isDark
                  ? 'text-slate-400 hover:bg-white/5'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {activeScope?.needsValue && (
          <div className="flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-slate-500" />
            <input
              value={filterValue}
              onChange={(e) => setFilterValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
              placeholder={scope === 'role' ? 'owner / admin / user' : scope}
              className={`w-36 rounded-lg px-2 py-1 text-xs outline-none ${
                isDark ? 'bg-white/5 text-slate-200' : 'bg-slate-100 text-slate-800'
              }`}
            />
          </div>
        )}

        <button
          onClick={load}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs text-slate-400 transition hover:text-slate-200"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      {canSeeOthers && activeUsers.length > 0 && (
        <div className={`rounded-xl border p-2.5 ${isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200 bg-slate-50'}`}>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-slate-500">
            <Users className="h-3 w-3" /> Recently active
          </div>
          <div className="flex flex-wrap gap-2">
            {activeUsers.map((u, i) => (
              <button
                key={i}
                onClick={() => { setScope('user'); setFilterValue(u.username); }}
                className="rounded-lg bg-white/5 px-2 py-1 text-[11px] text-slate-300 transition hover:bg-white/10"
              >
                {u.username} <span className="opacity-60">{u.role} · {u.channel} · {u.turns}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs text-amber-200">
          {error}
        </div>
      )}

      {note && (
        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <EyeOff className="h-3 w-3" /> {note}
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {entries.length === 0 && !loading && !error && (
          <p className="pt-6 text-center text-xs text-slate-500">
            Is scope mein koi trace nahi.
          </p>
        )}

        {entries.map((e) => {
          const redacted = (e.user_input ?? '').startsWith('[private');
          return (
            <div
              key={e.request_id}
              className={`rounded-xl border p-2.5 text-xs ${
                isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200 bg-white'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span className="font-medium text-slate-300">{e.username}</span>
                <span className="rounded bg-white/5 px-1.5 py-0.5">{e.role}</span>
                <span>{e.channel}</span>
                <span className="ml-auto font-mono">{e.timestamp}</span>
              </div>

              <div className="mt-1.5 space-y-1">
                <p className={redacted ? 'italic text-slate-500' : isDark ? 'text-slate-300' : 'text-slate-700'}>
                  ▸ {e.user_input}
                </p>
                <p className={redacted ? 'italic text-slate-500' : 'text-brand-300'}>
                  ◂ {e.response}
                </p>
              </div>

              <div className="mt-1.5 flex flex-wrap gap-2 text-[10px] text-slate-600">
                <span className="font-mono">{e.request_id}</span>
                {e.session_id && <span className="font-mono">sess {e.session_id}</span>}
                {typeof e.duration_ms === 'number' && <span>{Math.round(e.duration_ms)}ms</span>}
                {e.ip && <span>{e.ip}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
