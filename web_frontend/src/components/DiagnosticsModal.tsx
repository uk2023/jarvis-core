import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Terminal,
  X,
  Play,
  Minus,
  Maximize2,
  Minimize2,
  Radio,
  CheckCircle2,
  Trash2,
  Shield,
  ShieldAlert,
  Clock,
} from 'lucide-react';
import { AppTheme, SafetyCheckEntry } from '../types';
import { api } from '../api/client';

interface DiagnosticsModalProps {
  isOpen: boolean;
  onClose: () => void;
  beatCount: number;
  theme?: AppTheme;
}

export const DiagnosticsModal: React.FC<DiagnosticsModalProps> = ({
  isOpen,
  onClose,
  beatCount,
  theme = 'dark',
}) => {
  const [activeTab, setActiveTab] = useState<'terminal' | 'safety'>('terminal');
  const [safetyHistory, setSafetyHistory] = useState<SafetyCheckEntry[]>([]);
  const [logs, setLogs] = useState<string[]>([
    `[${new Date().toLocaleTimeString()}] Diagnostics terminal ready. Type any /command (e.g. /memory_inspect, /organ_inspect) or "help".`,
  ]);
  const [cmdInput, setCmdInput] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const isDark = theme === 'dark';

  useEffect(() => {
    if (isOpen) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      api.getSafetyHistory().then(data => setSafetyHistory(data));
    }
  }, [logs, isOpen]);

  if (!isOpen) return null;

  // Genuinely reuses cli.py's own handle_cli_command() via /api/cli_command
  // (see backend/routes_cli_command.py) -- previously a completely fake,
  // hardcoded simulation.
  const handleCommand = async (e: React.FormEvent) => {
    e.preventDefault();
    const cmd = cmdInput.trim();
    if (!cmd || isRunning) return;

    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, `[${time}] UK@jarvis:~$ ${cmd}`]);
    setCmdInput('');

    if (cmd === 'clear') {
      setLogs([]);
      return;
    }

    const slashCmd = cmd.startsWith('/') ? cmd : `/${cmd}`;
    setIsRunning(true);
    try {
      const result = await api.sendCliCommand(slashCmd);
      setLogs(prev => [
        ...prev,
        result.handled
          ? (result.output || '(no output)')
          : `Unknown command "${cmd}". Try "help" for the full command list.`,
      ]);
    } catch {
      setLogs(prev => [...prev, 'Could not reach the backend to run this command.']);
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <AnimatePresence>
      <div
        id="virtual-cli-container"
        className="fixed inset-0 z-50 pointer-events-none flex items-end sm:items-center justify-end sm:p-5"
      >
        {/* Transparent non-blocking backdrop on desktop, light dismissible backdrop on mobile */}
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/30 backdrop-blur-[2px] pointer-events-auto sm:bg-black/10"
        />

        {/* Authentic Floating Terminal Window on Right Side */}
        <motion.div
          initial={{ opacity: 0, y: 30, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 30, scale: 0.95 }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className={`pointer-events-auto w-full flex flex-col rounded-t-2xl sm:rounded-2xl border shadow-2xl overflow-hidden font-mono text-xs z-50 transition-all ${
            isExpanded
              ? 'sm:w-[680px] h-[85vh]'
              : 'sm:w-[480px] md:w-[500px] h-[65vh] sm:h-[480px]'
          } ${
            isDark
              ? 'bg-[#090c15]/95 backdrop-blur-2xl border-white/20 text-white shadow-[0_20px_60px_rgba(0,0,0,0.8)]'
              : 'bg-slate-900/95 backdrop-blur-2xl border-slate-700 text-slate-100 shadow-[0_20px_50px_rgba(0,0,0,0.4)]'
          }`}
        >
          {/* Authentic Terminal Title Bar with Traffic Lights */}
          <div
            className={`flex items-center justify-between px-3.5 py-2.5 border-b select-none ${
              isDark ? 'bg-black/60 border-white/10' : 'bg-slate-950 border-slate-800'
            }`}
          >
            {/* Window Traffic Lights & Title */}
            <div className="flex items-center gap-2.5">
              <div className="flex items-center gap-1.5">
                <button
                  onClick={onClose}
                  className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-600 transition flex items-center justify-center group cursor-pointer"
                  title="Close Terminal"
                >
                  <X className="w-2 h-2 text-black/70 opacity-0 group-hover:opacity-100" />
                </button>
                <button
                  onClick={onClose}
                  className="w-3 h-3 rounded-full bg-amber-500 hover:bg-amber-600 transition flex items-center justify-center group cursor-pointer"
                  title="Minimize"
                >
                  <Minus className="w-2 h-2 text-black/70 opacity-0 group-hover:opacity-100" />
                </button>
                <button
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="w-3 h-3 rounded-full bg-emerald-500 hover:bg-emerald-600 transition flex items-center justify-center group cursor-pointer"
                  title="Toggle Size"
                >
                  {isExpanded ? (
                    <Minimize2 className="w-2 h-2 text-black/70 opacity-0 group-hover:opacity-100" />
                  ) : (
                    <Maximize2 className="w-2 h-2 text-black/70 opacity-0 group-hover:opacity-100" />
                  )}
                </button>
              </div>

              <div className="flex items-center gap-1.5 text-xs text-slate-300 font-semibold pl-1">
                <button
                  onClick={() => setActiveTab('terminal')}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer transition ${
                    activeTab === 'terminal'
                      ? 'bg-brand-500/20 text-brand-300 border border-brand-500/40'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Terminal className="w-3 h-3" />
                  <span>Terminal</span>
                </button>

                <button
                  onClick={() => setActiveTab('safety')}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer transition ${
                    activeTab === 'safety'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Shield className="w-3 h-3" />
                  <span>Safety History</span>
                </button>
              </div>
            </div>

            {/* Right Status Badges */}
            <div className="flex items-center gap-2">
              <span className="text-emerald-400 text-xs bg-emerald-500/10 px-2 py-0.5 rounded-md border border-emerald-500/30 font-bold flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                LIVE
              </span>
              {activeTab === 'terminal' && (
                <button
                  onClick={() => setLogs([])}
                  className="text-slate-400 hover:text-slate-200 p-1 rounded transition cursor-pointer"
                  title="Clear Logs"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Body: Terminal Console Output OR Safety Check History */}
          {activeTab === 'safety' ? (
            <div
              className={`flex-1 overflow-y-auto p-4 space-y-3 select-text font-mono text-xs ${
                isDark ? 'bg-black/80 text-slate-200' : 'bg-slate-950 text-slate-200'
              }`}
            >
              {/* Header & Policy Note */}
              <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <ShieldAlert className="w-3.5 h-3.5" />
                  <span>Prompt-Injection Classifier Audit Log (Llama Prompt Guard 2)</span>
                </div>
                <p className="text-xs text-amber-200/80">
                  Llama Prompt Guard 2 flags are logged for operator audit; queries are not auto-blocked per policy.
                </p>
              </div>

              <div className="space-y-2">
                {safetyHistory.map((item) => (
                  <div
                    key={item.id}
                    className={`p-3 rounded-lg border space-y-1.5 text-xs ${
                      item.label === 'injection'
                        ? 'bg-rose-950/20 border-rose-500/40 text-rose-200'
                        : 'bg-white/[0.02] border-white/10 text-slate-300'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Clock className="w-3 h-3 text-slate-400" />
                        <span className="text-slate-400 font-mono text-xs">
                          {new Date(item.timestamp).toLocaleTimeString()}
                        </span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-xs font-bold uppercase border ${
                            item.label === 'injection'
                              ? 'bg-rose-500/20 text-rose-300 border-rose-500/50'
                              : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
                          }`}
                        >
                          {item.label} (score: {item.score.toFixed(2)})
                        </span>
                      </div>
                      <span className="px-2 py-0.5 rounded text-xs bg-white/5 border border-white/10 text-brand-400">
                        {item.action}
                      </span>
                    </div>

                    <div className="font-mono text-slate-100 bg-black/40 p-2 rounded border border-white/5">
                      &quot;{item.query_preview}&quot;
                    </div>

                    {item.notes && (
                      <div className="text-xs text-slate-400">
                        <span className="text-brand-400">Notes:</span> {item.notes}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Terminal Console Output */}
              <div
                className={`flex-1 overflow-y-auto p-3.5 space-y-1.5 text-xs leading-relaxed select-text font-mono ${
                  isDark ? 'bg-black/70 text-slate-200' : 'bg-slate-950 text-slate-200'
                }`}
              >
                {logs.length === 0 ? (
                  <div className="text-slate-500 italic py-4 text-center">
                    Terminal cleared. Type 'help' for commands.
                  </div>
                ) : (
                  logs.map((log, index) => (
                    <div key={index} className="whitespace-pre-wrap break-words">
                      {log.includes('UK@jarvis') ? (
                        <span className="text-brand-400 font-bold">{log}</span>
                      ) : log.includes('ERROR') ? (
                        <span className="text-red-400 font-semibold">{log}</span>
                      ) : log.includes('WARN') ? (
                        <span className="text-amber-400 font-semibold">{log}</span>
                      ) : log.includes('PASS') || log.includes('ONLINE') ? (
                        <span className="text-emerald-400 font-semibold">{log}</span>
                      ) : log.includes('[STATUS MATRIX]') || log.includes('[PULSE]') ? (
                        <span className="text-brand-300">{log}</span>
                      ) : (
                        <span className="text-slate-300">{log}</span>
                      )}
                    </div>
                  ))
                )}
                <div ref={logEndRef} />
              </div>

              {/* Terminal Command Input Form */}
              <form
                onSubmit={handleCommand}
                className={`p-2.5 border-t flex items-center gap-2 ${
                  isDark ? 'bg-black/80 border-white/10' : 'bg-slate-900 border-slate-800'
                }`}
              >
                <span className="text-brand-400 font-bold shrink-0 text-xs">UK@jarvis:~$</span>
                <input
                  type="text"
                  value={cmdInput}
                  onChange={e => setCmdInput(e.target.value)}
                  placeholder="Type 'help', 'status', 'pulse', 'test-hinglish'..."
                  className="flex-1 bg-transparent border-none outline-none text-white text-xs font-mono placeholder-slate-500"
                  autoFocus
                />
                <button
                  type="submit"
                  className="px-2.5 py-1 bg-brand-500 hover:bg-brand-400 text-black font-bold rounded-lg text-xs flex items-center gap-1 transition cursor-pointer shadow-sm"
                >
                  <Play className="w-2.5 h-2.5 fill-black" />
                  <span>Run</span>
                </button>
              </form>
            </>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
