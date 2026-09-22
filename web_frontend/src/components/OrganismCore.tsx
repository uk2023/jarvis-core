import React from 'react';
import { motion } from 'motion/react';
import { Activity, Cpu, Zap, Radio, Shield, Command } from 'lucide-react';
import { OrganismTelemetry, AppTheme } from '../types';

interface OrganismCoreProps {
  telemetry: OrganismTelemetry;
  onOpenCLI: () => void;
  onQuickPrompt: (prompt: string) => void;
  theme?: AppTheme;
}

export const OrganismCore: React.FC<OrganismCoreProps> = ({
  telemetry,
  onOpenCLI,
  onQuickPrompt,
  theme = 'dark',
}) => {
  const isDark = theme === 'dark';

  return (
    <div id="organism-core-container" className="flex flex-col items-center justify-center my-auto py-4 sm:py-8 text-center w-full max-w-xl mx-auto px-4 relative">
      {/* Central JARVIS Arc Reactor / Holographic Core */}
      <div className="relative mb-5 flex flex-col items-center">
        {/* Luminous Reactor Orbit */}
        <div id="black-hole-visualizer" className="relative w-28 h-28 sm:w-36 sm:h-36 flex items-center justify-center">
          {/* Outer Pulsing Glow */}
          <motion.div
            className={`absolute inset-0 rounded-full border ${
              isDark ? 'border-brand-400/30' : 'border-brand-500/40'
            }`}
            animate={{
              scale: [1, 1.1, 1],
              opacity: [0.3, 0.6, 0.3],
              rotate: 360,
            }}
            transition={{
              duration: 8,
              repeat: Infinity,
              ease: 'linear',
            }}
          />

          <motion.div
            className={`absolute w-24 h-24 sm:w-30 sm:h-30 rounded-full border border-dashed ${
              isDark ? 'border-brand-400/50' : 'border-brand-600/50'
            }`}
            animate={{ rotate: -360 }}
            transition={{ duration: 14, repeat: Infinity, ease: 'linear' }}
          />

          {/* Central Core Emblem */}
          <motion.div
            className={`w-16 h-16 sm:w-20 sm:h-20 rounded-full border-2 flex flex-col items-center justify-center backdrop-blur-xl z-10 ${
              isDark
                ? 'bg-[#050508]/90 border-brand-400 shadow-[0_0_35px_rgba(34,211,238,0.45)]'
                : 'bg-white border-brand-500 shadow-xl'
            }`}
            animate={{ scale: [0.97, 1.03, 0.97] }}
            transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}
          >
            <span
              className={`font-bold font-mono text-xl sm:text-2xl tracking-wider ${
                isDark ? 'text-brand-300 drop-shadow-[0_0_8px_#22d3ee]' : 'text-slate-900'
              }`}
            >
              J
            </span>
          </motion.div>

          {/* Orbiting Photon Particle */}
          <motion.div
            className="absolute w-24 h-24 sm:w-32 sm:h-32 rounded-full pointer-events-none"
            animate={{ rotate: 360 }}
            transition={{ duration: 4.5, repeat: Infinity, ease: 'linear' }}
          >
            <div className="w-2 h-2 rounded-full bg-brand-400 shadow-[0_0_8px_#22d3ee] -top-1 left-1/2 -translate-x-1/2 absolute" />
          </motion.div>
        </div>

        {/* Pulse Telemetry Pill */}
        <div
          className={`mt-3 px-3 py-0.5 rounded-full text-xs font-mono flex items-center gap-1.5 border shadow-sm ${
            isDark
              ? 'bg-brand-950/40 border-brand-500/30 text-brand-300 shadow-[0_0_10px_rgba(34,211,238,0.15)]'
              : 'bg-brand-50 border-brand-300 text-brand-800'
          }`}
        >
          <div className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse shadow-[0_0_6px_#22d3ee]" />
          <span className="uppercase tracking-widest font-semibold font-mono">
            PULSE {telemetry.bpm} BPM &bull; LATENCY {telemetry.avgLatencyMs}MS
          </span>
        </div>
      </div>

      {/* Main Greeting & Status */}
      <h2
        className={`text-base sm:text-lg font-bold tracking-wide uppercase mb-1 flex items-center justify-center gap-2 ${
          isDark ? 'text-white' : 'text-slate-900'
        }`}
      >
        <span>JARVIS COGNITIVE OS</span>
      </h2>
      <p
        className={`text-xs sm:text-xs max-w-sm mb-5 font-sans leading-relaxed ${
          isDark ? 'text-white/50' : 'text-slate-500'
        }`}
      >
        Native cognitive pipeline active with FAISS associative memory, SQLite persistence, and Groq fallback.
      </p>

      {/* Real-time Status Badges */}
      <div className="flex flex-wrap items-center justify-center gap-1.5 mb-5 text-xs font-mono">
        <span
          className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1 ${
            isDark ? 'bg-white/5 text-brand-200 border-white/10' : 'bg-slate-100 text-slate-700 border-slate-200'
          }`}
        >
          <Radio className="w-2.5 h-2.5 text-brand-400 animate-pulse" />
          <span>ASYNC LEARNING: ON</span>
        </span>
        <span
          className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1 ${
            isDark ? 'bg-white/5 text-white/80 border-white/10' : 'bg-slate-100 text-slate-700 border-slate-200'
          }`}
        >
          <Cpu className="w-2.5 h-2.5 text-brand-400" />
          <span>ARM64 8GB</span>
        </span>
        <span
          className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1 ${
            isDark ? 'bg-white/5 text-green-300 border-white/10' : 'bg-green-50 text-green-800 border-green-200'
          }`}
        >
          <Shield className="w-2.5 h-2.5 text-green-500" />
          <span>TYPO-RESILIENT</span>
        </span>
      </div>

      {/* Quick Suggestion Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
        <button
          id="btn-quick-status"
          onClick={() => onQuickPrompt('Status check of all active subsystems and memory engrams')}
          className={`p-3 rounded-xl text-left transition shadow-sm group cursor-pointer border ${
            isDark
              ? 'bg-white/[0.04] hover:bg-brand-500/10 border-white/10 hover:border-brand-400/40'
              : 'bg-white hover:bg-slate-50 border-slate-200 hover:border-brand-500'
          }`}
        >
          <div className="text-xs text-brand-500 dark:text-brand-300 font-semibold flex items-center gap-1.5 mb-0.5">
            <Cpu className="w-3 h-3 text-brand-400" />
            <span>Check Subsystem Health</span>
          </div>
          <p className={isDark ? 'text-xs text-white/40 truncate font-mono' : 'text-xs text-slate-500 truncate font-mono'}>
            Inspect 9 attached biological organs
          </p>
        </button>

        <button
          id="btn-quick-memory"
          onClick={() => onQuickPrompt('What are my hardware setup and personal memory facts?')}
          className={`p-3 rounded-xl text-left transition shadow-sm group cursor-pointer border ${
            isDark
              ? 'bg-white/[0.04] hover:bg-brand-500/10 border-white/10 hover:border-brand-400/40'
              : 'bg-white hover:bg-slate-50 border-slate-200 hover:border-brand-500'
          }`}
        >
          <div className="text-xs text-brand-500 dark:text-brand-300 font-semibold flex items-center gap-1.5 mb-0.5">
            <Zap className="w-3 h-3 text-brand-400" />
            <span>Recall Memory Facts</span>
          </div>
          <p className={isDark ? 'text-xs text-white/40 truncate font-mono' : 'text-xs text-slate-500 truncate font-mono'}>
            Query FAISS vector store & relations
          </p>
        </button>

        <button
          id="btn-quick-hinglish"
          onClick={() => onQuickPrompt('Mera ex ka naam Devyana hai aur mere dog ka naam Tommy h')}
          className={`p-3 rounded-xl text-left transition shadow-sm group cursor-pointer border ${
            isDark
              ? 'bg-white/[0.04] hover:bg-brand-500/10 border-white/10 hover:border-brand-400/40'
              : 'bg-white hover:bg-slate-50 border-slate-200 hover:border-brand-500'
          }`}
        >
          <div className="text-xs text-brand-500 dark:text-brand-300 font-semibold flex items-center gap-1.5 mb-0.5">
            <Command className="w-3 h-3 text-brand-400" />
            <span>Test Hinglish & Typos</span>
          </div>
          <p className={isDark ? 'text-xs text-white/40 truncate font-mono' : 'text-xs text-slate-500 truncate font-mono'}>
            Auto-extract facts & fix spelling
          </p>
        </button>

        <button
          id="btn-quick-trace"
          onClick={() => onQuickPrompt('Run diagnostic trace on typo-tolerant Hinglish pipeline')}
          className={`p-3 rounded-xl text-left transition shadow-sm group cursor-pointer border ${
            isDark
              ? 'bg-white/[0.04] hover:bg-brand-500/10 border-white/10 hover:border-brand-400/40'
              : 'bg-white hover:bg-slate-50 border-slate-200 hover:border-brand-500'
          }`}
        >
          <div className="text-xs text-brand-500 dark:text-brand-300 font-semibold flex items-center gap-1.5 mb-0.5">
            <Activity className="w-3 h-3 text-brand-400" />
            <span>Diagnostics Trace</span>
          </div>
          <p className={isDark ? 'text-xs text-white/40 truncate font-mono' : 'text-xs text-slate-500 truncate font-mono'}>
            Verify Qwen inference latency
          </p>
        </button>
      </div>
    </div>
  );
};
