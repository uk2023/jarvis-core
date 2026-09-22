import React, { useState } from 'react';
import { Lock, User as UserIcon, ArrowRight, X, AlertCircle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { AppTheme } from '../types';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  theme: AppTheme;
}

// PROFESSIONAL REDESIGN (2026-09-12, UK's explicit ask): the previous
// version simulated fingerprint/Face-ID scanning, a fake Google
// 1-click login, and a fake OTP flow ("8492" hardcoded client-side) --
// none of it verified anything on the backend. This is real signup
// and login only, backed by backend/routes_auth.py. Account creation
// always produces a 'user' role; becoming admin is a separate request
// that sits pending until the owner approves it from the CLI/monitor
// (see core/identity/user_store.py's approve_admin) -- there is no
// UI path here that can grant elevated access to itself.
export function AuthModal({ isOpen, onClose, onSuccess, theme }: AuthModalProps) {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!isOpen) return null;
  const isDark = theme === 'dark';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // The 3-character minimum is a SIGNUP rule -- it stops throwaway
    // one-letter accounts. Applying it to login locked the owner out of
    // his own system, because the owner account is 'uk'. An existing
    // account's name is not the login form's business.
    if (mode === 'signup' && username.trim().length < 3) {
      setError('Username must be at least 3 characters.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setIsSubmitting(true);
    try {
      const result = mode === 'signup'
        ? await api.signup(username.trim(), password, displayName.trim() || undefined)
        : await api.login(username.trim(), password);
      setSuccessMessage(mode === 'signup' ? `Account created. Welcome, ${result.display_name}.` : `Welcome back, ${result.display_name}.`);
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 500);
    } catch (err: any) {
      setError(err?.message || 'Something went wrong. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div
        className={`w-full max-w-sm rounded-2xl border shadow-2xl p-6 space-y-4 relative ${
          isDark ? 'bg-slate-900 border-white/10' : 'bg-white border-slate-200'
        }`}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-700 dark:hover:text-white transition cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-brand-500" />
          <h2 className="text-base font-bold text-slate-900 dark:text-white">
            {mode === 'login' ? 'Sign in to JARVIS' : 'Create your account'}
          </h2>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-xl border border-slate-200 dark:border-white/10 p-1 text-xs font-semibold">
          <button
            type="button"
            onClick={() => { setMode('login'); setError(null); }}
            className={`flex-1 py-1.5 rounded-lg transition cursor-pointer ${
              mode === 'login' ? 'bg-brand-600 text-white' : 'text-slate-500 hover:text-slate-800 dark:hover:text-white'
            }`}
          >
            Log in
          </button>
          <button
            type="button"
            onClick={() => { setMode('signup'); setError(null); }}
            className={`flex-1 py-1.5 rounded-lg transition cursor-pointer ${
              mode === 'signup' ? 'bg-brand-600 text-white' : 'text-slate-500 hover:text-slate-800 dark:hover:text-white'
            }`}
          >
            Sign up
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-2 p-2.5 rounded-xl text-xs bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {successMessage && (
          <div className="flex items-start gap-2 p-2.5 rounded-xl text-xs bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{successMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === 'signup' && (
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400">Display name (optional)</label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="How JARVIS should address you"
                className={`w-full px-3 py-2 rounded-xl border text-sm outline-none transition ${
                  isDark ? 'bg-black/40 border-white/10 focus:border-brand-400 text-white placeholder:text-slate-600'
                         : 'bg-slate-50 border-slate-300 focus:border-brand-600 text-slate-900 placeholder:text-slate-400'
                }`}
              />
            </div>
          )}

          <div className="space-y-1">
            <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400">Username</label>
            <div className="relative">
              <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
                className={`w-full pl-9 pr-3 py-2 rounded-xl border text-sm outline-none transition ${
                  isDark ? 'bg-black/40 border-white/10 focus:border-brand-400 text-white placeholder:text-slate-600'
                         : 'bg-slate-50 border-slate-300 focus:border-brand-600 text-slate-900 placeholder:text-slate-400'
                }`}
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={mode === 'signup' ? 'At least 8 characters' : ''}
                className={`w-full pl-9 pr-3 py-2 rounded-xl border text-sm outline-none transition ${
                  isDark ? 'bg-black/40 border-white/10 focus:border-brand-400 text-white placeholder:text-slate-600'
                         : 'bg-slate-50 border-slate-300 focus:border-brand-600 text-slate-900 placeholder:text-slate-400'
                }`}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-semibold text-sm flex items-center justify-center gap-1.5 shadow-md shadow-brand-600/20 transition cursor-pointer disabled:opacity-60"
          >
            <span>{isSubmitting ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Create account'}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </form>

        <p className="text-xs text-center text-slate-500 dark:text-slate-400">
          New accounts start with standard access. Admin access can be requested after signing in and requires
          the owner's approval.
        </p>

        <div className="text-center pt-2 border-t border-slate-200 dark:border-white/10">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white transition cursor-pointer"
          >
            Continue browsing as guest &rarr;
          </button>
        </div>
      </div>
    </div>
  );
}
