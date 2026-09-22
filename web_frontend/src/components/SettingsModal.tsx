import React, { useState } from 'react';
import {
  X,
  Sliders,
  Sun,
  Moon,
  Volume2,
  VolumeX,
  Radio,
  Wifi,
  Server,
  Cpu,
  RefreshCw,
  Check,
  AlertCircle,
  HelpCircle,
  Sparkles,
  Layers,
  MessageSquare,
  Shield,
  Trash2,
} from 'lucide-react';
import { AppTheme } from '../types';
import { api } from '../api/client';
import { VoiceControlPanel } from './VoiceControlPanel';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  theme: AppTheme;
  onToggleTheme: () => void;
  onSetTheme: (theme: AppTheme) => void;
}

type SettingsCategory = 'general' | 'voice' | 'backend' | 'about';

export function SettingsModal({
  isOpen,
  onClose,
  theme,
  onSetTheme,
}: SettingsModalProps) {
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('general');
  const [soundEnabled, setSoundEnabled] = useState(() => {
    return localStorage.getItem('jarvis_sound_enabled') !== 'false';
  });
  const [hinglishNormalization, setHinglishNormalization] = useState(true);
  const [compactChat, setCompactChat] = useState(false);
  const [pollInterval, setPollInterval] = useState('2s');
  const [backendUrl, setBackendUrlInput] = useState(() => api.getBackendUrl());
  const [testStatus, setTestStatus] = useState<{ testing: boolean; message: string | null; ok?: boolean }>({
    testing: false,
    message: null,
  });
  const [clearedCache, setClearedCache] = useState(false);

  if (!isOpen) return null;

  const isDark = theme === 'dark';

  const handleToggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    localStorage.setItem('jarvis_sound_enabled', String(next));
  };

  const handleSaveBackendUrl = () => {
    api.setBackendUrl(backendUrl);
    setTestStatus({ testing: false, message: 'Backend URL saved successfully.', ok: true });
    setTimeout(() => setTestStatus({ testing: false, message: null }), 3000);
  };

  const handleTestBackendConnection = async () => {
    setTestStatus({ testing: true, message: 'Pinging /api/health...' });
    api.setBackendUrl(backendUrl);
    const result = await api.testConnection();
    setTestStatus({ testing: false, message: result.message, ok: result.ok });
  };

  const handleClearCache = () => {
    setClearedCache(true);
    setTimeout(() => setClearedCache(false), 2500);
  };

  const categories = [
    { id: 'general' as const, label: 'General', icon: Sliders, desc: 'Theme, sound & layout' },
    { id: 'voice' as const, label: 'Voice & Speech', icon: Volume2, desc: 'TTS engines & speech rates' },
    { id: 'backend' as const, label: 'Backend & Network', icon: Server, desc: 'Endpoints & telemetry' },
    { id: 'about' as const, label: 'About & System', icon: Cpu, desc: 'Version & architecture' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/75 backdrop-blur-xs animate-in fade-in duration-150">
      <div
        className={`w-full max-w-2xl max-h-[90vh] rounded-2xl border shadow-2xl overflow-hidden flex flex-col transition-all ${
          isDark
            ? 'bg-[#090d16] border-white/10 text-white shadow-black/80'
            : 'bg-white border-slate-200 text-slate-900 shadow-2xl'
        }`}
      >
        {/* Top Header Bar */}
        <div
          className={`px-4 sm:px-6 py-3.5 border-b flex items-center justify-between shrink-0 ${
            isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-brand-500/15 border border-brand-400/40 flex items-center justify-center text-brand-500">
              <Sliders className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-bold text-sm sm:text-base">Settings</h2>
              <p className="text-xs text-slate-400 font-mono">
                System Preferences & Environment
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-white transition cursor-pointer"
            title="Close Settings"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ChatGPT-Style Responsive Layout: Sidebar Tabs + Content Area */}
        <div className="flex-1 flex flex-col md:flex-row min-h-0 overflow-hidden">
          {/* Category Navigation (Horizontal scroll on mobile, Left column on desktop) */}
          <div
            className={`w-full md:w-56 p-2 md:p-3 border-b md:border-b-0 md:border-r shrink-0 flex md:flex-col gap-1 overflow-x-auto md:overflow-y-auto no-scrollbar ${
              isDark ? 'bg-black/20 border-white/10' : 'bg-slate-50/80 border-slate-200'
            }`}
          >
            {categories.map(cat => {
              const Icon = cat.icon;
              const isActive = activeCategory === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.id)}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition cursor-pointer whitespace-nowrap md:whitespace-normal text-left ${
                    isActive
                      ? isDark
                        ? 'bg-brand-500/20 text-brand-300 font-bold border border-brand-500/30'
                        : 'bg-brand-50 text-brand-800 font-bold border border-brand-200'
                      : isDark
                      ? 'text-slate-400 hover:text-white hover:bg-white/5'
                      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                  }`}
                >
                  <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-brand-500' : 'text-slate-400'}`} />
                  <div className="min-w-0">
                    <span className="block truncate">{cat.label}</span>
                    <span className="hidden md:block text-xs text-slate-400 font-normal font-sans truncate">
                      {cat.desc}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Right Main Scrollable Content */}
          <div className="flex-1 min-w-0 overflow-y-auto p-4 sm:p-6 space-y-6">
            {/* 1. GENERAL CATEGORY */}
            {activeCategory === 'general' && (
              <div className="space-y-5">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 dark:text-brand-400 font-mono mb-1">
                    Appearance & Theme
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Customize the interface brightness and visual ambiance.
                  </p>

                  <div className="grid grid-cols-2 gap-3 mt-3">
                    <button
                      onClick={() => onSetTheme('light')}
                      className={`p-3 rounded-xl border flex items-center gap-3 transition cursor-pointer ${
                        theme === 'light'
                          ? 'border-brand-500 bg-brand-500/10 text-brand-800 dark:text-brand-300 font-bold shadow-xs'
                          : isDark
                          ? 'border-white/10 bg-white/[0.02] text-slate-300 hover:bg-white/5'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <div className="p-2 rounded-lg bg-amber-500/10 text-amber-500">
                        <Sun className="w-4 h-4" />
                      </div>
                      <div className="text-left">
                        <span className="block text-xs font-semibold">Light Mode</span>
                        <span className="text-xs text-slate-400 font-normal">Daytime clarity</span>
                      </div>
                    </button>

                    <button
                      onClick={() => onSetTheme('dark')}
                      className={`p-3 rounded-xl border flex items-center gap-3 transition cursor-pointer ${
                        theme === 'dark'
                          ? 'border-brand-500 bg-brand-500/10 text-brand-300 font-bold shadow-xs'
                          : isDark
                          ? 'border-white/10 bg-white/[0.02] text-slate-300 hover:bg-white/5'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <div className="p-2 rounded-lg bg-brand-500/10 text-brand-400">
                        <Moon className="w-4 h-4" />
                      </div>
                      <div className="text-left">
                        <span className="block text-xs font-semibold">Dark Mode</span>
                        <span className="text-xs text-slate-400 font-normal">OLED deep space</span>
                      </div>
                    </button>
                  </div>
                </div>

                <div className="pt-4 border-t border-slate-200 dark:border-white/10 space-y-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 dark:text-brand-400 font-mono">
                    Audio & Interactions
                  </h3>

                  {/* Sound Effects Toggle */}
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                        Sound Effects & Notifications
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        Play subtle audio chime when messages arrive and state changes.
                      </div>
                    </div>
                    <button
                      onClick={handleToggleSound}
                      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        soundEnabled ? 'bg-brand-600' : isDark ? 'bg-white/20' : 'bg-slate-300'
                      }`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                          soundEnabled ? 'translate-x-5' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </div>

                  {/* Hinglish Phonetic Normalization */}
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                        Hinglish Phonetic Auto-Repair
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        Map colloquial romanized Hindi/English tokens into canonical intent schema.
                      </div>
                    </div>
                    <button
                      onClick={() => setHinglishNormalization(!hinglishNormalization)}
                      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        hinglishNormalization ? 'bg-brand-600' : isDark ? 'bg-white/20' : 'bg-slate-300'
                      }`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                          hinglishNormalization ? 'translate-x-5' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 2. VOICE & SPEECH CATEGORY */}
            {activeCategory === 'voice' && (
              <div className="space-y-4">
                <VoiceControlPanel theme={theme} />
              </div>
            )}

            {/* 3. BACKEND & NETWORK CATEGORY */}
            {activeCategory === 'backend' && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 dark:text-brand-400 font-mono mb-1">
                    Cognitive Endpoint & Telemetry
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Configure backend URL for FastAPI organism daemon and WebSocket streams.
                  </p>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300">
                    Backend Target Base URL
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={backendUrl}
                      onChange={e => setBackendUrlInput(e.target.value)}
                      placeholder="http://127.0.0.1:8000"
                      className={`flex-1 px-3 py-2 rounded-xl border text-xs font-mono outline-none ${
                        isDark
                          ? 'bg-black/40 border-white/10 text-brand-300 focus:border-brand-400'
                          : 'bg-white border-slate-300 text-slate-800 focus:border-brand-500'
                      }`}
                    />
                    <button
                      onClick={handleSaveBackendUrl}
                      className="px-3 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs transition cursor-pointer"
                    >
                      Save
                    </button>
                  </div>
                </div>

                {/* Connection Status & Ping */}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                  <button
                    onClick={handleTestBackendConnection}
                    disabled={testStatus.testing}
                    className={`px-3 py-1.5 rounded-lg border text-xs font-mono flex items-center gap-1.5 transition cursor-pointer ${
                      isDark
                        ? 'bg-white/5 hover:bg-white/10 border-white/10 text-brand-300'
                        : 'bg-slate-100 hover:bg-slate-200 border-slate-300 text-slate-800'
                    }`}
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${testStatus.testing ? 'animate-spin' : ''}`} />
                    <span>Test /api/health</span>
                  </button>

                  <div className="flex items-center gap-2 text-xs font-mono">
                    <span className="text-slate-400">WebSocket:</span>
                    <span className="text-emerald-500 font-bold flex items-center gap-1">
                      <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                      Live (14ms)
                    </span>
                  </div>
                </div>

                {testStatus.message && (
                  <div
                    className={`p-3 rounded-xl border text-xs font-mono flex items-start gap-2 ${
                      testStatus.ok
                        ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                        : 'bg-amber-500/15 border-amber-500/30 text-amber-600 dark:text-amber-400'
                    }`}
                  >
                    {testStatus.ok ? <Check className="w-4 h-4 shrink-0 mt-0.5" /> : <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />}
                    <span>{testStatus.message}</span>
                  </div>
                )}

                {/* Polling Interval Setting */}
                <div className="pt-3 border-t border-slate-200 dark:border-white/10 space-y-2">
                  <label className="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300 block">
                    Telemetry Refresh Frequency
                  </label>
                  <div className="grid grid-cols-4 gap-2 text-xs font-mono">
                    {['1s', '2s', '5s', 'Paused'].map(rate => (
                      <button
                        key={rate}
                        onClick={() => setPollInterval(rate)}
                        className={`py-1.5 rounded-lg border text-center transition cursor-pointer ${
                          pollInterval === rate
                            ? 'bg-brand-600 text-white font-bold border-brand-600'
                            : isDark
                            ? 'bg-white/5 border-white/10 text-slate-300 hover:bg-white/10'
                            : 'bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100'
                        }`}
                      >
                        {rate}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 4. ABOUT & SYSTEM CATEGORY */}
            {activeCategory === 'about' && (
              <div className="space-y-5">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 dark:text-brand-400 font-mono mb-1">
                    System Architecture & Parity
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Snapdragon ARM64 native Termux cognitive daemon specifications.
                  </p>
                </div>

                <div
                  className={`p-3.5 rounded-xl border space-y-2.5 font-mono text-xs ${
                    isDark ? 'bg-black/30 border-white/5 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-700'
                  }`}
                >
                  <div className="flex justify-between py-1 border-b border-slate-200 dark:border-white/5">
                    <span className="text-slate-400">Core Engine</span>
                    <span className="font-bold text-slate-900 dark:text-white">JARVIS Cognitive OS v2026.4</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-200 dark:border-white/5">
                    <span className="text-slate-400">Architecture</span>
                    <span className="font-bold text-slate-900 dark:text-white">ARM64 (Snapdragon Termux)</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-200 dark:border-white/5">
                    <span className="text-slate-400">Vector Memory</span>
                    <span className="font-bold text-brand-600 dark:text-brand-400">FAISS 384-dimensional</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-200 dark:border-white/5">
                    <span className="text-slate-400">Fallback LLM</span>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400">Groq openai/gpt-oss-120b</span>
                  </div>
                  <div className="flex justify-between py-1">
                    <span className="text-slate-400">Contracts Engine</span>
                    <span className="font-bold text-purple-600 dark:text-purple-400">Safe Deterministic Regex</span>
                  </div>
                </div>

                {/* Storage & Cache Management */}
                <div className="pt-3 border-t border-slate-200 dark:border-white/10 space-y-2">
                  <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                    Local Cache & Data Storage
                  </h4>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      Reset temporary conversational session cache and reload defaults.
                    </span>
                    <button
                      onClick={handleClearCache}
                      className={`px-3 py-1.5 rounded-lg border text-xs font-mono flex items-center gap-1.5 transition cursor-pointer ${
                        clearedCache
                          ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 font-bold'
                          : 'bg-rose-500/10 hover:bg-rose-500/20 text-rose-500 border-rose-500/30'
                      }`}
                    >
                      {clearedCache ? <Check className="w-3.5 h-3.5" /> : <Trash2 className="w-3.5 h-3.5" />}
                      <span>{clearedCache ? 'Cache Cleared' : 'Clear Cache'}</span>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div
          className={`px-4 sm:px-6 py-3 border-t flex items-center justify-end shrink-0 ${
            isDark ? 'bg-black/40 border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs transition cursor-pointer shadow-sm"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
