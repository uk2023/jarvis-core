import React, { useEffect, useState } from 'react';
import { FileSearch, RefreshCw, ChevronDown, Radio, Users } from 'lucide-react';
import { TurnTrace, ActivityHistoryItem, AppTheme } from '../types';
import { api } from '../api/client';
import { TraceTreeViewer } from './TraceTreeViewer';

interface TraceInspectorScreenProps {
  selectedTurnId?: string | null;
  onSelectTurnId?: (id: string) => void;
  theme: AppTheme;
  /** Role of whoever is signed in. Decides which scopes are offered
   *  here; the SERVER decides what is actually returned. */
  viewerRole?: string;
}

export function TraceInspectorScreen({ selectedTurnId, onSelectTurnId, theme, viewerRole = 'guest' }: TraceInspectorScreenProps) {
  // WHO-FILTER (added 2026-09-14). The trace tree below is unchanged --
  // this is the one thing UK asked for: a filter on top of the view he
  // already uses, not a replacement for it.
  //
  // Scope only changes WHICH turns are listed. It cannot widen access:
  // /api/trace applies the role rules server-side, so asking for 'all'
  // as a normal user still returns that user's turns.
  // FILTER, REDESIGNED (2026-09-16, UK's spec). The previous version
  // had 'mine'/'all'/'user'/'role' in one box plus a second free-form
  // box -- confusing, and 'mine' duplicated what the role default
  // already gives you. Now it is two dependent dropdowns, which is what
  // he asked for:
  //
  //   BOX 1 (role):  All | Guest | User | Admin | Owner
  //   BOX 2 (who):   populated from BOX 1 -- the actual people who have
  //                  been active in that role. Guests are listed by
  //                  session id, since a guest has no username and each
  //                  guest session is its own identity.
  //
  // Default is the SIGNED-IN VIEWER'S OWN ROLE: an admin opens this and
  // sees admin turns first, an owner sees owner turns first. Nobody has
  // to pick anything to see something relevant.
  const [roleFilter, setRoleFilter] = useState<string>(() =>
    ['owner', 'co_owner', 'admin', 'user', 'guest'].includes(viewerRole) ? viewerRole : 'all'
  );
  const [whoFilter, setWhoFilter] = useState<string>('');
  const [scopedTurns, setScopedTurns] = useState<any[] | null>(null);
  const [scopeNote, setScopeNote] = useState<string | null>(null);

  const canSeeOthers = viewerRole === 'owner' || viewerRole === 'co_owner' || viewerRole === 'admin';
  const [whoOpen, setWhoOpen] = useState(false);

  // Who has actually been active, with their role AND session id. The
  // session id matters for guests specifically: a guest has no
  // username, and each guest session is a separate identity that resets
  // -- so the session id is the only stable handle for "this guest".
  const [activeUsers, setActiveUsers] = useState<{ username: string; role: string; session_id?: string }[]>([]);
  const ROLE_OPTIONS = ['owner', 'co_owner', 'admin', 'user', 'guest'];

  useEffect(() => {
    if (!canSeeOthers) return;
    api.getActiveTraceUsers()
      .then(res => setActiveUsers((res?.users ?? []).map((u: any) => ({
        username: u.username, role: u.role, session_id: u.session_id,
      }))))
      .catch(() => setActiveUsers([]));
  }, [canSeeOthers, whoOpen]);
  const [history, setHistory] = useState<ActivityHistoryItem[]>([]);
  const [activeTurnId, setActiveTurnId] = useState(selectedTurnId || '');
  const [currentTrace, setCurrentTrace] = useState<TurnTrace | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [historyLimit, setHistoryLimit] = useState(5);

  useEffect(() => {
    if (selectedTurnId && selectedTurnId !== activeTurnId) setActiveTurnId(selectedTurnId);
  }, [selectedTurnId]);

  useEffect(() => { loadTurns(); }, [activeTurnId]);

  // Fetch the identity-tagged list for the current role/who selection.
  // Always runs -- there is no "mine" special case any more; the role
  // default already scopes it to the viewer, and the server enforces
  // what they may actually see regardless of what is asked for.
  useEffect(() => {
    let cancelled = false;
    const params: any = { limit: 60 };

    if (roleFilter === 'all') {
      params.scope = 'all';
    } else {
      params.scope = 'role';
      params.role = roleFilter;
    }

    // Narrowing to one specific person inside that role. Guests are
    // identified by session id (they have no username); everyone else
    // by username.
    if (whoFilter) {
      if (roleFilter === 'guest') {
        params.scope = 'session';
        params.session_id = whoFilter;
      } else {
        params.scope = 'user';
        params.username = whoFilter;
      }
    }

    api.getTraces(params)
      .then(res => {
        if (cancelled) return;
        if (!res?.allowed) { setScopedTurns([]); setScopeNote(res?.reason ?? null); return; }
        setScopedTurns(res.entries ?? []);
        setScopeNote(res.note ?? null);
      })
      .catch(err => { if (!cancelled) { setScopedTurns([]); setScopeNote(err?.message ?? null); } });
    return () => { cancelled = true; };
  }, [roleFilter, whoFilter]);

  const loadTurns = async () => {
    setIsLoading(true);
    try {
      const hist = await api.getActivityHistory();
      setHistory(hist);
      const target = activeTurnId || hist[0]?.turnId;
      if (target) {
        if (!activeTurnId) setActiveTurnId(target);
        setCurrentTrace(await api.getTurnTrace(target));
      } else setCurrentTrace(null);
    } catch (err) {
      console.error('Error fetching turn trace:', err);
      setCurrentTrace(null);
    } finally {
      setIsLoading(false);
    }
  };

  const visibleHistory = [...history].sort((a, b) => b.startTime - a.startTime).slice(0, historyLimit);

  useEffect(() => {
    if (activeTurnId && !visibleHistory.some(item => item.turnId === activeTurnId)) {
      const fallback = visibleHistory[0]?.turnId;
      if (fallback) selectTurn(fallback);
    }
  }, [historyLimit, history, activeTurnId, onSelectTurnId]);

  const selectTurn = (id: string) => {
    setActiveTurnId(id);
    onSelectTurnId?.(id);
  };

  return (
    <div className="trace-inspector-page h-full overflow-y-auto overflow-x-hidden font-mono text-xs max-w-full p-3 sm:p-5">
      <header
        className="trace-inspector-bar"
        style={{ position: 'static', top: 'auto', bottom: 'auto', inset: 'auto', zIndex: 'auto' }}
      >
        <div className="trace-inspector-brand">
          <div className="trace-inspector-icon trace-inspector-icon-live"><FileSearch size={19} /><span className="trace-inspector-pulse" /></div>
          <div className="trace-inspector-heading">
            <div className="trace-inspector-eyebrow"><Radio size={10} /> JARVIS / OBSERVABILITY</div>
            <h1>Cognitive Trace</h1>
            <p>Per-turn execution monitor</p>
          </div>
        </div>

        <div className="trace-inspector-controls">
          <label className="trace-select-wrap trace-turn-select">
            <span>TURN</span>
            <select value={activeTurnId} onChange={e => selectTurn(e.target.value)} disabled={!history.length}>
              {visibleHistory.length ? visibleHistory.map(item => (
                <option key={item.turnId} value={item.turnId}>{item.turnId} — {item.query.slice(0, 38)}</option>
              )) : <option value="">No recorded turns</option>}
            </select>
            <ChevronDown size={14} />
          </label>
          <label className="trace-turn-window">
            <span>SHOW</span>
            <select value={historyLimit} onChange={e => setHistoryLimit(Number(e.target.value))}>
              {[5, 10, 30, 50].map(limit => <option key={limit} value={limit}>LAST {limit} TURNS</option>)}
            </select>
            <ChevronDown size={12} />
          </label>
          <button className="trace-action-btn trace-refresh" onClick={loadTurns} disabled={isLoading} title="Reload trace" aria-label="Reload trace">
            <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </header>

      {/* WHO filter -- SAME header-box style as the trace tree above
          (.trace-inspector-bar / -icon / -heading), collapsible, so it
          reads as part of the same instrument rather than a separate
          bolted-on control strip. */}
      <header
        className="trace-inspector-bar trace-who-bar"
        style={{ position: 'static', top: 'auto', bottom: 'auto', inset: 'auto', zIndex: 'auto' }}
      >
        <button
          type="button"
          className="trace-inspector-brand trace-who-brand-btn"
          onClick={() => setWhoOpen(o => !o)}
          aria-expanded={whoOpen}
        >
          <div className="trace-inspector-icon">
            <Users size={17} />
          </div>
          <div className="trace-inspector-heading">
            <div className="trace-inspector-eyebrow"><Radio size={10} /> JARVIS / IDENTITY</div>
            <h1>Session Filter</h1>
            <p>
              {scopedTurns === null
                ? `${viewerRole} view`
                : `${scopedTurns.length} turns -- ${roleFilter}${whoFilter ? ` / ${whoFilter}` : ''}`}
            </p>
          </div>
          <ChevronDown
            size={16}
            style={{
              marginLeft: 4,
              transition: 'transform .18s',
              transform: whoOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              color: 'var(--jarvis-text-muted)',
            }}
          />
        </button>

        {whoOpen && (
          <div className="trace-inspector-controls trace-who-controls">
            {/* BOX 1: role. Defaults to the viewer's own role, so an
                admin sees admin turns without picking anything. */}
            <label className="trace-select-wrap trace-turn-select">
              <span>ROLE</span>
              <select
                value={roleFilter}
                onChange={e => { setRoleFilter(e.target.value); setWhoFilter(''); }}
              >
                {canSeeOthers && <option value="all">All</option>}
                {ROLE_OPTIONS.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <ChevronDown size={14} />
            </label>

            {/* BOX 2: who, inside that role. Populated from who has
                actually been active -- never typed by hand. Guests are
                listed by session id because that is their only stable
                identity. */}
            {roleFilter !== 'all' && (
              <label className="trace-select-wrap trace-turn-select">
                <span>{roleFilter === 'guest' ? 'SESSION' : 'WHO'}</span>
                <select value={whoFilter} onChange={e => setWhoFilter(e.target.value)}>
                  <option value="">
                    All {roleFilter}{roleFilter === 'guest' ? ' sessions' : 's'}
                  </option>
                  {activeUsers
                    .filter(u => u.role === roleFilter)
                    .map((u, i) => {
                      const value = roleFilter === 'guest' ? (u.session_id || '') : (u.username || '');
                      const label = roleFilter === 'guest'
                        ? `session ${String(u.session_id || '').slice(0, 10)}`
                        : u.username;
                      return <option key={`${value}-${i}`} value={value}>{label}</option>;
                    })}
                </select>
                <ChevronDown size={14} />
              </label>
            )}

            <button
              className="trace-action-btn trace-refresh"
              onClick={() => setWhoFilter(w => w)}
              title="Refresh"
              aria-label="Refresh"
            >
              <RefreshCw size={15} />
            </button>
          </div>
        )}
      </header>

      {scopeNote && <div className="trace-who-note">{scopeNote}</div>}

      {/* TRANSACTION TABLE. Every row now shows its REQUEST ID -- the
          transaction number UK needs to identify a specific turn -- and
          clicking a row loads THAT turn into the trace tree below.
          Previously the id was not rendered at all, so the tree always
          showed only the most recent turn no matter what was clicked. */}
      {scopedTurns !== null && scopedTurns.length > 0 && whoOpen && (
        <div className="trace-who-list">
          {scopedTurns.map((entry: any) => (
            <button
              key={entry.request_id}
              className={`trace-who-row ${activeTurnId === entry.request_id ? 'is-active' : ''}`}
              onClick={() => entry.request_id && selectTurn(entry.request_id)}
            >
              <span className="trace-who-txn" title={entry.request_id}>
                {String(entry.request_id || '').replace(/^req_/, '').slice(0, 10)}
              </span>
              <span className="trace-who-user">{entry.username || 'guest'}</span>
              <span className="trace-who-role">{entry.role}</span>
              <span className="trace-who-text">{(entry.user_input || '').slice(0, 40)}</span>
              <span className="trace-who-time">{entry.timestamp}</span>
            </button>
          ))}
        </div>
      )}

      {scopedTurns !== null && scopedTurns.length === 0 && whoOpen && (
        <div className="trace-who-note">
          Is filter mein koi turn nahi mila.
        </div>
      )}


      <main className="trace-inspector-main" style={{ width: '100%', minWidth: 0, margin: 0, padding: 0 }}>
        <style>{`
          .trace-inspector-page .trace-root { width:100%; max-width:100%; margin:0 auto; }
          .trace-inspector-page .trace-hero { padding:16px 16px 14px; }
          .trace-inspector-page .trace-hero-title { margin-top:12px; }
          .trace-inspector-page .trace-overview { margin-top:12px; gap:6px; }
          .trace-inspector-page .trace-metric { padding:8px 9px; }
          .trace-inspector-page .trace-flow { padding:14px 14px 16px; }
          .trace-inspector-page .trace-stage { margin-bottom:9px; border-radius:13px; }
          .trace-inspector-page .trace-stage-head { gap:7px; padding:9px 10px; }
          .trace-inspector-page .trace-stage-content { padding:10px; }
          .trace-inspector-page .trace-field { padding:8px 9px; }
          .trace-inspector-page .trace-flow-label { margin-bottom:9px; }
          .trace-inspector-page .trace-inspector-bar { position:static!important; top:auto!important; bottom:auto!important; inset:auto!important; z-index:auto!important; }
        `}</style>
        {currentTrace ? (
          <TraceTreeViewer trace={currentTrace} theme={theme} initiallyExpanded={true} />
        ) : (
          <div className="trace-empty">
            <FileSearch size={26} />
            <strong>{isLoading ? 'LOADING COGNITIVE TRACE' : 'NO TRACE RECORDED'}</strong>
            <span>{isLoading ? 'Fetching the latest workflow from JARVIS…' : 'Start a conversation to capture a per-turn trace.'}</span>
          </div>
        )}
      </main>
    </div>
  );
}
