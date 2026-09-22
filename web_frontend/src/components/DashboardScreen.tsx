import React, { useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Cpu, ExternalLink, Maximize2, RefreshCw, Terminal, X } from 'lucide-react';
import { LiveStateResponse, SystemResourcesData, ActivityHistoryItem, AppTheme } from '../types';
import { api } from '../api/client';
import { OrganIntrospectionViewer } from './OrganIntrospectionViewer';
import { OvernightLearningCard } from './OvernightLearningCard';
import { SelfImprovementList } from './SelfImprovementList';
import { MemoryDBPipeline } from './MemoryDBPipeline';
import { TabHeader } from './TabHeader';
import { CognitivePipelineCard } from './CognitivePipelineCard';
import { CognitiveMonitoringCards } from './CognitiveMonitoringCards';
import '../styles/dashboard-tables.css';

interface DashboardScreenProps {
  onSelectTurn: (turnId: string) => void;
  onNavigateToCLI: () => void;
  theme: AppTheme;
  activeSection?: 'monitor' | 'memory' | 'reasoning' | 'organs' | 'all';
  onSelectSection?: (section: 'monitor' | 'memory' | 'reasoning' | 'organs' | 'all') => void;
}

const formatTime = (timestamp: number) => {
  if (!timestamp) return '—';
  const value = timestamp > 1e12 ? timestamp : timestamp * 1000;
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export function DashboardScreen({ onSelectTurn, theme, activeSection = 'monitor' }: DashboardScreenProps) {
  const [liveState, setLiveState] = useState<LiveStateResponse | null>(null);
  const [resources, setResources] = useState<SystemResourcesData | null>(null);
  const [history, setHistory] = useState<ActivityHistoryItem[]>([]);
  const [pollIntervalMs, setPollIntervalMs] = useState(2000);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSyncAnimating, setIsSyncAnimating] = useState(false);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [currentSection, setCurrentSection] = useState<'monitor' | 'memory' | 'reasoning' | 'organs' | 'all'>(activeSection);
  const [expandedTable, setExpandedTable] = useState<'activity' | 'logs' | null>(null);
  const isDark = theme === 'dark';

  useEffect(() => setCurrentSection(activeSection), [activeSection]);

  const fetchDashboardData = async () => {
    const animationDuration = Math.max(800, pollIntervalMs || 2000);
    setIsSyncAnimating(true);
    window.setTimeout(() => setIsSyncAnimating(false), animationDuration);
    try {
      setIsRefreshing(true);
      const [stateRes, resRes, histRes] = await Promise.all([api.getLiveState(), api.getResources(), api.getActivityHistory()]);
      setLiveState(stateRes);
      setResources(resRes);
      setHistory(histRes);
    } catch (err) {
      console.error('Failed to load dashboard metrics:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = pollIntervalMs > 0 ? setInterval(fetchDashboardData, pollIntervalMs) : null;
    return () => { if (interval) clearInterval(interval); };
  }, [pollIntervalMs]);

  const showMonitor = currentSection === 'monitor' || currentSection === 'all';
  const showMemory = currentSection === 'memory' || currentSection === 'all';
  const showReasoning = currentSection === 'reasoning' || currentSection === 'all';
  const showOrgans = currentSection === 'organs' || currentSection === 'all';

  const headerControls = <>
    <span className="trace-tab-control" title={`Process ID: ${liveState?.pid || '—'}`} aria-label={`Process ID ${liveState?.pid || 'unknown'}`}><Cpu size={11} />{liveState?.pid || '—'}</span>
    <select value={pollIntervalMs} onChange={e => setPollIntervalMs(Number(e.target.value))} className="trace-tab-control cursor-pointer outline-none">
      <option value={1000}>POLL: 1s</option><option value={2000}>POLL: 2s</option><option value={5000}>POLL: 5s</option><option value={0}>POLL: PAUSED</option>
    </select>
    <button onClick={fetchDashboardData} disabled={isRefreshing} className={`trace-action-btn dashboard-sync-button flex items-center justify-center p-2 ${isSyncAnimating ? 'is-syncing' : ''}`} style={{ '--sync-duration': `${Math.max(800, pollIntervalMs || 2000)}ms` } as React.CSSProperties} title="Sync now" aria-label="Sync now"><RefreshCw className="h-3.5 w-3.5" /></button>
  </>;

  const expandButton = (table: 'activity' | 'logs') => <button onClick={() => setExpandedTable(table)} className={`p-1.5 border rounded-md flex items-center justify-center text-[8px] font-bold shrink-0 ${isDark ? 'bg-white/5 hover:bg-white/10 border-white/10 text-[#8eb3ff]' : 'bg-slate-50 hover:bg-slate-100 border-slate-200 text-[#315fbe]'}`} title="Expand table" aria-label="Expand table"><Maximize2 className="w-3 h-3" /></button>;

  const tableGrid = 'grid-cols-[60px_68px_minmax(0,1fr)]';

  const normalizedLogs = useMemo(() => {
    const severityRank: Record<string, number> = { debug: 0, info: 1, warning: 2, warn: 2, error: 3 };
    const merged = new Map<string, { level: string; message: string; timestamp: number }>();
    for (const log of liveState?.logs ?? []) {
      const level = typeof log === 'object' && log !== null && 'level' in log ? String((log as { level?: string }).level || 'info').toLowerCase() : 'info';
      const message = typeof log === 'string' ? log : typeof log === 'object' && log !== null && 'message' in log ? String((log as { message?: unknown }).message ?? '') : String(log);
      const timestamp = typeof log === 'object' && log !== null && 'timestamp' in log ? Number((log as { timestamp?: number }).timestamp || 0) : 0;
      const key = `${timestamp}|${message.trim()}`;
      const existing = merged.get(key);
      if (!existing || (severityRank[level] ?? 1) > (severityRank[existing.level] ?? 1)) merged.set(key, { level, message, timestamp });
    }
    return Array.from(merged.values()).slice(-5);
  }, [liveState?.logs]);

  const activityTable = (expanded = false) => {
    const rows = history.slice(-5);
    return <div className={`dashboard-table-surface border rounded-lg overflow-hidden w-full ${expanded ? 'min-w-0' : ''}`}>
      <div className={`grid ${tableGrid} gap-0 border-b dashboard-table-header text-[7px] uppercase tracking-[.14em]`}>
        <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5">TIME</span>
        <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5">TRXN</span>
        <span className="dashboard-table-fixed-cell dashboard-table-center px-1.5">Content</span>
      </div>
      <div className="dashboard-table-body">
        {rows.length === 0 ? <div className="px-2.5 py-3 dashboard-table-muted text-[9px]">No activity history available.</div> : rows.map(item => {
          const selected = selectedTurnId === item.turnId;
          return <div key={item.turnId} onClick={() => { setSelectedTurnId(item.turnId); onSelectTurn(item.turnId); }} className={`group relative grid ${tableGrid} items-center gap-0 cursor-pointer border-b last:border-0 dashboard-table-row text-[8px] transition-all ${selected ? (isDark ? 'bg-[#5b8def]/12' : 'bg-[#5b8def]/[.08]') : ''}`}>
            <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5 tabular-nums dashboard-table-muted">{formatTime(item.startTime)}</span>
            <span className="dashboard-table-fixed-cell dashboard-table-center min-w-0 truncate border-r dashboard-table-cell-divider px-1.5 font-bold text-[#5b8def]" title={item.turnId}>{item.turnId}</span>
            <span className="dashboard-table-message px-2" title={item.query}>{item.query || '—'}</span>
            {selected && <span className="absolute left-0 top-0 bottom-0 w-[2px] bg-[#5b8def]" />}
            <button onClick={e => { e.stopPropagation(); setSelectedTurnId(item.turnId); onSelectTurn(item.turnId); }} className={`absolute right-1.5 p-1 rounded ${isDark ? 'bg-black/30' : 'bg-white'} opacity-0 group-hover:opacity-100 text-[#5b8def] transition`} title="Inspect transaction" aria-label="Inspect transaction"><ExternalLink className="w-2.5 h-2.5" /></button>
          </div>;
        })}
      </div>
    </div>;
  };

  const logsTable = (expanded = false) => <div className={`dashboard-table-surface border rounded-lg overflow-hidden w-full ${expanded ? 'min-w-0' : ''}`}>
    <div className={`grid ${tableGrid} gap-0 border-b dashboard-table-header text-[7px] uppercase tracking-[.14em]`}>
      <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5">TIME</span>
      <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5">Level</span>
      <span className="dashboard-table-fixed-cell dashboard-table-center px-1.5">Diagnostic Message</span>
    </div>
    <div className="dashboard-table-body">
      {normalizedLogs.length === 0 ? <div className="px-2.5 py-3 dashboard-table-muted text-[9px]">No diagnostic logs available.</div> : normalizedLogs.map((log, index) => {
        const warning = log.level === 'warning' || log.level === 'warn';
        const error = log.level === 'error';
        return <div key={`${log.timestamp}-${index}`} className={`grid ${tableGrid} items-center gap-0 border-b last:border-0 dashboard-table-row text-[8px] ${error ? 'text-rose-500' : warning ? 'text-amber-500' : 'text-[var(--jarvis-text)]'}`}>
          <span className="dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5 tabular-nums dashboard-table-muted">{formatTime(log.timestamp)}</span>
          <span className={`dashboard-table-fixed-cell dashboard-table-center border-r dashboard-table-cell-divider px-1.5 font-bold uppercase ${error ? 'text-rose-500' : warning ? 'text-amber-500' : 'text-[#5b8def]'}`}>{log.level}</span>
          <span className="dashboard-table-message px-2">{log.message}</span>
        </div>;
      })}
    </div>
  </div>;

  return <div className={`h-full overflow-y-auto overflow-x-hidden p-3 sm:p-5 space-y-3 font-mono text-xs max-w-full ${isDark ? 'trace-dark' : 'trace-light'}`}>
    {showMonitor && <>
      <TabHeader icon={Activity} category="JARVIS / OBSERVABILITY" title="COGNITIVE MONITOR" subtitle="Live organism runtime monitor" controls={headerControls} />
      <CognitivePipelineCard liveState={liveState} theme={theme} />
      <CognitiveMonitoringCards liveState={liveState} resources={resources} theme={theme} />
      <section id="card-activity-history" className="trace-root dashboard-observability-card overflow-hidden"><div className="px-3 py-2.5 sm:px-4"><div className="flex items-center justify-between gap-3 mb-2"><div className="flex items-center gap-2 min-w-0"><BarChart3 className="w-3.5 h-3.5 text-[#5b8def] shrink-0" /><div className="min-w-0"><h2 className="font-bold text-[9px] uppercase tracking-wider truncate">Recent Activity History</h2><div className="text-[7px] dashboard-table-muted truncate">Transaction stream · select a row to inspect</div></div></div><div className="flex items-center gap-2 shrink-0">{expandButton('activity')}</div></div>{activityTable()}</div></section>
      <section id="card-internal-logs" className="trace-root dashboard-observability-card overflow-hidden"><div className="px-3 py-2.5 sm:px-4"><div className="flex items-center justify-between gap-3 mb-2"><div className="flex items-center gap-2 min-w-0"><Terminal className="w-3.5 h-3.5 text-[#5b8def] shrink-0" /><div className="min-w-0"><h2 className="font-bold text-[9px] uppercase tracking-wider truncate">Internal Diagnostic Logs</h2><div className="text-[7px] dashboard-table-muted truncate">Runtime diagnostics · warnings and errors surfaced inline</div></div></div>{expandButton('logs')}</div>{logsTable()}</div></section>
    </>}
    {showMemory && <MemoryDBPipeline liveState={liveState} resources={resources} theme={theme} />}
    {showReasoning && <><OvernightLearningCard theme={theme} /><SelfImprovementList theme={theme} /></>}
    {showOrgans && <OrganIntrospectionViewer theme={theme} />}
    {expandedTable && <div className="fixed inset-0 z-[100] bg-black/70 backdrop-blur-sm p-2 sm:p-5 flex items-center justify-center"><div className={`w-full h-full max-w-[1500px] flex flex-col rounded-xl border shadow-2xl overflow-hidden ${isDark ? 'bg-[#0f141d] border-[#293446] text-[#edf3fb]' : 'bg-white border-slate-200 text-slate-900'}`}><div className={`flex items-center justify-between gap-3 px-3 sm:px-5 py-3 border-b ${isDark ? 'border-[#293446] bg-[#151c27]' : 'border-slate-200 bg-slate-50'} shrink-0`}><div><h2 className="font-black text-[10px] sm:text-xs uppercase tracking-[.14em]">{expandedTable === 'activity' ? 'Recent Activity History' : 'Internal Diagnostic Logs'}</h2><p className={`mt-1 text-[8px] ${isDark ? 'text-[#9aa8ba]' : 'text-slate-500'}`}>Full-window diagnostic table · spreadsheet view</p></div><button onClick={() => setExpandedTable(null)} className={`p-2 rounded-lg border ${isDark ? 'border-[#293446] bg-white/[.04]' : 'border-slate-200 bg-white'} hover:opacity-80`} title="Close" aria-label="Close"><X className="w-4 h-4" /></button></div><div className="flex-1 overflow-hidden p-3 sm:p-5">{expandedTable === 'activity' ? activityTable(true) : logsTable(true)}</div></div></div>}
  </div>;
}
