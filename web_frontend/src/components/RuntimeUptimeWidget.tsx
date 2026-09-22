import React, { useState, useEffect } from 'react';
import { Clock, History, Calendar, Cpu, Hourglass } from 'lucide-react';
import { RuntimeInfo, AppTheme } from '../types';
import { api } from '../api/client';

interface RuntimeUptimeWidgetProps {
  theme?: AppTheme;
  compact?: boolean;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export const RuntimeUptimeWidget: React.FC<RuntimeUptimeWidgetProps> = ({
  theme = 'dark',
  compact = false,
}) => {
  const isDark = theme === 'dark';
  const [runtime, setRuntime] = useState<RuntimeInfo>({
    session_uptime_seconds: 12240,
    cumulative_runtime_seconds: 142050,
    age_seconds: 1555200,
  });

  useEffect(() => {
    let mounted = true;
    const fetchInfo = async () => {
      const data = await api.getRuntimeInfo();
      if (mounted) setRuntime(data);
    };

    fetchInfo();
    const interval = setInterval(() => {
      setRuntime((prev) => ({
        ...prev,
        session_uptime_seconds: prev.session_uptime_seconds + 1,
        cumulative_runtime_seconds: prev.cumulative_runtime_seconds + 1,
        age_seconds: prev.age_seconds + 1,
      }));
    }, 1000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  if (compact) {
    return (
      <div
        className={`flex items-center gap-2 px-2.5 py-1 rounded-lg border text-xs font-mono select-none ${
          isDark
            ? 'bg-black/40 border-white/10 text-slate-300'
            : 'bg-white border-slate-200 text-slate-700 shadow-xs'
        }`}
        title="Uptime: Process Session / Cumulative All Sessions / Total Age since first boot"
      >
        <span className="flex items-center gap-1 text-brand-400">
          <Hourglass className="w-3 h-3 text-brand-400" />
          <span className="text-slate-400">Up:</span> {formatDuration(runtime.session_uptime_seconds)}
        </span>
        <span className="text-white/20">|</span>
        <span className="text-emerald-400 hidden sm:inline-flex items-center gap-1">
          <span className="text-slate-400">Cumul:</span> {formatDuration(runtime.cumulative_runtime_seconds)}
        </span>
        <span className="text-white/20 hidden sm:inline">|</span>
        <span className="text-indigo-400 hidden md:inline-flex items-center gap-1">
          <span className="text-slate-400">Age:</span> {formatDuration(runtime.age_seconds)}
        </span>
      </div>
    );
  }

  return (
    <div
      id="widget-runtime-uptime"
      className={`p-3.5 rounded-xl border space-y-2.5 font-mono text-xs ${
        isDark ? 'bg-black/30 border-white/10 text-white' : 'bg-slate-50 border-slate-200 text-slate-900'
      }`}
    >
      <div className="flex items-center justify-between border-b border-white/5 pb-1.5 text-xs">
        <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-brand-400">
          <Clock className="w-3.5 h-3.5 text-brand-400" />
          <span>Organism Runtime Triad</span>
        </div>
        <span className="text-slate-400">core/identity/jarvis_identity.py</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        {/* 1. Session Uptime */}
        <div className={`p-2 rounded-lg border ${isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'}`}>
          <div className="text-xs text-slate-400 uppercase">Process Uptime</div>
          <div className="font-bold text-brand-400 text-xs sm:text-sm mt-0.5">
            {formatDuration(runtime.session_uptime_seconds)}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Current run only</div>
        </div>

        {/* 2. Cumulative Runtime */}
        <div className={`p-2 rounded-lg border ${isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'}`}>
          <div className="text-xs text-slate-400 uppercase">Cumulative Uptime</div>
          <div className="font-bold text-emerald-400 text-xs sm:text-sm mt-0.5">
            {formatDuration(runtime.cumulative_runtime_seconds)}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">All sessions persisted</div>
        </div>

        {/* 3. Total Age */}
        <div className={`p-2 rounded-lg border ${isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'}`}>
          <div className="text-xs text-slate-400 uppercase">Organism Age</div>
          <div className="font-bold text-indigo-400 text-xs sm:text-sm mt-0.5">
            {formatDuration(runtime.age_seconds)}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Since genesis boot</div>
        </div>
      </div>
    </div>
  );
};
