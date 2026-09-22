import React, { useState } from 'react';
import {
  X,
  User,
  Shield,
  KeyRound,
  LogOut,
  Sun,
  Moon,
  Volume2,
  VolumeX,
  Activity,
  Check,
  Sparkles,
  Terminal,
  Cpu,
  RefreshCw,
  Sliders,
  Server,
  Mic,
} from 'lucide-react';
import { AppTheme } from '../types';
import { api } from '../api/client';
import { VoiceControlPanel } from './VoiceControlPanel';

interface ProfileSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  isAdmin: boolean;
  onLoginSuccess: () => void;
  onLogout: () => void;
  theme: AppTheme;
  onToggleTheme: () => void;
  onNavigateToView?: (view: 'dashboard' | 'cli' | 'inspector' | 'user_chat') => void;
}

export function ProfileSettingsModal({
  isOpen,
  onClose,
  isAdmin,
  onLoginSuccess,
  onLogout,
  theme,
  onToggleTheme,
  onNavigateToView,
}: ProfileSettingsModalProps) {
  const [requestingAdmin, setRequestingAdmin] = useState(false);
  const [requestAdminMessage, setRequestAdminMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [pollInterval, setPollInterval] = useState('2s');
  const [backendUrl, setBackendUrlInput] = useState(() => api.getBackendUrl());
  const [activeTab, setActiveTab] = useState<'general' | 'voice'>('general');
  const [testStatus, setTestStatus] = useState<{ testing: boolean; message: string | null; ok?: boolean }>({
    testing: false,
    message: null,
  });

  const handleSaveBackendUrl = () => {
    api.setBackendUrl(backendUrl);
    setTestStatus({ testing: false, message: 'URL saved to local settings.', ok: true });
    setTimeout(() => setTestStatus({ testing: false, message: null }), 3500);
  };

  const handleTestBackendConnection = async () => {
    setTestStatus({ testing: true, message: 'Testing /api/health endpoint...' });
    api.setBackendUrl(backendUrl);
    const result = await api.testConnection();
    setTestStatus({ testing: false, message: result.message, ok: result.ok });
  };

  if (!isOpen) return null;

  const isDark = theme === 'dark';

  const handleRequestAdmin = async () => {
    setError(null);
    setRequestingAdmin(true);
    try {
      const result = await api.requestAdmin();
      setRequestAdminMessage(result.message || 'Request sent -- the owner must approve it.');
    } catch (err: any) {
      setError(err?.message || 'Could not send the request. Are you signed in?');
    } finally {
      setRequestingAdmin(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-150">
      <div
        className={`w-full max-w-md rounded-2xl border shadow-2xl overflow-hidden transition-all ${
          isDark
            ? 'bg-[#0a0d16] border-white/10 text-white shadow-black/80'
            : 'bg-white border-slate-200 text-slate-900 shadow-xl'
        }`}
      >
        {/* Header */}
        <div
          className={`px-5 py-4 border-b flex items-center justify-between ${
            isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-brand-500/15 border border-brand-400/40 flex items-center justify-center text-brand-400">
              <Sliders className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-sm">Profile & System Settings</h3>
              <p className="text-xs text-slate-400">JARVIS Organism Configuration</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className={`flex border-b text-xs font-mono px-5 pt-2 gap-2 ${isDark ? 'border-white/10 bg-black/20' : 'border-slate-200 bg-slate-50'}`}>
          <button
            onClick={() => setActiveTab('general')}
            className={`pb-2 px-3 border-b-2 font-semibold transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'general'
                ? 'border-brand-400 text-brand-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>General & Profile</span>
          </button>

          <button
            onClick={() => setActiveTab('voice')}
            className={`pb-2 px-3 border-b-2 font-semibold transition cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'voice'
                ? 'border-brand-400 text-brand-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Mic className="w-3.5 h-3.5" />
            <span>Voice Control (TTS/STT)</span>
          </button>
        </div>

        <div className="p-5 space-y-5 max-h-[80vh] overflow-y-auto">
          {activeTab === 'voice' ? (
            <VoiceControlPanel theme={theme} onClose={onClose} />
          ) : (
            <>
          {/* User Profile Card */}
          <div
            className={`p-3.5 rounded-xl border flex items-center gap-3.5 ${
              isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
            }`}
          >
            {/* Avatar Circle */}
            <div className="relative">
              <div
                className={`w-12 h-12 rounded-full border-2 flex items-center justify-center font-bold text-sm select-none ${
                  isAdmin
                    ? 'bg-brand-500/20 border-brand-400 text-brand-300 shadow-[0_0_12px_rgba(34,211,238,0.3)]'
                    : 'bg-slate-200 dark:bg-slate-800 border-slate-300 dark:border-white/20 text-slate-600 dark:text-slate-300'
                }`}
              >
                {isAdmin ? 'AD' : 'GU'}
              </div>
              <span
                className={`absolute bottom-0 right-0 w-3.5 h-3.5 rounded-full border-2 border-[#0a0d16] ${
                  isAdmin ? 'bg-emerald-500' : 'bg-amber-500'
                }`}
              />
            </div>

            {/* Profile Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm truncate">
                  {isAdmin ? 'Admin' : 'Guest User'}
                </span>
                <span
                  className={`text-xs font-mono px-2 py-0.2 rounded-full font-bold uppercase tracking-wider ${
                    isAdmin
                      ? 'bg-brand-500/15 text-brand-400 border border-brand-500/30'
                      : 'bg-amber-500/15 text-amber-500 border border-amber-500/30'
                  }`}
                >
                  {isAdmin ? 'ADMIN' : 'GUEST'}
                </span>
              </div>
              <p className="text-xs text-slate-400 truncate mt-0.5">
                {isAdmin ? 'ujjwal.rob11@gmail.com' : 'Public Sandbox Session'}
              </p>
              <div className="text-xs text-slate-500 font-mono mt-0.5">
                {isAdmin
                  ? 'Active: Dashboard, CLI, Trace Inspector'
                  : 'Chat Only Mode • Sign in as Admin for telemetry'}
              </div>
            </div>
          </div>

          {/* Role Switching & Access Section */}
          <div className="space-y-2">
            <span className="text-xs uppercase font-bold tracking-wider text-slate-400 font-mono block">
              Access Control & Permissions
            </span>

            {isAdmin ? (
              <div
                className={`p-3 rounded-xl border space-y-2.5 ${
                  isDark
                    ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300'
                    : 'bg-emerald-50 border-emerald-200 text-emerald-800'
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold flex items-center gap-1.5">
                    <Shield className="w-4 h-4 text-emerald-400" />
                    <span>Admin Mode Active</span>
                  </span>
                  <span className="text-xs font-mono opacity-80">Full Privileges</span>
                </div>
                <p className="text-xs opacity-90 leading-relaxed">
                  You have full access to the Systems Monitoring Dashboard, Virtual CLI terminal, and per-turn Trace Inspector.
                </p>

                <button
                  onClick={() => {
                    onLogout();
                    onClose();
                  }}
                  className="w-full py-2 px-3 rounded-lg border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 text-xs font-semibold flex items-center justify-center gap-2 transition cursor-pointer"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Sign out to Guest Mode</span>
                </button>
              </div>
            ) : (
              <div
                className={`p-3.5 rounded-xl border space-y-3 ${
                  isDark
                    ? 'bg-brand-950/20 border-brand-500/30'
                    : 'bg-brand-50 border-brand-200'
                }`}
              >
                <div>
                  <div className="text-xs font-bold text-brand-600 dark:text-brand-300 flex items-center gap-1.5">
                    <Shield className="w-4 h-4" />
                    <span>Admin Access</span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
                    Admin access to the monitor.py dashboard, CLI terminal, and trace inspector requires the
                    owner's approval. Sign in first, then request access below.
                  </p>
                </div>

                <button
                  onClick={handleRequestAdmin}
                  disabled={requestingAdmin}
                  className="w-full py-2 px-3 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold flex items-center justify-center gap-1.5 shadow-md shadow-brand-600/30 transition cursor-pointer disabled:opacity-60"
                >
                  <Shield className="w-3.5 h-3.5" />
                  <span>{requestingAdmin ? 'Sending request...' : 'Request Admin Access'}</span>
                </button>
                {requestAdminMessage && <p className="text-xs text-emerald-500">{requestAdminMessage}</p>}
                {error && <p className="text-xs text-rose-400">{error}</p>}
              </div>
            )}
          </div>

          {/* Settings Options */}
          <div className="space-y-3">
            <span className="text-xs uppercase font-bold tracking-wider text-slate-400 font-mono block">
              Preferences & Environment
            </span>

            {/* Backend API Endpoint (Custom Backend Integration) */}
            <div
              className={`p-3.5 rounded-xl border space-y-2.5 ${
                isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Server className="w-4 h-4 text-brand-500" />
                  <div>
                    <span className="text-xs font-semibold block text-slate-800 dark:text-slate-100">
                      Backend API Endpoint
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                      Connect to external JARVIS engine
                    </span>
                  </div>
                </div>
                {backendUrl && (
                  <button
                    onClick={() => {
                      setBackendUrlInput('');
                      api.setBackendUrl('');
                      setTestStatus({ testing: false, message: 'Reverted to local/default container.', ok: true });
                    }}
                    className="text-xs text-slate-500 hover:text-rose-500 font-mono transition cursor-pointer"
                    title="Reset to default"
                  >
                    Reset Default
                  </button>
                )}
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Default: Local container (/api/*)"
                  value={backendUrl}
                  onChange={e => setBackendUrlInput(e.target.value)}
                  className={`flex-1 px-2.5 py-1.5 rounded-lg border text-xs font-mono outline-none ${
                    isDark
                      ? 'bg-black/40 border-white/15 text-white placeholder:text-slate-500'
                      : 'bg-white border-slate-300 text-slate-900 placeholder:text-slate-400'
                  }`}
                />
                <button
                  onClick={handleSaveBackendUrl}
                  className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-medium cursor-pointer"
                >
                  Save
                </button>
                <button
                  onClick={handleTestBackendConnection}
                  disabled={testStatus.testing}
                  className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition cursor-pointer flex items-center gap-1 ${
                    isDark
                      ? 'border-white/15 hover:bg-white/10 text-brand-300'
                      : 'border-slate-300 hover:bg-slate-100 text-slate-700'
                  }`}
                >
                  {testStatus.testing ? <RefreshCw className="w-3 h-3 animate-spin" /> : null}
                  <span>Test</span>
                </button>
              </div>

              {testStatus.message && (
                <div
                  className={`text-xs font-mono px-2.5 py-1 rounded-md border flex items-center gap-1.5 ${
                    testStatus.ok
                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'
                      : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20'
                  }`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-current" />
                  <span>{testStatus.message}</span>
                </div>
              )}
            </div>

            {/* Theme Toggle */}
            <div
              className={`p-3 rounded-xl border flex items-center justify-between ${
                isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="flex items-center gap-2.5">
                {isDark ? (
                  <Moon className="w-4 h-4 text-brand-400" />
                ) : (
                  <Sun className="w-4 h-4 text-amber-500" />
                )}
                <div>
                  <span className="text-xs font-semibold block">Interface Theme</span>
                  <span className="text-xs text-slate-400 font-mono">
                    Currently in {isDark ? 'Night Mode' : 'Day Mode'}
                  </span>
                </div>
              </div>

              <button
                onClick={onToggleTheme}
                className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition cursor-pointer ${
                  isDark
                    ? 'border-white/15 hover:bg-white/10 text-amber-300'
                    : 'border-slate-300 hover:bg-slate-100 text-slate-800'
                }`}
              >
                Switch to {isDark ? 'Day' : 'Night'}
              </button>
            </div>

            {/* Sound & Speech Effects */}
            <div
              className={`p-3 rounded-xl border flex items-center justify-between ${
                isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="flex items-center gap-2.5">
                {soundEnabled ? (
                  <Volume2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <VolumeX className="w-4 h-4 text-slate-400" />
                )}
                <div>
                  <span className="text-xs font-semibold block">Text-to-Speech & Sounds</span>
                  <span className="text-xs text-slate-400 font-mono">Speech synthesis & tones</span>
                </div>
              </div>

              <button
                onClick={() => setSoundEnabled(!soundEnabled)}
                className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition cursor-pointer ${
                  soundEnabled
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-500'
                    : 'border-slate-300 dark:border-white/10 text-slate-400'
                }`}
              >
                {soundEnabled ? 'Enabled' : 'Muted'}
              </button>
            </div>

            {/* Telemetry Polling Rate */}
            <div
              className={`p-3 rounded-xl border flex items-center justify-between ${
                isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <Activity className="w-4 h-4 text-brand-400" />
                <div>
                  <span className="text-xs font-semibold block">Telemetry Poll Interval</span>
                  <span className="text-xs text-slate-400 font-mono">Live state refresh rate</span>
                </div>
              </div>

              <div className="flex gap-1 text-xs font-mono">
                {['1s', '2s', '5s'].map(rate => (
                  <button
                    key={rate}
                    onClick={() => setPollInterval(rate)}
                    className={`px-2 py-1 rounded-md border text-xs font-semibold transition cursor-pointer ${
                      pollInterval === rate
                        ? 'bg-brand-600 text-white border-brand-600'
                        : isDark
                        ? 'border-white/10 text-slate-400 hover:text-white'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {rate}
                  </button>
                ))}
              </div>
            </div>
          </div>
          </>
          )}
        </div>

        {/* Footer */}
        <div
          className={`px-5 py-3 border-t flex items-center justify-between text-xs font-mono ${
            isDark ? 'bg-black/40 border-white/10 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-500'
          }`}
        >
          <span>JARVIS Organism Console v2026.4</span>
          <button
            onClick={onClose}
            className="px-3 py-1 rounded-lg bg-slate-800 dark:bg-white/10 hover:bg-slate-700 text-white font-medium cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
