import React, { useState, useEffect } from 'react';
import {
  GitPullRequest,
  Plus,
  CheckCircle2,
  Clock,
  FlaskConical,
  UserCheck,
  AlertCircle,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import { ImprovementRequest, AppTheme } from '../types';
import { api } from '../api/client';

interface SelfImprovementListProps {
  theme?: AppTheme;
}

export const SelfImprovementList: React.FC<SelfImprovementListProps> = ({ theme = 'dark' }) => {
  const isDark = theme === 'dark';
  const [requests, setRequests] = useState<ImprovementRequest[]>([]);
  const [newText, setNewText] = useState('');
  const [newScope, setNewScope] = useState<'narrow' | 'broad'>('narrow');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [filter, setFilter] = useState<'all' | 'narrow' | 'broad'>('all');

  const loadRequests = async () => {
    const list = await api.getImprovementRequests();
    setRequests(list);
  };

  useEffect(() => {
    loadRequests();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newText.trim() || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await api.createImprovementRequest(newText.trim(), newScope);
      setNewText('');
      setShowAddForm(false);
      await loadRequests();
    } finally {
      setIsSubmitting(false);
    }
  };

  const filtered = requests.filter((r) => {
    if (filter === 'all') return true;
    return r.scope === filter;
  });

  return (
    <div
      id="self-improvement-list"
      className={`p-4 rounded-xl border space-y-3.5 ${
        isDark ? 'bg-[#080b12] border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900 shadow-sm'
      }`}
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b pb-2.5 border-white/10">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-amber-500/20 text-amber-400 flex items-center justify-center border border-amber-500/30 shrink-0">
            <GitPullRequest className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 className="font-bold text-xs uppercase tracking-wider text-amber-400 truncate">
              Self-Improvement Requests
            </h3>
            <p className="text-xs text-slate-400 font-mono truncate">
              core/learning/improvement_requests.py &bull; Logged Bugs & Features
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="text-xs text-amber-400 hover:text-amber-300 font-semibold flex items-center gap-1 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/30 transition cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{showAddForm ? 'Cancel' : 'Log Request'}</span>
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-400">
        Recorded when operator reports bugs or desired features. Classified as{' '}
        <span className="text-brand-400 font-mono">narrow</span> (JARVIS can sandbox-test itself) or{' '}
        <span className="text-amber-400 font-mono">broad</span> (requires developer intervention).
      </p>

      {/* Add Request Form */}
      {showAddForm && (
        <form
          onSubmit={handleSubmit}
          className={`p-3.5 rounded-xl border space-y-3 ${
            isDark ? 'bg-black/40 border-amber-500/30' : 'bg-amber-50/50 border-amber-200'
          }`}
        >
          <div className="space-y-1">
            <label className="text-xs font-bold uppercase text-slate-300">
              Request Description / Bug Detail
            </label>
            <input
              type="text"
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="e.g., Fix Hinglish number word parsing in timer skill..."
              className={`w-full px-3 py-2 rounded-lg border text-xs font-mono outline-none ${
                isDark ? 'bg-white/5 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900'
              }`}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400 text-xs">Scope:</span>
              <button
                type="button"
                onClick={() => setNewScope('narrow')}
                className={`px-2 py-1 rounded text-xs font-mono border cursor-pointer ${
                  newScope === 'narrow'
                    ? 'bg-brand-500/20 text-brand-300 border-brand-400'
                    : 'text-slate-400 border-transparent hover:border-white/10'
                }`}
              >
                Narrow (Sandbox Auto-testable)
              </button>
              <button
                type="button"
                onClick={() => setNewScope('broad')}
                className={`px-2 py-1 rounded text-xs font-mono border cursor-pointer ${
                  newScope === 'broad'
                    ? 'bg-amber-500/20 text-amber-300 border-amber-400'
                    : 'text-slate-400 border-transparent hover:border-white/10'
                }`}
              >
                Broad (Needs Developer)
              </button>
            </div>

            <button
              type="submit"
              disabled={isSubmitting || !newText.trim()}
              className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-black font-bold text-xs transition cursor-pointer"
            >
              {isSubmitting ? 'Recording...' : 'Save Request'}
            </button>
          </div>
        </form>
      )}

      {/* Filter Tabs */}
      <div className="flex items-center justify-between text-xs font-mono">
        <div className="flex gap-1.5">
          {(['all', 'narrow', 'broad'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setFilter(t)}
              className={`px-2 py-0.5 rounded capitalize transition cursor-pointer ${
                filter === t
                  ? 'bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {t} ({t === 'all' ? requests.length : requests.filter((r) => r.scope === t).length})
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="space-y-2">
        {filtered.map((req) => {
          const dateStr = new Date(req.timestamp).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          });

          const isNarrow = req.scope === 'narrow';
          const statusBadge =
            req.status === 'applied'
              ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
              : req.status === 'sandbox_testing'
              ? 'bg-brand-500/20 text-brand-300 border-brand-500/40'
              : req.status === 'needs_operator'
              ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
              : 'bg-slate-500/20 text-slate-300 border-slate-500/40';

          return (
            <div
              key={req.id}
              className={`p-3 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 font-mono text-xs ${
                isDark ? 'bg-white/[0.02] border-white/5' : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="space-y-1 min-w-0 flex-1">
                <div className={`font-sans font-medium break-words ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
                  {req.request_text}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    <span>{dateStr}</span>
                  </span>
                  {req.evidence && (
                    <span className={`truncate max-w-full sm:max-w-xs ${isDark ? 'text-brand-400/90' : 'text-brand-700 font-semibold'}`}>
                      &bull; {req.evidence}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0 self-start sm:self-center">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-bold border uppercase ${
                    isNarrow
                      ? 'bg-brand-500/10 text-brand-300 border-brand-500/30'
                      : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                  }`}
                >
                  {req.scope}
                </span>

                <span className={`px-2 py-0.5 rounded text-xs font-bold border uppercase ${statusBadge}`}>
                  {req.status.replace('_', ' ')}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
