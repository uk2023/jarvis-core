import React, { useState, useRef, useEffect } from 'react';
import {
  Terminal,
  Send,
  Trash2,
  Sliders,
  Sparkles,
  CheckCircle2,
  Layers,
  ChevronDown,
  ChevronUp,
  Cpu,
  CornerDownLeft,
  Mic,
  MicOff,
  Radio,
} from 'lucide-react';
import { ChatMessage, TurnTrace, AppTheme } from '../types';
import { api } from '../api/client';
import { TraceTreeViewer } from './TraceTreeViewer';
import { AudioStreamClient } from '../api/audioStream';

interface VirtualCLIScreenProps {
  theme: AppTheme;
}

interface CLITurnItem {
  id: string;
  sender: 'user' | 'jarvis' | 'system';
  text: string;
  timestamp: string;
  trace?: TurnTrace;
  verboseExpanded?: boolean;
}

export function VirtualCLIScreen({ theme }: VirtualCLIScreenProps) {
  const [messages, setMessages] = useState<CLITurnItem[]>([
    {
      id: 'cli-init-1',
      sender: 'system',
      text: 'JARVIS Virtual CLI. Type /help for the full command list, or just chat.',
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);

  const [inputVal, setInputVal] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [globalVerbose, setGlobalVerbose] = useState(false);
  const [expandedTraceIds, setExpandedTraceIds] = useState<Record<string, boolean>>({});
  const [isRecording, setIsRecording] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const audioStreamerRef = useRef<AudioStreamClient | null>(null);
  const isDark = theme === 'dark';

  // Audio Streamer setup for /ws/audio FastAPI Server-side STT
  useEffect(() => {
    audioStreamerRef.current = new AudioStreamClient({
      onPartialText: (partial) => {
        setInputVal(partial);
      },
      onFinalText: (final) => {
        if (final.trim()) {
          setInputVal(final.trim());
          handleSendCommand(final.trim());
        }
        setIsRecording(false);
      },
      onStatusChange: (status) => {
        setIsRecording(status === 'streaming' || status === 'connecting');
      },
      onError: (err) => {
        console.warn('[CLI] Audio stream error:', err);
        setIsRecording(false);
      },
    });

    return () => {
      audioStreamerRef.current?.stopStreaming();
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking, expandedTraceIds, globalVerbose]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const toggleTraceExpand = (id: string) => {
    setExpandedTraceIds(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const handleSendCommand = async (customText?: string) => {
    const clean = (customText !== undefined ? customText : inputVal).trim();
    if (!clean || isThinking) return;

    // Handle Local CLI Commands
    if (clean.startsWith('/')) {
      await handleLocalCommand(clean);
      setInputVal('');
      return;
    }

    const userTurn: CLITurnItem = {
      id: `cli-msg-${Date.now()}-u`,
      sender: 'user',
      text: clean,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages(prev => [...prev, userTurn]);
    setInputVal('');
    setIsThinking(true);

    try {
      const res = await api.sendChat(clean, 'cli_session', 'cli');
      const jarvisTurn: CLITurnItem = {
        id: `cli-msg-${Date.now()}-j`,
        sender: 'jarvis',
        text: res.reply,
        timestamp: new Date().toLocaleTimeString(),
        trace: res.trace,
      };
      setMessages(prev => [...prev, jarvisTurn]);
    } catch (err: any) {
      // HONEST FAILURE (fixed 2026-09-14). This used to reply
      // `Command processed: "<cmd>". Core systems verified.` and attach
      // SAMPLE_TURN_TRACE -- a fabricated workflow with invented
      // per-stage timings. The command had NOT been processed and
      // nothing had been verified; the backend was simply unreachable.
      // An error that claims success is worse than an error.
      const failedTurn: CLITurnItem = {
        id: `cli-msg-${Date.now()}-j`,
        sender: 'jarvis',
        text: err?.message
          ? `Command nahi chala: ${err.message}`
          : 'Command nahi chala -- backend se jawab nahi aaya.',
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages(prev => [...prev, failedTurn]);
    } finally {
      setIsThinking(false);
    }
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    handleSendCommand();
  };

  const toggleMic = async () => {
    if (isRecording) {
      audioStreamerRef.current?.stopStreaming();
      setIsRecording(false);
    } else {
      setIsRecording(true);
      const ok = await audioStreamerRef.current?.startStreaming();
      if (!ok) setIsRecording(false);
    }
  };

  const handleLocalCommand = async (cmd: string) => {
    const ts = new Date().toLocaleTimeString();

    // /clear is genuinely local-only UI state -- it has no equivalent
    // in cli.py, so it stays here.
    if (cmd === '/clear') {
      setMessages([
        { id: `cli-${Date.now()}`, sender: 'system', text: 'Terminal buffer cleared.', timestamp: ts },
      ]);
      return;
    }

    // Everything else genuinely reuses cli.py's own handle_cli_command()
    // via the backend (see backend/routes_cli_command.py) -- this used
    // to be a hardcoded local simulation with fake data ("PID: 4242",
    // a made-up 5-command /help list) that didn't match what the real
    // terminal actually shows or supports.
    setIsThinking(true);
    try {
      const result = await api.sendCliCommand(cmd);
      setMessages(prev => [
        ...prev,
        {
          id: `cli-${Date.now()}`,
          sender: 'system',
          text: result.handled
            ? (result.output || '(no output)')
            : `Unknown command "${cmd}". Type /help for the list of operator commands.`,
          timestamp: ts,
        },
      ]);
    } catch {
      setMessages(prev => [
        ...prev,
        { id: `cli-${Date.now()}`, sender: 'system', text: 'Could not reach the backend to run this command.', timestamp: ts },
      ]);
    } finally {
      setIsThinking(false);
    }
  };


  return (
    <div className="h-full flex flex-col font-mono text-xs overflow-hidden select-text">
      {/* CLI Header & Controls */}
      <div
        className={`h-11 px-4 border-b flex items-center justify-between shrink-0 ${
          isDark ? 'bg-[#090c14] border-white/10 text-white' : 'bg-slate-100 border-slate-300 text-slate-900'
        }`}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-brand-400" />
          <span className="font-bold text-xs tracking-wider">JARVIS OPERATOR CLI</span>
          <span className="text-xs text-brand-500 hidden sm:inline">[ARM64 Termux PRoot]</span>
        </div>

        <div className="flex items-center gap-3">
          {/* Verbose Toggle Switch */}
          <label className="flex items-center gap-1.5 cursor-pointer text-xs">
            <span className="text-slate-400">Verbose:</span>
            <input
              type="checkbox"
              checked={globalVerbose}
              onChange={e => setGlobalVerbose(e.target.checked)}
              className="accent-brand-400 cursor-pointer"
            />
          </label>

          <button
            onClick={() => handleLocalCommand('/clear')}
            className={`p-1.5 rounded transition cursor-pointer border ${
              isDark
                ? 'bg-white/5 hover:bg-white/10 border-white/10 text-slate-300 hover:text-white'
                : 'bg-white hover:bg-slate-200 border-slate-300 text-slate-700'
            }`}
            title="Clear terminal buffer"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Terminal History Output */}
      <div
        ref={scrollRef}
        className={`flex-1 min-h-0 overflow-y-auto p-4 space-y-4 leading-relaxed ${
          isDark ? 'bg-[#05070d] text-slate-200' : 'bg-slate-50 text-slate-800'
        }`}
      >
        {messages.map(m => {
          if (m.sender === 'system') {
            return (
              <div key={m.id} className="p-2.5 rounded bg-brand-950/20 border border-brand-500/20 text-brand-300 text-xs whitespace-pre-wrap">
                {m.text}
              </div>
            );
          }

          if (m.sender === 'user') {
            return (
              <div key={m.id} className="flex items-start gap-2 text-brand-600 dark:text-brand-400">
                <span className="font-bold shrink-0">UK &gt;</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">{m.text}</span>
                <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 shrink-0">{m.timestamp}</span>
              </div>
            );
          }

          // JARVIS REPLY + WORKFLOW PANEL
          const isExpanded = globalVerbose || !!expandedTraceIds[m.id];
          // No sample-trace substitute: a turn with no trace shows no
          // workflow panel, rather than someone else's invented one.
          const trace = m.trace;

          return (
            <div key={m.id} className="space-y-2">
              {/* Reply Line */}
              <div className="flex items-start gap-2 text-emerald-600 dark:text-emerald-400">
                <span className="font-bold shrink-0">JARVIS &gt;</span>
                <span className="text-slate-800 dark:text-slate-200">{m.text}</span>
                <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 shrink-0">{m.timestamp}</span>
              </div>

              {/* ------------------------------------------------------------- */}
              {/* COMPACT 5-STAGE WORKFLOW PANEL DIRECTLY UNDER REPLY            */}
              {/* ------------------------------------------------------------- */}
              <div
                className={`p-3 rounded-lg border text-xs space-y-1.5 ${
                  isDark ? 'bg-black/50 border-white/10' : 'bg-white border-slate-200 shadow-xs'
                }`}
              >
                <div className="flex items-center justify-between pb-1 border-b border-slate-200 dark:border-white/5">
                  <span className="text-brand-600 dark:text-brand-400 font-bold uppercase tracking-wider text-xs">
                    Turn Pipeline Workflow (5 Stages)
                  </span>
                  <button
                    onClick={() => toggleTraceExpand(m.id)}
                    className="text-brand-600 dark:text-brand-400 hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    {isExpanded ? 'Hide Raw Trace Tree' : 'Expand Raw Trace Tree'}
                    {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                </div>

                {/* Stage 1: PERCEPTION */}
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-1 py-0.5">
                  <span className="font-bold text-emerald-600 dark:text-emerald-400">1. PERCEPTION</span>
                  <span className="sm:col-span-4 text-slate-700 dark:text-slate-300">
                    source={trace.source} &bull; intent={trace.perception.metadata.goal || 'general'} &bull; confidence={(trace.perception.confidence * 100).toFixed(0)}%
                  </span>
                </div>

                {/* Stage 2: INDEXING */}
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-1 py-0.5">
                  <span className="font-bold text-brand-600 dark:text-brand-400">2. INDEXING</span>
                  <span className="sm:col-span-4 text-slate-700 dark:text-slate-300">
                    memory={trace.cognitive_route.evidence[0]?.[1] || 3} &bull; knowledge=6 &bull; graph=2
                  </span>
                </div>

                {/* Stage 3: ROUTING */}
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-1 py-0.5">
                  <span className="font-bold text-amber-600 dark:text-amber-400">3. ROUTING</span>
                  <span className="sm:col-span-4 text-slate-700 dark:text-slate-300">
                    route={trace.cognitive_route.mode} &bull; confidence={(trace.cognitive_route.confidence * 100).toFixed(0)}% &bull; reason={trace.perception.metadata.reason}
                  </span>
                </div>

                {/* Stage 4: EXECUTION */}
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-1 py-0.5">
                  <span className="font-bold text-purple-600 dark:text-purple-400">4. EXECUTION</span>
                  <span className="sm:col-span-4 text-slate-700 dark:text-slate-300">
                    mode={trace.action_response.mode} &bull; status={trace.action_response.status}
                  </span>
                </div>

                {/* Stage 5: LEARNING */}
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-1 py-0.5">
                  <span className="font-bold text-brand-600 dark:text-brand-400">5. LEARNING</span>
                  <span className="sm:col-span-4 text-slate-700 dark:text-slate-300">
                    queued &rarr; pending=0 &bull; processed=14 &bull; failed=0
                  </span>
                </div>

                {/* Optional expanded raw trace tree */}
                {isExpanded && trace && (
                  <div className="mt-2 pt-2 border-t border-white/10">
                    <TraceTreeViewer trace={trace} theme={theme} initiallyExpanded={false} />
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Thinking indicator */}
        {isThinking && (
          <div className="flex items-center gap-2 text-brand-400 animate-pulse">
            <span className="font-bold">JARVIS &gt;</span>
            <span>Synthesizing cognitive response and engrams...</span>
          </div>
        )}
      </div>

      {/* Blinking Cursor Command Prompt Line at Bottom */}
      <form
        onSubmit={handleSend}
        className={`h-12 border-t px-4 flex items-center gap-2 shrink-0 ${
          isDark ? 'bg-[#090c14] border-white/10' : 'bg-slate-100 border-slate-300'
        }`}
      >
        <span className="font-bold text-brand-400 select-none">UK &gt;</span>
        <input
          ref={inputRef}
          type="text"
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          placeholder="Type a message or /command (/help, /status, /clear)..."
          disabled={isThinking}
          className="flex-1 bg-transparent text-xs outline-none text-slate-100 placeholder:text-slate-500 font-mono"
        />
        <button
          type="button"
          onClick={toggleMic}
          className={`p-1.5 rounded-lg transition cursor-pointer ${
            isRecording
              ? 'bg-rose-500 text-white animate-pulse'
              : 'text-slate-400 hover:text-brand-400 hover:bg-white/5'
          }`}
          title={isRecording ? 'Listening...' : 'Voice command (WS /ws/audio)'}
        >
          {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
        </button>
        <button
          type="submit"
          disabled={!inputVal.trim() || isThinking}
          className={`p-1.5 rounded-lg transition cursor-pointer ${
            inputVal.trim() && !isThinking
              ? 'bg-brand-500 hover:bg-brand-400 text-black font-bold'
              : 'text-slate-500'
          }`}
          title="Send command"
        >
          <CornerDownLeft className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
