import React, { useState, useRef, useEffect } from 'react';
import {
  Plus,
  MessageSquare,
  Pin,
  PinOff,
  MoreVertical,
  Trash2,
  Edit2,
  Check,
  X,
  Radio,
  Search,
  Shield,
  User,
  LogIn,
  Settings,
  PanelLeftClose,
  PanelLeft,
  ChevronDown,
  ChevronRight,
  Clock,
} from 'lucide-react';
import { AppTheme, SessionItem } from '../types';
import ProfileDropdown from './ProfileDropdown';

interface ChatThreadsSidebarProps {
  theme: AppTheme;
  isOpen: boolean;
  onClose: () => void;
  sessions: SessionItem[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, newTitle: string) => void;
  onTogglePinSession: (id: string) => void;
  onToggleTheme?: () => void;
  beatCount: number;
  isAdmin: boolean;
  /** Real role string, read from the session -- owner/co_owner/admin/user/guest.
   *  isAdmin above stays for legacy call sites; role is the source of truth
   *  for the profile dropdown, which needs to tell all five apart. */
  role?: string;
  displayName?: string | null;
  onOpenProfileSettings: () => void;
  onOpenSettings?: () => void;
  onGoHome?: () => void;
  currentView?: string;
  onNavigateToView?: (view: 'user_chat' | 'dashboard' | 'cli' | 'inspector') => void;
  /** Separate from onNavigateToView because CodeBox is its own screen
   *  (currentView === 'codebox' in App.tsx), not one of the four the
   *  older nav type already enumerates. */
  onNavigateToCodebox?: () => void;
  onOpenAuth?: () => void;
  onLogout?: () => void;
}

export function ChatThreadsSidebar({
  theme,
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onRenameSession,
  onTogglePinSession,
  onToggleTheme,
  beatCount,
  isAdmin,
  role,
  displayName,
  onOpenProfileSettings,
  onOpenSettings,
  onGoHome,
  currentView = 'user_chat',
  onNavigateToView,
  onNavigateToCodebox,
  onOpenAuth,
  onLogout,
}: ChatThreadsSidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [menuOpenSessionId, setMenuOpenSessionId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  // Collapsible section states
  const [pinnedOpen, setPinnedOpen] = useState(true);
  const [recentOpen, setRecentOpen] = useState(true);
  const [olderOpen, setOlderOpen] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  const isDark = theme === 'dark';

  // Focus input when editing begins
  useEffect(() => {
    if (editingSessionId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingSessionId]);

  // Click outside to close three-dots menu
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenSessionId(null);
      }
    }
    if (menuOpenSessionId) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpenSessionId]);

  const handleStartRename = (session: SessionItem, e: React.MouseEvent) => {
    e.stopPropagation();
    setMenuOpenSessionId(null);
    setEditingSessionId(session.sessionId);
    setEditTitle(session.title);
  };

  const handleSaveRename = (sessionId: string, e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (editTitle.trim()) {
      onRenameSession(sessionId, editTitle.trim());
    }
    setEditingSessionId(null);
  };

  const filteredSessions = sessions.filter(s =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Grouping: Pinned, Recent (last 7 days), and Older
  const pinnedSessions = filteredSessions.filter(s => s.pinned);
  const unpinnedSessions = filteredSessions.filter(s => !s.pinned);

  const recentSessions = unpinnedSessions.filter(
    s => s.category === 'Today' || s.category === 'Yesterday' || s.category === 'Previous 7 Days'
  );
  const olderSessions = unpinnedSessions.filter(
    s => s.category !== 'Today' && s.category !== 'Yesterday' && s.category !== 'Previous 7 Days'
  );

  const renderSessionItem = (session: SessionItem) => {
    const isActive = session.sessionId === activeSessionId;
    const isEditing = editingSessionId === session.sessionId;
    const isMenuOpen = menuOpenSessionId === session.sessionId;

    return (
      <div
        key={session.sessionId}
        className={`group relative rounded-xl px-2.5 py-1.5 flex items-center gap-2 transition cursor-pointer text-xs select-none ${
          isActive
            ? isDark
              ? 'bg-brand-500/15 border border-brand-400/40 text-brand-200 font-semibold'
              : 'bg-brand-50 border border-brand-400 text-brand-900 font-semibold shadow-2xs'
            : isDark
            ? 'hover:bg-white/5 text-slate-300 hover:text-white border border-transparent'
            : 'hover:bg-slate-100 text-slate-700 hover:text-slate-950 border border-transparent'
        }`}
        onClick={() => {
          if (!isEditing) {
            onSelectSession(session.sessionId);
            onClose(); // close on mobile
          }
        }}
      >
        <MessageSquare
          className={`w-3.5 h-3.5 shrink-0 transition-colors ${
            isActive
              ? 'text-brand-500'
              : isDark
              ? 'text-slate-500 group-hover:text-slate-300'
              : 'text-slate-400 group-hover:text-slate-600'
          }`}
        />

        {/* Title or Inline Edit Input */}
        {isEditing ? (
          <form
            onSubmit={e => handleSaveRename(session.sessionId, e)}
            className="flex-1 flex items-center gap-1 min-w-0"
            onClick={e => e.stopPropagation()}
          >
            <input
              ref={editInputRef}
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              className={`w-full text-xs px-1.5 py-0.5 rounded border outline-none ${
                isDark
                  ? 'bg-black/60 border-brand-400 text-white'
                  : 'bg-white border-brand-600 text-slate-900'
              }`}
            />
            <button
              type="submit"
              className="p-1 text-emerald-500 hover:text-emerald-400 cursor-pointer"
              title="Save"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setEditingSessionId(null)}
              className="p-1 text-slate-400 hover:text-slate-200 cursor-pointer"
              title="Cancel"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </form>
        ) : (
          <div className="flex-1 min-w-0 flex items-center justify-between gap-1">
            <span className="truncate leading-tight">{session.title}</span>
            {session.pinned && (
              <Pin className="w-2.5 h-2.5 text-brand-500 dark:text-brand-400 shrink-0 opacity-80" />
            )}
          </div>
        )}

        {/* Three dots action trigger */}
        {!isEditing && (
          <div className="relative">
            <button
              type="button"
              onClick={e => {
                e.stopPropagation();
                setMenuOpenSessionId(isMenuOpen ? null : session.sessionId);
              }}
              className={`p-1 rounded-md transition cursor-pointer ${
                isMenuOpen
                  ? 'opacity-100 bg-white/10 text-brand-400'
                  : 'opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-white/10'
              }`}
              title="Chat options"
            >
              <MoreVertical className="w-3 h-3" />
            </button>

            {/* Contextual Options Menu */}
            {isMenuOpen && (
              <div
                ref={menuRef}
                className={`absolute right-0 top-6 w-36 rounded-xl border shadow-xl z-50 py-1 space-y-0.5 text-xs animate-in fade-in duration-100 ${
                  isDark
                    ? 'bg-[#0f1422] border-white/15 text-slate-200 shadow-black/80'
                    : 'bg-white border-slate-200 text-slate-800 shadow-slate-300/50'
                }`}
                onClick={e => e.stopPropagation()}
              >
                {/* Pin / Unpin */}
                <button
                  onClick={e => {
                    e.stopPropagation();
                    onTogglePinSession(session.sessionId);
                    setMenuOpenSessionId(null);
                  }}
                  className={`w-full px-2.5 py-1.5 flex items-center gap-2 text-left transition cursor-pointer ${
                    isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'
                  }`}
                >
                  {session.pinned ? (
                    <>
                      <PinOff className="w-3.5 h-3.5 text-slate-400" />
                      <span>Unpin</span>
                    </>
                  ) : (
                    <>
                      <Pin className="w-3.5 h-3.5 text-brand-400" />
                      <span>Pin chat</span>
                    </>
                  )}
                </button>

                {/* Rename */}
                <button
                  onClick={e => handleStartRename(session, e)}
                  className={`w-full px-2.5 py-1.5 flex items-center gap-2 text-left transition cursor-pointer ${
                    isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'
                  }`}
                >
                  <Edit2 className="w-3.5 h-3.5 text-slate-400" />
                  <span>Rename</span>
                </button>

                {/* Delete */}
                <button
                  onClick={e => {
                    e.stopPropagation();
                    onDeleteSession(session.sessionId);
                    setMenuOpenSessionId(null);
                  }}
                  className={`w-full px-2.5 py-1.5 flex items-center gap-2 text-left text-rose-500 transition cursor-pointer ${
                    isDark ? 'hover:bg-rose-500/15' : 'hover:bg-rose-50'
                  }`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Delete</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/60 backdrop-blur-xs z-30 md:hidden"
        />
      )}

      {/* Main Sidebar Drawer */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 border-r transition-all duration-200 flex flex-col justify-between md:static md:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        } ${isCollapsed ? 'md:w-16' : 'w-64'} ${
          isDark
            ? 'bg-[#080b14] border-white/10 text-slate-200'
            : 'bg-white border-slate-200 text-slate-800 shadow-[2px_0_12px_rgba(0,0,0,0.03)]'
        }`}
      >
        {/* Top Header */}
        <div className="p-3 border-b border-slate-200 dark:border-white/10 space-y-2.5">
          {/* Top Brand Bar */}
          <div className="flex items-center justify-between">
            <button
              onClick={() => {
                if (onGoHome) onGoHome();
                onClose();
              }}
              className="flex items-center gap-2 text-left cursor-pointer group select-none min-w-0"
              title="Return to Home"
            >
              <div className="w-7 h-7 rounded-xl bg-brand-500/15 border border-brand-400/40 flex items-center justify-center group-hover:scale-105 transition-transform shrink-0">
                <span className="w-2 h-2 rounded-full bg-brand-400 animate-pulse" />
              </div>
              {!isCollapsed && (
                <span className="font-extrabold text-xs tracking-wider uppercase text-slate-900 dark:text-brand-400 group-hover:text-brand-600 dark:group-hover:text-brand-300 transition-colors truncate">
                  JARVIS
                </span>
              )}
            </button>

            {/* Desktop Collapse / Expand Toggle Button (Gemini Style) */}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="hidden md:flex p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition cursor-pointer"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <PanelLeft className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
            </button>

            {/* Mobile Close Button */}
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 md:hidden text-slate-400 cursor-pointer"
              title="Close sidebar"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* New Chat Button */}
          {isCollapsed ? (
            <button
              onClick={() => {
                onNewChat();
                onClose();
              }}
              className="w-10 h-10 mx-auto rounded-xl bg-brand-600 hover:bg-brand-500 text-white flex items-center justify-center transition cursor-pointer shadow-xs"
              title="New Chat"
            >
              <Plus className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={() => {
                onNewChat();
                onClose();
              }}
              className="w-full py-2 px-3 rounded-xl bg-brand-600 hover:bg-brand-500 border border-brand-500 text-white flex items-center justify-center gap-2 text-xs font-semibold transition cursor-pointer shadow-xs"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New Chat</span>
            </button>
          )}

          {/* NO SIDEBAR NAV SECTION (removed 2026-09-14). UK: "chat
              threads ko jagah nahi milegi" -- correct; this list of
              four buttons was competing with the chat thread list for
              the sidebar's limited vertical space, which is the wrong
              trade on a phone. CodeBox instead lives in the icon
              subheader (App.tsx), right next to Virtual CLI, which is
              where UK asked for it and where Dashboard/Trace/CLI
              already lived before this round touched anything. */}

          {/* Search Threads input (only when expanded) */}
          {!isCollapsed && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-sm"
              style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text)' }}
            >
              <Search size={13} style={{ color: 'var(--jarvis-text-muted)' }} className="shrink-0" />
              <input
                type="text"
                placeholder="Search chats..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full bg-transparent outline-none text-sm"
                style={{ color: 'var(--jarvis-text)' }}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          )}
        </div>

        {/* Scrollable Chat Threads List */}
        {isCollapsed ? (
          /* Slim Rail View: Icon-only list of active & recent chats */
          <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">
            {sessions.slice(0, 8).map(session => {
              const isActive = session.sessionId === activeSessionId;
              return (
                <button
                  key={session.sessionId}
                  onClick={() => onSelectSession(session.sessionId)}
                  className={`w-10 h-10 mx-auto rounded-xl flex items-center justify-center transition cursor-pointer relative group ${
                    isActive
                      ? 'bg-brand-600 text-white shadow-xs'
                      : isDark
                      ? 'hover:bg-white/10 text-slate-400 hover:text-white'
                      : 'hover:bg-slate-100 text-slate-600 hover:text-slate-900'
                  }`}
                  title={session.title}
                >
                  <MessageSquare className="w-4 h-4" />
                  {session.pinned && (
                    <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-brand-400" />
                  )}
                </button>
              );
            })}
          </div>
        ) : (
          /* Full Expanded View: Grouped with Collapsible Sections */
          <div className="flex-1 min-h-0 overflow-y-auto p-2.5 space-y-3 font-sans">
            {/* Pinned Section */}
            {pinnedSessions.length > 0 && (
              <div className="space-y-1">
                <button
                  onClick={() => setPinnedOpen(!pinnedOpen)}
                  className="w-full px-2 py-1 flex items-center justify-between text-xs font-medium transition-colors cursor-pointer select-none" style={{ color: 'var(--jarvis-text-muted)' }}
                >
                  <span className="flex items-center gap-1.5">
                    <Pin className="w-2.5 h-2.5 text-brand-500" />
                    <span>Pinned</span>
                  </span>
                  {pinnedOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                </button>
                {pinnedOpen && pinnedSessions.map(renderSessionItem)}
              </div>
            )}

            {/* Recent Section (Last 7 Days) */}
            <div className="space-y-1">
              <button
                onClick={() => setRecentOpen(!recentOpen)}
                className="w-full px-2 py-1 flex items-center justify-between text-xs font-medium transition-colors cursor-pointer select-none" style={{ color: 'var(--jarvis-text-muted)' }}
              >
                <span className="flex items-center gap-1.5">
                  <Clock className="w-2.5 h-2.5 text-brand-500" />
                  <span>Recent (Last 7 Days)</span>
                </span>
                {recentOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              </button>
              {recentOpen &&
                (recentSessions.length > 0 ? (
                  recentSessions.map(renderSessionItem)
                ) : (
                  <div className="px-3 py-2 text-xs text-slate-400 italic">No recent chats</div>
                ))}
            </div>

            {/* Older Section */}
            {olderSessions.length > 0 && (
              <div className="space-y-1">
                <button
                  onClick={() => setOlderOpen(!olderOpen)}
                  className="w-full px-2 py-1 flex items-center justify-between text-xs font-medium transition-colors cursor-pointer select-none" style={{ color: 'var(--jarvis-text-muted)' }}
                >
                  <span>Older Conversations</span>
                  {olderOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                </button>
                {olderOpen && olderSessions.map(renderSessionItem)}
              </div>
            )}

            {filteredSessions.length === 0 && (
              <div className="text-center py-8 text-xs text-slate-400">No conversations found</div>
            )}
          </div>
        )}

        {/* Sidebar Footer: Unified Profile, Settings, and Theme Hub */}
        <div className="p-2.5 border-t border-slate-200 dark:border-white/10 space-y-2 select-none">
          {isCollapsed ? (
            /* Slim Rail Footer Icons */
            <div className="flex flex-col items-center gap-2">
              <button
                onClick={onOpenProfileSettings}
                className="w-9 h-9 rounded-xl bg-brand-500/20 text-brand-400 border border-brand-400/30 flex items-center justify-center font-bold text-xs hover:scale-105 transition-transform cursor-pointer"
                title="Profile & Settings"
              >
                {isAdmin ? 'AD' : <User className="w-4 h-4" />}
              </button>
              {onOpenSettings && (
                <button
                  onClick={onOpenSettings}
                  className="w-9 h-9 rounded-xl hover:bg-slate-100 dark:hover:bg-white/10 text-slate-500 dark:text-slate-400 hover:text-brand-500 transition flex items-center justify-center cursor-pointer"
                  title="Settings"
                >
                  <Settings className="w-4 h-4" />
                </button>
              )}
            </div>
          ) : (
            /* Profile dropdown -- replaces the old bare-Login-button
               footer. Click the avatar to see role status, open
               settings, or log out. Every role (guest/user/admin/
               owner/co-owner) gets the right label and actions instead
               of collapsing into an isAdmin boolean. */
            <ProfileDropdown
              role={(role as any) || (isAdmin ? 'admin' : 'guest')}
              displayName={displayName}
              onOpenAuth={onOpenAuth}
              onOpenSettings={onOpenProfileSettings}
              onLogout={onLogout}
            />
          )}
        </div>
      </aside>
    </>
  );
}
