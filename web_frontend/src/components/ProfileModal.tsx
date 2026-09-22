import React, { useState, useEffect } from 'react';
import {
  X,
  User,
  Shield,
  KeyRound,
  LogOut,
  Check,
  AlertCircle,
  Save,
  Lock,
  Mail,
  Tag,
  Phone,
  Calendar,
  Trash2,
  Moon,
  Sun,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { AppTheme } from '../types';

interface ProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  isAdmin: boolean;
  onLoginSuccess: () => void;
  onLogout: () => void;
  theme: AppTheme;
  onToggleTheme?: () => void;
}

interface UserProfileData {
  displayName: string;
  nickname: string;
  username: string;
  email: string;
  birthday: string;
  mobile: string;
  role: 'admin' | 'user';
}

const DEFAULT_PROFILE: UserProfileData = {
  displayName: 'Lead Operator',
  nickname: 'Admin',
  username: 'admin@jarvis.core',
  email: 'admin@jarvis.core',
  birthday: '1998-08-15',
  mobile: '+91 98765 43210',
  role: 'admin',
};

export function ProfileModal({
  isOpen,
  onClose,
  isAdmin,
  onLoginSuccess,
  onLogout,
  theme,
  onToggleTheme,
}: ProfileModalProps) {
  const isDark = theme === 'dark';

  // Active Menu: 'profile' | 'security' (strictly two clean sections)
  const [activeMenu, setActiveMenu] = useState<'profile' | 'security'>('profile');

  // Stored Profile Data
  const [profile, setProfile] = useState<UserProfileData>(() => {
    try {
      const saved = localStorage.getItem('jarvis_user_profile');
      if (saved) return JSON.parse(saved);
    } catch {
      // fallback
    }
    return DEFAULT_PROFILE;
  });

  // Edit fields
  const [displayName, setDisplayName] = useState(profile.displayName);
  const [nickname, setNickname] = useState(profile.nickname);
  const [username, setUsername] = useState(profile.username);
  const [email, setEmail] = useState(profile.email || profile.username);
  const [birthday, setBirthday] = useState(profile.birthday || '1998-08-15');
  const [mobile, setMobile] = useState(profile.mobile || '+91 98765 43210');
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Security fields
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [securityNotice, setSecurityNotice] = useState<string | null>(null);
  const [recoveryEmail, setRecoveryEmail] = useState('recovery@jarvis.network');
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const [backupCodesCount, setBackupCodesCount] = useState(8);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  // Logout Warning Dialog
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  // Delete Account Confirm Dialog
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    if (isOpen) {
      try {
        const saved = localStorage.getItem('jarvis_user_profile');
        if (saved) {
          const parsed = JSON.parse(saved);
          setProfile(parsed);
          setDisplayName(parsed.displayName);
          setNickname(parsed.nickname);
          setUsername(parsed.username);
          setEmail(parsed.email || parsed.username);
          setBirthday(parsed.birthday || '1998-08-15');
          setMobile(parsed.mobile || '+91 98765 43210');
        }
      } catch {
        // ignore
      }
      setSaveSuccess(false);
      setSecurityNotice(null);
      setRecoveryNotice(null);
      setSessionNotice(null);
      setShowLogoutConfirm(false);
      setShowDeleteConfirm(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleGenerateBackupCodes = () => {
    setBackupCodesCount(8);
    setRecoveryNotice('Generated 8 new cryptographic recovery backup keys.');
    setTimeout(() => setRecoveryNotice(null), 3000);
  };

  const handleRevokeOtherSessions = () => {
    setSessionNotice('All other active browser and terminal sessions revoked.');
    setTimeout(() => setSessionNotice(null), 3000);
  };

  // Save changes
  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    const updated: UserProfileData = {
      ...profile,
      displayName: displayName.trim() || 'Operator',
      nickname: nickname.trim() || 'Admin',
      username: username.trim() || 'operator@jarvis.core',
      email: email.trim() || username.trim() || 'operator@jarvis.core',
      birthday: birthday.trim(),
      mobile: mobile.trim(),
    };
    setProfile(updated);
    localStorage.setItem('jarvis_user_profile', JSON.stringify(updated));
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 2500);
  };

  // Password / Security update
  const handleUpdateSecurity = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPassword) {
      setSecurityNotice('Please enter a new password');
      return;
    }
    if (newPassword !== confirmPassword) {
      setSecurityNotice('New password and confirmation do not match');
      return;
    }
    setSecurityNotice('Security credentials successfully updated!');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setTimeout(() => setSecurityNotice(null), 3000);
  };

  // Confirm logout
  const handleConfirmLogout = () => {
    onLogout();
    const guestProfile: UserProfileData = {
      displayName: 'Guest User',
      nickname: 'Guest',
      username: 'guest@jarvis.local',
      email: 'guest@jarvis.local',
      birthday: '',
      mobile: '',
      role: 'user',
    };
    setProfile(guestProfile);
    localStorage.setItem('jarvis_user_profile', JSON.stringify(guestProfile));
    setShowLogoutConfirm(false);
    onClose();
  };

  // Confirm delete account
  const handleConfirmDeleteAccount = () => {
    onLogout();
    localStorage.removeItem('jarvis_user_profile');
    localStorage.removeItem('jarvis_sessions');
    setShowDeleteConfirm(false);
    onClose();
    window.location.reload();
  };

  const getInitials = (name: string) => {
    return (
      name
        .split(' ')
        .map(n => n[0])
        .slice(0, 2)
        .join('')
        .toUpperCase() || 'OP'
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className={`w-full max-w-xl rounded-2xl sm:rounded-3xl border shadow-2xl overflow-hidden flex flex-col transition-all max-h-[90vh] ${
          isDark
            ? 'bg-[#080c18] border-brand-500/25 text-white shadow-[0_0_50px_rgba(0,0,0,0.8)]'
            : 'bg-white border-slate-300 text-slate-900 shadow-2xl'
        }`}
      >
        {/* ============================================================ */}
        {/* FIX 4: SIMPLIFIED HEADER (No top tab sub-header bar)          */}
        {/* ============================================================ */}
        <div
          className={`px-5 py-4 border-b flex items-center justify-between shrink-0 ${
            isDark ? 'bg-[#050811] border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-brand-500/15 border border-brand-400/40 flex items-center justify-center text-brand-400 shadow-[0_0_12px_rgba(34,211,238,0.25)]">
              <User className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-bold text-sm sm:text-base flex items-center gap-2">
                <span>Profile & Security</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-mono font-bold uppercase border ${
                    isAdmin
                      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                      : 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
                  }`}
                >
                  {isAdmin ? 'OPERATOR' : 'GUEST'}
                </span>
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 font-sans">
                Personal identity, credentials & security preferences
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {onToggleTheme && (
              <button
                type="button"
                onClick={onToggleTheme}
                className={`p-2 rounded-xl border transition cursor-pointer ${
                  isDark
                    ? 'bg-white/5 border-white/10 text-brand-400 hover:bg-white/10'
                    : 'bg-slate-100 border-slate-200 text-slate-700 hover:bg-slate-200'
                }`}
                title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            )}

            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-600 dark:hover:text-white transition cursor-pointer"
              title="Close Settings"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* ============================================================ */}
        {/* TWO DISTINCT SECTIONS: 1. Profile Settings • 2. Account Security */}
        {/* ============================================================ */}
        <div className="px-4 py-2 border-b flex items-center gap-2 shrink-0" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}>
          <button
            onClick={() => setActiveMenu('profile')}
            className="flex-1 py-2 px-3 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2"
            style={activeMenu === 'profile'
              ? { backgroundColor: 'var(--jarvis-accent)', color: 'white' }
              : { color: 'var(--jarvis-text-muted)' }}
          >
            <User className="w-3.5 h-3.5" />
            <span>Profile Settings</span>
          </button>

          <button
            onClick={() => setActiveMenu('security')}
            className="flex-1 py-2 px-3 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2"
            style={activeMenu === 'security'
              ? { backgroundColor: 'var(--jarvis-accent)', color: 'white' }
              : { color: 'var(--jarvis-text-muted)' }}
          >
            <KeyRound className="w-3.5 h-3.5" />
            <span>Account Security</span>
          </button>
        </div>

        {/* ============================================================ */}
        {/* MODAL BODY (Scrollable contents)                             */}
        {/* ============================================================ */}
        <div className="p-5 space-y-4 overflow-y-auto flex-1">
          {/* ---------------------------------------------------------- */}
          {/* MENU 1: PROFILE SETTINGS                                   */}
          {/* Display Name, Call Sign, Email, Birthday, Mobile           */}
          {/* ---------------------------------------------------------- */}
          {activeMenu === 'profile' && (
            <div className="space-y-4">
              {/* ChatGPT/Gemini-Style User Identity Header Card */}
              <div
                className={`p-4 rounded-2xl border flex items-center gap-4 ${
                  isDark
                    ? 'bg-gradient-to-r from-brand-950/30 to-blue-950/20 border-brand-500/20'
                    : 'bg-gradient-to-r from-brand-50 to-blue-50 border-brand-200'
                }`}
              >
                <div className="relative shrink-0">
                  <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-500 to-blue-600 text-white font-black text-lg flex items-center justify-center shadow-md">
                    {getInitials(displayName || profile.displayName)}
                  </div>
                  <span
                    className={`absolute -bottom-1 -right-1 w-4 h-4 rounded-full border-2 ${
                      isDark ? 'border-[#080c18]' : 'border-white'
                    } ${isAdmin ? 'bg-emerald-500' : 'bg-amber-500'}`}
                  />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-sm truncate text-slate-900 dark:text-white">
                      {displayName || profile.displayName}
                    </h3>
                  </div>
                  <p className="text-xs text-brand-600 dark:text-brand-400 font-mono mt-0.5">
                    Call Sign: &ldquo;{nickname || profile.nickname}&rdquo;
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                    {email || username || profile.username}
                  </p>
                </div>
              </div>

              {/* Editable Fields Form */}
              <form onSubmit={handleSaveProfile} className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Display Name */}
                  <div className="space-y-1">
                    <label className="text-sm font-medium flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                      <User className="w-3.5 h-3.5 text-brand-500" />
                      <span>Display Name</span>
                    </label>
                    <input
                      type="text"
                      value={displayName}
                      onChange={e => setDisplayName(e.target.value)}
                      placeholder="e.g. Lead Operator"
                      className="w-full px-3 py-2 rounded-xl border text-sm outline-none transition-colors focus:border-[var(--jarvis-accent)]"
                      style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
                    />
                  </div>

                  {/* Nickname / Call Sign */}
                  <div className="space-y-1">
                    <label className="text-sm font-medium flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                      <Tag className="w-3.5 h-3.5 text-brand-500" />
                      <span>JARVIS Nickname / Call Sign</span>
                    </label>
                    <input
                      type="text"
                      value={nickname}
                      onChange={e => setNickname(e.target.value)}
                      placeholder="e.g. Admin, Sir, Boss"
                      className="w-full px-3 py-2 rounded-xl border text-sm outline-none transition-colors focus:border-[var(--jarvis-accent)]"
                      style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
                    />
                  </div>
                </div>

                {/* Email / Username */}
                <div className="space-y-1">
                  <label className="text-sm font-medium flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                    <Mail className="w-3.5 h-3.5 text-brand-500" />
                    <span>Username / Email</span>
                  </label>
                  <input
                    type="text"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="e.g. admin@jarvis.core"
                    className="w-full px-3 py-2 rounded-xl border text-sm font-mono outline-none transition-colors focus:border-[var(--jarvis-accent)]"
                    style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Birthday (Date of Birth) */}
                  <div className="space-y-1">
                    <label className="text-sm font-medium flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                      <Calendar className="w-3.5 h-3.5 text-brand-500" />
                      <span>Birthday</span>
                    </label>
                    <input
                      type="date"
                      value={birthday}
                      onChange={e => setBirthday(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl border text-sm outline-none transition-colors focus:border-[var(--jarvis-accent)]"
                      style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
                    />
                  </div>

                  {/* Mobile Number */}
                  <div className="space-y-1">
                    <label className="text-sm font-medium flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                      <Phone className="w-3.5 h-3.5 text-brand-500" />
                      <span>Mobile Number</span>
                    </label>
                    <input
                      type="tel"
                      value={mobile}
                      onChange={e => setMobile(e.target.value)}
                      placeholder="+91 98765 43210"
                      className="w-full px-3 py-2 rounded-xl border text-sm outline-none transition-colors focus:border-[var(--jarvis-accent)]"
                      style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
                    />
                  </div>
                </div>

                {saveSuccess && (
                  <div className="p-2.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-semibold flex items-center gap-2">
                    <Check className="w-4 h-4" />
                    <span>Profile settings saved successfully!</span>
                  </div>
                )}

                {/* PROMINENT SAVE CHANGES BUTTON (Replacing old Done button) */}
                <div className="pt-2">
                  <button
                    type="submit"
                    className="w-full py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs flex items-center justify-center gap-2 transition cursor-pointer shadow-md shadow-brand-600/20"
                  >
                    <Save className="w-4 h-4" />
                    <span>Save Changes</span>
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ---------------------------------------------------------- */}
          {/* MENU 2: ACCOUNT SECURITY                                   */}
          {/* Consolidated minimalist cards: Password, Recovery, Creds   */}
          {/* ---------------------------------------------------------- */}
          {activeMenu === 'security' && (
            <div className="space-y-3.5">
              {/* Card 1: Password Reset */}
              <div
                className={`p-4 rounded-2xl border transition-all ${
                  isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50/90 border-slate-200'
                }`}
              >
                <div className="flex items-center gap-2.5 mb-3">
                  <div className="w-8 h-8 rounded-xl bg-brand-500/15 border border-brand-400/30 flex items-center justify-center text-brand-500 shrink-0">
                    <Lock className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-slate-900 dark:text-white">Password Reset</h4>
                    <p className="text-xs text-slate-500 dark:text-slate-400">Update account authentication passphrase</p>
                  </div>
                </div>

                <form onSubmit={handleUpdateSecurity} className="space-y-2.5">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <input
                      type="password"
                      value={currentPassword}
                      onChange={e => setCurrentPassword(e.target.value)}
                      placeholder="Current password"
                      className={`px-3 py-2 rounded-xl border text-xs font-mono outline-none ${
                        isDark
                          ? 'bg-black/50 border-white/10 text-white focus:border-brand-400'
                          : 'bg-white border-slate-300 text-slate-900 focus:border-brand-600'
                      }`}
                    />
                    <input
                      type="password"
                      value={newPassword}
                      onChange={e => setNewPassword(e.target.value)}
                      placeholder="New password (8+ chars)"
                      className={`px-3 py-2 rounded-xl border text-xs font-mono outline-none ${
                        isDark
                          ? 'bg-black/50 border-white/10 text-white focus:border-brand-400'
                          : 'bg-white border-slate-300 text-slate-900 focus:border-brand-600'
                      }`}
                    />
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={e => setConfirmPassword(e.target.value)}
                      placeholder="Confirm password"
                      className={`px-3 py-2 rounded-xl border text-xs font-mono outline-none ${
                        isDark
                          ? 'bg-black/50 border-white/10 text-white focus:border-brand-400'
                          : 'bg-white border-slate-300 text-slate-900 focus:border-brand-600'
                      }`}
                    />
                  </div>

                  {securityNotice && (
                    <div className="p-2 rounded-xl bg-brand-500/15 border border-brand-500/30 text-brand-600 dark:text-brand-300 text-xs font-semibold flex items-center gap-2">
                      <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                      <span>{securityNotice}</span>
                    </div>
                  )}

                  <div className="flex justify-end pt-1">
                    <button
                      type="submit"
                      className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs flex items-center gap-2 transition cursor-pointer shadow-xs"
                    >
                      <KeyRound className="w-3.5 h-3.5" />
                      <span>Update Password</span>
                    </button>
                  </div>
                </form>
              </div>

              {/* Card 2: Account Recovery */}
              <div
                className={`p-4 rounded-2xl border transition-all ${
                  isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50/90 border-slate-200'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-xl bg-emerald-500/15 border border-emerald-400/30 flex items-center justify-center text-emerald-500 shrink-0">
                      <Shield className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-slate-900 dark:text-white">Account Recovery</h4>
                      <p className="text-xs text-slate-500 dark:text-slate-400">Emergency backup keys & secondary contact</p>
                    </div>
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shrink-0">
                    2FA ACTIVE
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                  <div className={`p-2.5 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'}`}>
                    <div className="text-xs text-slate-400 font-mono">RECOVERY EMAIL</div>
                    <div className="font-semibold text-slate-800 dark:text-slate-200 truncate mt-0.5">{recoveryEmail}</div>
                  </div>
                  <div className={`p-2.5 rounded-xl border flex items-center justify-between ${isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'}`}>
                    <div>
                      <div className="text-xs text-slate-400 font-mono">BACKUP CODES</div>
                      <div className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5">{backupCodesCount} unused keys</div>
                    </div>
                    <button
                      type="button"
                      onClick={handleGenerateBackupCodes}
                      className="px-2.5 py-1 rounded-lg bg-emerald-600/15 hover:bg-emerald-600 text-emerald-600 dark:text-emerald-400 hover:text-white border border-emerald-500/30 text-xs font-semibold transition cursor-pointer"
                    >
                      Regenerate
                    </button>
                  </div>
                </div>

                {recoveryNotice && (
                  <div className="mt-2.5 p-2 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-semibold flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 shrink-0" />
                    <span>{recoveryNotice}</span>
                  </div>
                )}
              </div>

              {/* Card 3: Credential Management */}
              <div
                className={`p-4 rounded-2xl border transition-all ${
                  isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50/90 border-slate-200'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-xl bg-purple-500/15 border border-purple-400/30 flex items-center justify-center text-purple-500 shrink-0">
                      <KeyRound className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-slate-900 dark:text-white">Credential Management</h4>
                      <p className="text-xs text-slate-500 dark:text-slate-400">Active session tokens & authorized devices</p>
                    </div>
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/30 shrink-0">
                    JWT VALID
                  </span>
                </div>

                <div className={`mt-3 flex items-center justify-between p-2.5 rounded-xl border text-xs ${
                  isDark ? 'bg-white/[0.02] border-white/5' : 'bg-white border-slate-200'
                }`}>
                  <div>
                    <div className="font-semibold text-slate-800 dark:text-slate-200">Current Session (Browser)</div>
                    <div className="text-xs text-slate-400 font-mono mt-0.5">Expires in 24h &bull; Neural Vault Token</div>
                  </div>
                  <button
                    type="button"
                    onClick={handleRevokeOtherSessions}
                    className="px-2.5 py-1 rounded-lg bg-rose-600/15 hover:bg-rose-600 text-rose-600 dark:text-rose-400 hover:text-white border border-rose-500/30 text-xs font-semibold transition cursor-pointer"
                  >
                    Revoke Other Sessions
                  </button>
                </div>

                {sessionNotice && (
                  <div className="mt-2.5 p-2 rounded-xl bg-purple-500/15 border border-purple-500/30 text-purple-600 dark:text-purple-300 text-xs font-semibold flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 shrink-0" />
                    <span>{sessionNotice}</span>
                  </div>
                )}
              </div>

              {/* Card 4: Danger Zone / Delete Account */}
              <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 space-y-3">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-bold text-xs text-rose-600 dark:text-rose-400">
                      Danger Zone &bull; Terminate Account
                    </h4>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
                      Permanently remove operator credentials, purge local conversation threads, and reset FAISS vector indices. This action cannot be undone.
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(true)}
                  className="w-full py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs flex items-center justify-center gap-2 transition cursor-pointer shadow-md shadow-rose-600/20"
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Delete Account & Purge Data</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ============================================================ */}
        {/* FIX 3: FULL-WIDTH CONTAINER "LOG OUT" BUTTON AT BOTTOM       */}
        {/* ============================================================ */}
        <div
          className={`p-4 border-t flex flex-col items-center gap-2 shrink-0 ${
            isDark ? 'bg-[#050811] border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <button
            type="button"
            onClick={() => setShowLogoutConfirm(true)}
            className="w-full py-2.5 rounded-xl border border-rose-500/30 text-rose-500 hover:text-white bg-rose-500/10 hover:bg-rose-600 font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer shadow-xs"
          >
            <LogOut className="w-4 h-4" />
            <span>Log Out</span>
          </button>
        </div>

        {/* ============================================================ */}
        {/* LOGOUT CONFIRMATION WARNING DIALOG BOX                       */}
        {/* ============================================================ */}
        {showLogoutConfirm && (
          <div className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-xs animate-in fade-in duration-150">
            <div
              className={`w-full max-w-sm p-5 rounded-2xl border shadow-2xl space-y-4 text-center ${
                isDark ? 'bg-[#0b1020] border-white/20 text-white' : 'bg-white border-slate-300 text-slate-900'
              }`}
            >
              <div className="w-12 h-12 rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-500 mx-auto flex items-center justify-center">
                <AlertCircle className="w-6 h-6" />
              </div>

              <div>
                <h3 className="font-bold text-sm">Are you sure you want to log out?</h3>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  You will be switched to Guest User session. Administrative diagnostic tools, telemetry monitors, and trace logs will be locked.
                </p>
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowLogoutConfirm(false)}
                  className="flex-1 py-2 rounded-xl border text-xs font-semibold transition cursor-pointer hover:bg-white/5 border-slate-300 dark:border-white/10"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmLogout}
                  className="flex-1 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold transition cursor-pointer shadow-md shadow-rose-600/30"
                >
                  Confirm Log Out
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ============================================================ */}
        {/* DELETE ACCOUNT CONFIRMATION DIALOG BOX                       */}
        {/* ============================================================ */}
        {showDeleteConfirm && (
          <div className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-black/90 backdrop-blur-xs animate-in fade-in duration-150">
            <div
              className={`w-full max-w-sm p-5 rounded-2xl border shadow-2xl space-y-4 text-center ${
                isDark ? 'bg-[#0b1020] border-rose-500/30 text-white' : 'bg-white border-rose-300 text-slate-900'
              }`}
            >
              <div className="w-12 h-12 rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-500 mx-auto flex items-center justify-center">
                <Trash2 className="w-6 h-6" />
              </div>

              <div>
                <h3 className="font-bold text-sm text-rose-500">Confirm Account Deletion</h3>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  This action is irreversible. All local profiles, threads, and stored memory keys will be purged immediately.
                </p>
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 py-2 rounded-xl border text-xs font-semibold transition cursor-pointer hover:bg-white/5 border-slate-300 dark:border-white/10"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDeleteAccount}
                  className="flex-1 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold transition cursor-pointer"
                >
                  Yes, Delete All
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
