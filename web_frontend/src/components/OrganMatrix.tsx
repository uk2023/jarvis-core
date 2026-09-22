import React from 'react';
import { motion } from 'motion/react';
import {
  Activity,
  Cpu,
  Database,
  Brain as BrainIcon,
  Shield,
  Layers,
  Sparkles,
  GitBranch,
  Repeat,
  Heart,
  CheckCircle2,
  AlertCircle,
  Radio,
  Terminal,
} from 'lucide-react';
import { OrganStatusInfo, AppTheme } from '../types';

interface OrganMatrixProps {
  organs: OrganStatusInfo[];
  beatCount: number;
  bpm: number;
  onTriggerPulse: () => void;
  theme?: AppTheme;
}

export const OrganMatrix: React.FC<OrganMatrixProps> = ({
  organs,
  beatCount,
  bpm,
  onTriggerPulse,
  theme = 'dark',
}) => {
  const isDark = theme === 'dark';

  const getIconForOrgan = (name: string) => {
    switch (name.toLowerCase()) {
      case 'brain':
        return <BrainIcon className="w-4 h-4 text-brand-500 dark:text-brand-400" />;
      case 'memory':
        return <Database className="w-4 h-4 text-purple-600 dark:text-purple-400" />;
      case 'experience_engine':
        return <Layers className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />;
      case 'self_evaluator':
        return <Shield className="w-4 h-4 text-amber-600 dark:text-yellow-400" />;
      case 'knowledge_builder':
        return <Sparkles className="w-4 h-4 text-pink-600 dark:text-pink-400" />;
      case 'memory_consolidator':
        return <Repeat className="w-4 h-4 text-blue-600 dark:text-blue-400" />;
      case 'learning_coordinator':
        return <GitBranch className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />;
      case 'evolution':
        return <Cpu className="w-4 h-4 text-red-600 dark:text-red-400" />;
      case 'llm':
        return <Terminal className="w-4 h-4 text-brand-600 dark:text-brand-300" />;
      default:
        return <Heart className="w-4 h-4 text-red-600 dark:text-red-400" />;
    }
  };

  return (
    <div
      id="organ-matrix-view"
      className="h-full overflow-y-auto p-4 sm:p-6 max-w-5xl mx-auto space-y-6 select-text"
    >
      {/* Header Banner */}
      <div
        className={`border rounded-2xl p-5 shadow-sm relative overflow-hidden transition-colors ${
          isDark
            ? 'bg-[#0b0e17]/80 backdrop-blur-2xl border-white/10 shadow-2xl'
            : 'bg-white border-slate-200/90 shadow-sm'
        }`}
      >
        <div
          className={`absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl pointer-events-none ${
            isDark ? 'bg-brand-500/10' : 'bg-brand-500/5'
          }`}
        />
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-2.5 h-2.5 rounded-full bg-brand-500 animate-pulse shadow-[0_0_8px_#22d3ee]"></div>
              <h2
                className={`text-sm sm:text-base font-bold tracking-widest uppercase font-mono ${
                  isDark ? 'text-brand-50' : 'text-slate-900'
                }`}
              >
                NEURAL SUBSYSTEMS & ORGAN MATRIX
              </h2>
            </div>
            <p
              className={`text-xs font-mono ${
                isDark ? 'text-white/60' : 'text-slate-500'
              }`}
            >
              Real-time Subsystem Metrics & Diagnostics Control Unit &bull; UK Architecture
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div
              className={`border px-3.5 py-1.5 rounded-xl font-mono text-xs ${
                isDark
                  ? 'bg-black/40 backdrop-blur-xl border-white/10 text-brand-200'
                  : 'bg-slate-100 border-slate-200 text-slate-800'
              }`}
            >
              <span className={isDark ? 'text-white/40 text-xs uppercase' : 'text-slate-500 text-xs uppercase'}>
                ORGANISM PULSE:{' '}
              </span>
              <span className="text-brand-600 dark:text-brand-400 font-bold">{bpm} BPM</span>
              <span className={isDark ? 'text-white/30 ml-2' : 'text-slate-400 ml-2'}>#{beatCount}</span>
            </div>
            <button
              onClick={onTriggerPulse}
              className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold font-mono flex items-center gap-1.5 transition cursor-pointer ${
                isDark
                  ? 'bg-brand-400/15 hover:bg-brand-400/25 text-brand-200 border border-brand-400/40 shadow-[0_0_12px_rgba(34,211,238,0.2)]'
                  : 'bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-300 shadow-sm'
              }`}
            >
              <Radio className="w-3.5 h-3.5 text-brand-500 dark:text-brand-400" />
              <span>Stimulate Pulse</span>
            </button>
          </div>
        </div>
      </div>

      {/* Subsystem Organs Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {organs.map((organ, index) => (
          <motion.div
            key={organ.name}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04 }}
            className={`border p-4 rounded-2xl transition-all flex flex-col justify-between group ${
              isDark
                ? 'bg-[#0f121d]/80 backdrop-blur-xl border-white/10 hover:border-brand-400/40 shadow-xl'
                : 'bg-white border-slate-200/90 hover:border-brand-400 shadow-sm'
            }`}
          >
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2.5">
                  <div
                    className={`w-8 h-8 rounded-xl border flex items-center justify-center shadow-inner ${
                      isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-200'
                    }`}
                  >
                    {getIconForOrgan(organ.name)}
                  </div>
                  <div>
                    <h3
                      className={`font-mono font-bold text-xs capitalize ${
                        isDark ? 'text-white' : 'text-slate-900'
                      }`}
                    >
                      {organ.name.replace('_', ' ')}
                    </h3>
                    <span
                      className={`text-xs font-mono ${
                        isDark ? 'text-white/40' : 'text-slate-400'
                      }`}
                    >
                      {organ.classType}
                    </span>
                  </div>
                </div>

                <span
                  className={`px-2 py-0.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1 border ${
                    isDark
                      ? 'bg-green-400/10 text-green-400 border-green-400/30'
                      : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  }`}
                >
                  <CheckCircle2 className="w-2.5 h-2.5" /> ONLINE
                </span>
              </div>

              <p
                className={`text-xs leading-relaxed mb-3 ${
                  isDark ? 'text-slate-300' : 'text-slate-600'
                }`}
              >
                {organ.role}
              </p>
            </div>

            <div
              className={`pt-2.5 border-t flex items-center justify-between text-xs font-mono ${
                isDark ? 'border-white/10' : 'border-slate-100'
              }`}
            >
              <span className={isDark ? 'text-white/40' : 'text-slate-400'}>Diagnostics:</span>
              <span
                className={`font-semibold ${
                  isDark ? 'text-brand-300' : 'text-brand-700'
                }`}
              >
                {organ.metrics}
              </span>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Biological Loop Flow Explainer Card */}
      <div
        className={`border rounded-2xl p-4 font-mono text-xs space-y-2 shadow-sm ${
          isDark
            ? 'bg-black/40 backdrop-blur-2xl border-white/10 text-white/80'
            : 'bg-white border-slate-200 text-slate-700'
        }`}
      >
        <h4
          className={`font-bold flex items-center gap-2 uppercase tracking-wider ${
            isDark ? 'text-brand-300' : 'text-brand-700'
          }`}
        >
          <GitBranch className="w-4 h-4 text-brand-500 dark:text-brand-400" /> Real-time Execution Flow Pipeline
        </h4>
        <p
          className={`text-xs leading-relaxed ${
            isDark ? 'text-white/60' : 'text-slate-600'
          }`}
        >
          <code
            className={`px-1.5 py-0.5 rounded border ${
              isDark
                ? 'text-brand-200 bg-white/5 border-white/10'
                : 'text-brand-800 bg-brand-50 border-brand-200'
            }`}
          >
            USER INPUT
          </code>{' '}
          ➔{' '}
          <code
            className={`px-1.5 py-0.5 rounded border ${
              isDark
                ? 'text-brand-200 bg-white/5 border-white/10'
                : 'text-brand-800 bg-brand-50 border-brand-200'
            }`}
          >
            Memory Vector Retrieval (FAISS + Graph)
          </code>{' '}
          ➔{' '}
          <code
            className={`px-1.5 py-0.5 rounded border ${
              isDark
                ? 'text-brand-200 bg-white/5 border-white/10'
                : 'text-brand-800 bg-brand-50 border-brand-200'
            }`}
          >
            Native Pipeline / Groq Fallback Call
          </code>{' '}
          ➔{' '}
          <code
            className={`px-1.5 py-0.5 rounded border ${
              isDark
                ? 'text-brand-200 bg-white/5 border-white/10'
                : 'text-brand-800 bg-brand-50 border-brand-200'
            }`}
          >
            Instant Response to User
          </code>{' '}
          ➔{' '}
          <code
            className={`px-1.5 py-0.5 rounded border ${
              isDark
                ? 'text-green-300 bg-white/5 border-white/10'
                : 'text-emerald-800 bg-emerald-50 border-emerald-200'
            }`}
          >
            [Async Background Queue] ExperienceEngine ➔ SelfEvaluator ➔ KnowledgeBuilder ➔ Engram Store
          </code>
        </p>
      </div>
    </div>
  );
};
