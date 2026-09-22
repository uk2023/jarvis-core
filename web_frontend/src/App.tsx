import React, { useState, useEffect } from 'react';
import {
  Home,
  Activity,
  Terminal,
  FileSearch,
  MessageSquare,
  Shield,
  LogOut,
  Menu,
  Sliders,
  User,
  Sparkles,
  Database,
  Layers,
  FileCode,
  Phone,
  Bot,
} from 'lucide-react';
import { AppTheme, ConsoleView, SessionItem, ChatMessage } from './types';
import { api } from './api/client';
import {
  INITIAL_SESSIONS,
  INITIAL_MESSAGES_BY_SESSION,
  OLDER_ARCHIVED_MESSAGES,
} from './data/chatSessions';
import { HomeScreen } from './components/HomeScreen';
import { DashboardScreen } from './components/DashboardScreen';
import { VirtualCLIScreen } from './components/VirtualCLIScreen';
import { TraceInspectorScreen } from './components/TraceInspectorScreen';
import CodeBoxScreen from './components/CodeBoxScreen';
import CodingAgentWorkspace from './components/CodingAgentWorkspace';
import VoiceCallScreen from './components/VoiceCallScreen';
import { prewarmVoice, unlockVoice } from './voice/jarvisVoice';
import OwnerLoginScreen from './components/OwnerLoginScreen';
import { loginRouteFromPath, applyRoutePath, clearRouteIds } from './routes/roleRoutes';
import { isReady, isReadyForRole } from './config/features';
import { UserChatView } from './components/UserChatView';
import { ChatThreadsSidebar } from './components/ChatThreadsSidebar';
import { StatusNotificationPopover } from './components/StatusNotificationPopover';
import { AuthModal } from './components/AuthModal';
import { SettingsModal } from './components/SettingsModal';
import { ProfileModal } from './components/ProfileModal';

export function App() {
  // Theme state: persists in localStorage
  const [theme, setTheme] = useState<AppTheme>(() => {
    try {
      const saved = localStorage.getItem('jarvis_theme') as AppTheme;
      return saved === 'light' || saved === 'dark' ? saved : 'dark';
    } catch {
      return 'dark';
    }
  });

  // AUTH STATE -- SINGLE SOURCE OF TRUTH (2026-09-13, UK: "koi bhi
  // password daalo to admin login ho jata hai", plus logout showing
  // wrong state). There were TWO competing auth stores: client.ts
  // holds the real backend-verified token in sessionStorage, while
  // this component independently trusted a localStorage marker called
  // 'jarvis_operator_token' -- and handleLoginSuccess wrote the
  // literal string 'operator-active' into it whenever no real token
  // existed. So the UI unlocked on a value it invented itself, with no
  // role attached and no server ever consulted; and because
  // localStorage outlives the sessionStorage token, the two disagreed
  // after a reload, which is the inconsistent logged-in/logged-out
  // display. Both now read from api.currentUser(), which only returns
  // a role when a real signed token from /api/auth/login is present.
  const [session, setSession] = useState(() => api.currentUser());
  const isAuthenticated = session.isLoggedIn;
  const role = session.role;                       // 'owner' | 'co_owner' | 'admin' | 'user' | 'guest'
  const isOwner = role === 'owner' || role === 'co_owner';
  const isAdmin = isOwner || role === 'admin';

  // SESSION-PERSISTENT UI STATE (2026-09-12, UK's explicit fix
  // request: minimizing Chrome on Android can cause the tab to be
  // discarded by the OS under memory pressure -- when reopened, the
  // page does a full reload and every useState here would normally
  // reset to its default, landing back on 'home' with the monitor/CLI
  // scroll and active section all lost. Read once from sessionStorage
  // on first render (survives a tab reload, cleared when the tab/
  // window actually closes -- the same scope as the auth session in
  // api/client.ts), then a single effect below keeps it in sync on
  // every change.
  // Voice needs warming before first use and unlocking on a real user
  // gesture -- see unlockVoice() in voice/jarvisVoice.ts for why the
  // browser silently drops utterances otherwise.
  // /owner is the owner and co-owner entrance. It is a separate SCREEN,
  // not a separate security boundary -- role is always checked
  // server-side against the session token. The route exists so the
  // owner is not forced through a signup form whose 3-character
  // username rule rejects "uk".
  const [ownerRoute] = useState(() => loginRouteFromPath() === 'owner');

  // Reflect the session in the address bar with an opaque id, so a
  // screenshot or a glance never exposes a username.
  useEffect(() => {
    const role = (session?.role as any) ?? 'guest';
    applyRoutePath(role);
  }, [session?.role]);

  useEffect(() => {
    prewarmVoice();
    const unlock = () => unlockVoice();
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
    return () => {
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
    };
  }, []);

  const [currentView, setCurrentView] = useState<ConsoleView>(() => {
    try {
      return (sessionStorage.getItem('jarvis_ui_currentView') as ConsoleView) || 'home';
    } catch {
      return 'home';
    }
  });

  // Active dashboard section for sub-header navigation: 'monitor' | 'memory' | 'reasoning' | 'organs' | 'all'
  const [dashboardSection, setDashboardSection] = useState<'monitor' | 'memory' | 'reasoning' | 'organs' | 'all'>(() => {
    try {
      return (sessionStorage.getItem('jarvis_ui_dashboardSection') as any) || 'monitor';
    } catch {
      return 'monitor';
    }
  });

  useEffect(() => {
    try {
      sessionStorage.setItem('jarvis_ui_currentView', currentView);
      sessionStorage.setItem('jarvis_ui_dashboardSection', dashboardSection);
    } catch {
      // sessionStorage unavailable -- state simply won't survive a reload, no functional harm otherwise
    }
  }, [currentView, dashboardSection]);

  // Selected Turn ID for Trace Inspector
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);

  // Auth modal toggle
  const [isAuthOpen, setIsAuthOpen] = useState(false);

  // Categorized Settings modal toggle
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // User Profile modal toggle
  const [isProfileOpen, setIsProfileOpen] = useState(false);

  // Mobile sidebar drawer
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  // Pulse & beat ticker
  const [beatCount, setBeatCount] = useState(88);

  // Chat Sessions & Active Thread State
  const [sessions, setSessions] = useState<SessionItem[]>(() => {
    try {
      const saved = localStorage.getItem('jarvis_chat_sessions');
      if (saved) return JSON.parse(saved);
    } catch {}
    return INITIAL_SESSIONS;
  });

  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    try {
      const savedId = localStorage.getItem('jarvis_active_session_id');
      if (savedId) return savedId;
    } catch {}
    return INITIAL_SESSIONS[0]?.sessionId || 'session-1';
  });

  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessage[]>>(() => {
    try {
      const saved = localStorage.getItem('jarvis_messages_by_session');
      if (saved) return JSON.parse(saved);
    } catch {}
    return INITIAL_MESSAGES_BY_SESSION;
  });

  const [hasOlderMessages, setHasOlderMessages] = useState<boolean>(true);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingSeconds, setThinkingSeconds] = useState(0);

  const isDark = theme === 'dark';

  // Synchronize documentElement dark mode class for reliable Tailwind dark: styles
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  // Persist sessions to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('jarvis_chat_sessions', JSON.stringify(sessions));
    } catch {}
  }, [sessions]);

  // Persist activeSessionId
  useEffect(() => {
    try {
      localStorage.setItem('jarvis_active_session_id', activeSessionId);
    } catch {}
  }, [activeSessionId]);

  // Persist messagesBySession
  useEffect(() => {
    try {
      localStorage.setItem('jarvis_messages_by_session', JSON.stringify(messagesBySession));
    } catch {}
  }, [messagesBySession]);

  // LOAD REAL PERSISTED HISTORY FROM JARVIS (2026-09-17). Previously
  // chat was restored from localStorage ONLY -- the backend has stored
  // every turn (chat_messages table) and, since this session, the real
  // coding-agent/codebox thinking-step trace too (trace_log), but
  // nothing ever fetched it back. This is what makes a refresh show
  // JARVIS's own memory instead of just the browser's local cache, and
  // what makes the "PLAN / CODE / VERIFY" step panel survive a reload.
  // Best-effort and non-destructive: only overwrites the local cache
  // when the server has at least as many turns, and any fetch failure
  // silently keeps the existing local state -- never throws into the
  // chat UI.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.getSessionHistory(activeSessionId);
        if (cancelled || res.status !== 'success' || !Array.isArray(res.history) || !res.history.length) return;
        const serverMessages: ChatMessage[] = res.history.map((row) => ({
          id: `srv-${row.id}`,
          sessionId: activeSessionId,
          sender: row.sender === 'jarvis' ? 'jarvis' : 'user',
          text: row.text,
          timestamp: row.timestamp,
          source: (row.source as ChatMessage['source']) || 'web',
          thinkingSteps: Array.isArray(row.thinking_steps) && row.thinking_steps.length
            ? row.thinking_steps : undefined,
          thinkingNarratives: Array.isArray(row.thinking_narratives) && row.thinking_narratives.length
            ? row.thinking_narratives : undefined,
        }));
        setMessagesBySession((prev) => {
          const local = prev[activeSessionId] || [];
          if (serverMessages.length >= local.length) {
            return { ...prev, [activeSessionId]: serverMessages };
          }
          return prev;
        });
      } catch {
        // Server history unavailable -- keep whatever is already local.
      }
    })();
    return () => { cancelled = true; };
  }, [activeSessionId]);

  // Pulse & beat counter ticker
  useEffect(() => {
    const timer = setInterval(() => {
      setBeatCount(b => (b >= 9999 ? 1 : b + 1));
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // Thinking timer ticker
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    if (isThinking) {
      setThinkingSeconds(0);
      timer = setInterval(() => {
        setThinkingSeconds(s => s + 0.1);
      }, 100);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isThinking]);

  const toggleTheme = () => {
    const nextTheme: AppTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    try {
      localStorage.setItem('jarvis_theme', nextTheme);
    } catch {}
  };

  const handleLoginSuccess = () => {
    // Re-read the REAL session that client.ts just persisted from the
    // backend's response. Nothing is invented here any more -- if the
    // backend did not return a valid token and role, the UI stays
    // logged out, which is the correct outcome for a failed login.
    const fresh = api.currentUser();
    setSession(fresh);
    try {
      localStorage.removeItem('jarvis_operator_token');  // clear the old fake marker if a previous build left one behind
    } catch {}
    // Only elevated roles have a dashboard to land on; a plain user
    // goes to chat, and a guest never reaches this handler at all.
    setCurrentView(fresh.role === 'owner' || fresh.role === 'co_owner' || fresh.role === 'admin' ? 'dashboard' : 'user_chat');
  };

  const handleLogout = () => {
    api.logout();
    setSession(api.currentUser());
    try {
      localStorage.removeItem('jarvis_operator_token');
    } catch {}
    setCurrentView('user_chat');
  };

  const navigateToTrace = (turnId: string) => {
    setSelectedTurnId(turnId);
    setCurrentView('inspector');
    setIsMobileNavOpen(false);
  };

  const navigateToCLI = () => {
    setCurrentView('cli');
    setIsMobileNavOpen(false);
  };

  // Chat Session Management Handlers (Claude-style)
  const handleNewChat = () => {
    const newId = `session-${Date.now()}`;
    const newSession: SessionItem = {
      sessionId: newId,
      title: 'New Conversation',
      createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      updatedAt: 'Just now',
      pinned: false,
      msgCount: 0,
      category: 'Today',
    };

    setSessions(prev => [newSession, ...prev]);
    setActiveSessionId(newId);
    setMessagesBySession(prev => ({
      ...prev,
      [newId]: [],
    }));
    setCurrentView('user_chat');
  };

  const handleDeleteSession = (sessionIdToDelete: string) => {
    const updated = sessions.filter(s => s.sessionId !== sessionIdToDelete);
    setSessions(updated);

    // Clean up messages
    setMessagesBySession(prev => {
      const next = { ...prev };
      delete next[sessionIdToDelete];
      return next;
    });

    if (activeSessionId === sessionIdToDelete) {
      if (updated.length > 0) {
        setActiveSessionId(updated[0].sessionId);
      } else {
        handleNewChat();
      }
    }
  };

  const handleRenameSession = (sessionIdToRename: string, newTitle: string) => {
    setSessions(prev =>
      prev.map(s => (s.sessionId === sessionIdToRename ? { ...s, title: newTitle } : s))
    );
  };

  const handleTogglePinSession = (sessionIdToPin: string) => {
    setSessions(prev =>
      prev.map(s => (s.sessionId === sessionIdToPin ? { ...s, pinned: !s.pinned } : s))
    );
  };

  // Send message in current active session
  // Attaches a completed thinking-step panel to the LAST jarvis message
  // in the active session (2026-09-17) -- called from UserChatView
  // after both the live stream and the reply have finished. See
  // UserChatView's onAttachThinkingSteps prop doc for why this can't
  // be passed through handleSendMessage's own call.
  const attachThinkingStepsToLastMessage = (
    steps: { stage: string; content: string; duration_ms?: number; ok?: boolean; chunk_id?: number }[],
    narratives: { content: string; chunk_id: number }[] = [],
  ) => {
    setMessagesBySession((prev) => {
      const msgs = prev[activeSessionId] || [];
      const lastIdx = msgs.length - 1;
      if (lastIdx < 0 || msgs[lastIdx].sender !== 'jarvis') return prev;
      const updated = [...msgs];
      updated[lastIdx] = { ...updated[lastIdx], thinkingSteps: steps, thinkingNarratives: narratives };
      return { ...prev, [activeSessionId]: updated };
    });
    // PERSIST (2026-09-17, narratives added 2026-09-19) -- see
    // api.attachThinkingSteps's doc comment. Fire-and-forget: the
    // in-memory attach above already made the panel visible for this
    // session; this call is what makes it survive a refresh.
    api.attachThinkingSteps(activeSessionId, steps, narratives);
  };

  const handleSendMessage = async (
    text: string,
    realThinkingSteps?: { stage: string; content: string }[],
    deferReplyUntil?: Promise<any>,
    groundingSummary?: { current: string },
    // REAL upload_id(s) picked this turn via the chat composer's
    // attach button (2026-09-21) -- see UserChatView.tsx's
    // pendingAttachmentIds and client.ts's sendChat() doc comment.
    attachmentUploadIds?: string[],
  ) => {
    if (!text.trim() || isThinking) return;

    const userMsg: ChatMessage = {
      id: `usr-${Date.now()}`,
      sessionId: activeSessionId,
      sender: 'user',
      text: text.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      dateLabel: 'Today',
      source: 'web',
    };

    // Prepend/append to session's messages
    setMessagesBySession(prev => ({
      ...prev,
      [activeSessionId]: [...(prev[activeSessionId] || []), userMsg],
    }));

    // If new session, auto-rename title from query
    const currentSession = sessions.find(s => s.sessionId === activeSessionId);
    if (currentSession && currentSession.title === 'New Conversation') {
      const generatedTitle = text.slice(0, 30) + (text.length > 30 ? '...' : '');
      handleRenameSession(activeSessionId, generatedTitle);
    }

    setIsThinking(true);
    const startTime = Date.now();

    // WAIT FOR THINKING TO FINISH BEFORE FETCHING THE REPLY (2026-09-17,
    // UK's screenshots: some thinking steps kept arriving and rendering
    // a while AFTER the final answer had already appeared -- the
    // opposite of Claude's order (message -> thinking -> answer). Root
    // cause: the normal chat reply (api.sendChat below) and Extended
    // Thinking's own SSE analysis (UserChatView's streamThinking) are
    // two INDEPENDENT network calls with no coordination between them --
    // whichever one happens to finish first renders first, and Extended
    // Thinking's multi-step task_loop run is usually the slower one, so
    // its later steps kept trickling in after the reply was already on
    // screen. UserChatView now passes its thinking-stream promise here;
    // when present, the reply fetch waits for it, so the full thinking
    // panel is always complete before the answer appears -- matching
    // the order the panel already visually implies.
    if (deferReplyUntil) {
      try { await deferReplyUntil; } catch { /* thinking stream errors are handled in UserChatView */ }
    }

    try {
      // GROUND THE REPLY IN WHAT EXTENDED THINKING ACTUALLY DID
      // (2026-09-18, UK's repeated report: the reply text described a
      // DIFFERENT outcome than the steps panel just showed -- e.g. the
      // panel showing a package-install failure and a token-budget
      // stop, the reply instead saying "workdir uplabdh nahi hai",
      // something the steps never mentioned at all).
      //
      // Root cause: the visible steps panel (Extended Thinking's own
      // TaskLoop run, streamed via SSE) and this reply (the normal
      // chat pipeline, which decides FOR ITSELF via tool-calling
      // whether to invoke coding) are two INDEPENDENT attempts at the
      // same request, each its own separate LLM run with no shared
      // state. When the reply pipeline's own tool-calling also decided
      // to try the coding task, it started a SECOND, unrelated attempt
      // -- different sandbox session, different randomness, often a
      // different result -- and then described THAT one, which reads
      // as the reply "hallucinating" against the panel the person was
      // just watching.
      //
      // Rather than trying to prevent the reply pipeline from ever
      // calling coding tools (a much larger change), this tells it
      // PLAINLY what Extended Thinking already did this turn, so its
      // own reasoning has a truthful anchor: summarize/ground in this
      // real result instead of silently starting a redundant, possibly
      // contradictory attempt.
      const grounding = groundingSummary?.current;

      const res = await api.sendChat(text, activeSessionId, 'web', grounding, attachmentUploadIds);
      const duration = Number(((Date.now() - startTime) / 1000).toFixed(1));

      // NO FABRICATED STEPS (fixed 2026-09-15). This used to hardcode
      // the SAME four lines -- "Interpreted query semantics...",
      // "Surveyed FAISS vector episodic memory...", "Traversed
      // relationship graph...", "Formulated natural response" -- on
      // EVERY single reply, regardless of what actually happened. That
      // is fabricated telemetry, the same class of bug removed
      // elsewhere in this project (fake resource numbers, fake chat
      // fallbacks). It also explains why the message bubble's "Thought
      // for Xs" expander never matched the REAL streamed thinking
      // panel elsewhere on screen -- they were two disconnected
      // systems, one real, one invented.
      //
      // realThinkingSteps, when present, are the ACTUAL stages
      // UserChatView's extended-thinking stream captured for this
      // exact turn. Only real content goes on the message; if nothing
      // was captured (thinking was off, or produced nothing), the
      // expander simply does not appear -- no placeholder invented to
      // fill the gap.
      const jarvisMsg: ChatMessage = {
        id: res.messageId || `jarvis-${Date.now()}`,
        sessionId: activeSessionId,
        sender: 'jarvis',
        text: res.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        dateLabel: 'Today',
        source: 'web',
        thinkingDurationSeconds: Math.max(0.1, duration),
        thinkingProcess: realThinkingSteps && realThinkingSteps.length
          ? realThinkingSteps.map(s => s.content).filter(Boolean)
          : undefined,
      };

      setMessagesBySession(prev => ({
        ...prev,
        [activeSessionId]: [...(prev[activeSessionId] || []), jarvisMsg],
      }));
    } catch (err: any) {
      // NO FABRICATED REPLY (fixed 2026-09-15). This used to invent
      // "Understood, sir. I have processed '...' and verified
      // cognitive state consistency." on ANY failure -- network error,
      // backend down, timeout, anything. UK would read that as JARVIS
      // confidently confirming it did something, when the request had
      // actually failed outright. That is hallucination manufactured
      // by the frontend itself, not the model -- a failed request is a
      // failed request, shown as one.
      const duration = Number(((Date.now() - startTime) / 1000).toFixed(1));
      const errorMsg: ChatMessage = {
        id: `jarvis-error-${Date.now()}`,
        sessionId: activeSessionId,
        sender: 'jarvis',
        text: `Jawab nahi aaya -- ${err?.message || 'backend se connection nahi bana.'} `
             + `CLI mein JARVIS chal raha hai check karo.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        dateLabel: 'Today',
        source: 'web',
        thinkingDurationSeconds: Math.max(0.1, duration),
      };

      setMessagesBySession(prev => ({
        ...prev,
        [activeSessionId]: [...(prev[activeSessionId] || []), errorMsg],
      }));
    } finally {
      setIsThinking(false);
    }
  };

  // Load older historical messages
  const handleLoadEarlierMessages = () => {
    const older = OLDER_ARCHIVED_MESSAGES[activeSessionId];
    if (older && older.length > 0) {
      setMessagesBySession(prev => ({
        ...prev,
        [activeSessionId]: [...older, ...(prev[activeSessionId] || [])],
      }));
    }
    setHasOlderMessages(false);
  };

  const activeSession = sessions.find(s => s.sessionId === activeSessionId);
  const currentMessages = messagesBySession[activeSessionId] || [];

  // On /owner: show the owner entrance until an owner/co-owner session
  // exists. Everything else in the app stays untouched.
  if (ownerRoute && session?.role !== 'owner' && session?.role !== 'co_owner') {
    return (
      <OwnerLoginScreen
        onAuthenticated={() => {
          clearRouteIds();
          setSession(api.currentUser());
        }}
        onBack={() => { window.location.href = '/'; }}
      />
    );
  }

  return (
    <div
      className={`h-screen w-screen flex overflow-hidden font-sans ${
        isDark ? 'dark bg-[#05070c] text-slate-100' : 'bg-[#F8FAFC] text-slate-900'
      }`}
      id="app-root"
    >
      {/* ------------------------------------------------------------- */}
      {/* CLAUDE-STYLE CHAT THREADS SIDEBAR                             */}
      {/* ------------------------------------------------------------- */}
      <ChatThreadsSidebar
        theme={theme}
        isOpen={isMobileNavOpen}
        onClose={() => setIsMobileNavOpen(false)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={id => {
          setActiveSessionId(id);
          setCurrentView('user_chat');
        }}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onRenameSession={handleRenameSession}
        onTogglePinSession={handleTogglePinSession}
        onToggleTheme={toggleTheme}
        beatCount={beatCount}
        isAdmin={isAdmin}
        role={session?.role}
        displayName={session?.display_name || session?.username}
        onOpenProfileSettings={() => setIsProfileOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenAuth={() => setIsAuthOpen(true)}
        onGoHome={() => setCurrentView('home')}
        currentView={currentView}
        onNavigateToView={view => setCurrentView(view)}
        onNavigateToCodebox={() => setCurrentView('codebox')}
        onLogout={handleLogout}
      />

      {/* ------------------------------------------------------------- */}
      {/* MAIN CONTENT AREA                                             */}
      {/* ------------------------------------------------------------- */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
        {/* ============================================================= */}
        {/* TOP UNIFIED APPLICATION HEADER (Minimal, Neat & Tidy)         */}
        {/* ============================================================= */}
        <header
          className="h-14 px-3 sm:px-6 border-b flex items-center justify-between shrink-0 z-30"
          style={{ backgroundColor: 'var(--jarvis-surface-raised)', borderColor: 'var(--jarvis-border)' }}
        >
          {/* Left: mobile drawer trigger + JARVIS mark, name, subtitle.
              No online/offline dot here anymore (point 6, UK's
              explicit ask) -- that status lives ONLY in the
              right-corner indicator now, not duplicated in two
              places. */}
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              onClick={() => setIsMobileNavOpen(true)}
              className="p-1.5 rounded-lg border md:hidden shrink-0"
              style={{ borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text-muted)' }}
              title="Open navigation"
            >
              <Menu className="w-4 h-4" />
            </button>

            <button
              onClick={() => setCurrentView('home')}
              className="flex items-center gap-2 sm:gap-2.5 group cursor-pointer text-left select-none"
              title="Return to JARVIS Home"
            >
              <div className="relative w-8 h-8 rounded-xl border flex items-center justify-center shrink-0 transition-transform group-hover:scale-105" style={{ borderColor: 'var(--jarvis-border-strong)', backgroundColor: 'var(--jarvis-accent-dim)' }}>
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: 'var(--jarvis-accent)' }} />
              </div>
              <div className="hidden min-[360px]:block">
                <h1 className="font-semibold text-sm" style={{ color: 'var(--jarvis-text)' }}>
                  JARVIS
                </h1>
                <span className="text-xs -mt-0.5 block" style={{ color: 'var(--jarvis-text-muted)' }}>
                  Cognitive OS
                </span>
              </div>
            </button>
          </div>

          {/* Center Navigation: Quick Home & Chat */}
          <nav
            className="hidden md:flex items-center gap-1 p-1 rounded-2xl border"
            style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}
          >
            <button
              onClick={() => setCurrentView('home')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors"
              style={currentView === 'home' ? { backgroundColor: 'var(--jarvis-accent)', color: 'white' } : { color: 'var(--jarvis-text-muted)' }}
              title="JARVIS Home"
            >
              <Home className="w-3.5 h-3.5" />
              <span>Home</span>
            </button>

            <button
              onClick={() => setCurrentView('user_chat')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors"
              style={currentView === 'user_chat' ? { backgroundColor: 'var(--jarvis-accent)', color: 'white' } : { color: 'var(--jarvis-text-muted)' }}
              title="Chat"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Chat</span>
            </button>

            {/* CodeBox moved to the icon subheader (next to Virtual
                CLI) -- see the "5. CodeBox" block below, which replaced
                the old Organs button. Kept only here: nothing; this
                was the duplicate top-bar entry. */}

            {isReady('call') && (
            <button
              onClick={() => setCurrentView('call')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors"
              style={currentView === 'call' ? { backgroundColor: 'var(--jarvis-accent)', color: 'white' } : { color: 'var(--jarvis-text-muted)' }}
              title="Voice call"
            >
              <Phone className="w-3.5 h-3.5" />
              <span>Call</span>
            </button>
            )}
          </nav>

          {/* Right: ONLY the connection indicator -- no login button */}
          <div className="flex items-center gap-2">
            <StatusNotificationPopover
              theme={theme}
              isAdmin={isAdmin}
              onNavigateToTrace={navigateToTrace}
            />
          </div>
        </header>

        {/* ============================================================= */}
        {/* SUB-HEADER: 6 Admin Elements (Chat removed, Centered & Wide)   */}
        {/* a. Monitor • b. Trace Inspector • c. Memory & DB • d. Reasoning • e. Organs • f. Virtual CLI */}
        {/* ============================================================= */}
        {isAuthenticated && (
          <div
            className={`h-11 px-3 sm:px-6 border-b flex items-center justify-center shrink-0 z-20 transition-colors ${
              isDark
                ? 'bg-[#060911]/90 backdrop-blur-md border-white/10'
                : 'bg-slate-100/95 backdrop-blur-md border-slate-200 shadow-2xs'
            }`}
          >
            <div className="w-full max-w-xl flex items-center justify-center gap-1 sm:gap-2">
              {/* 1. Monitor */}
              <button
                onClick={() => {
                  setCurrentView('dashboard');
                  setDashboardSection('monitor');
                }}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'dashboard' && dashboardSection === 'monitor'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="Monitor (System Telemetry & Vitals)"
              >
                <Activity className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  Monitor
                </span>
              </button>

              {/* 2. Trace Inspector */}
              <button
                onClick={() => setCurrentView('inspector')}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'inspector'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="Trace Inspector (Turn Execution & Latency Waterfall)"
              >
                <FileSearch className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  Trace Inspector
                </span>
              </button>

              {/* 3. Memory and Database */}
              <button
                onClick={() => {
                  setCurrentView('dashboard');
                  setDashboardSection('memory');
                }}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'dashboard' && dashboardSection === 'memory'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="Memory & Database (Schema Contracts & Evolution DB)"
              >
                <Database className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  Memory & Database
                </span>
              </button>

              {/* 4. System Reasoning */}
              <button
                onClick={() => {
                  setCurrentView('dashboard');
                  setDashboardSection('reasoning');
                }}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'dashboard' && dashboardSection === 'reasoning'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="System Reasoning (Overnight Learning & Self-Improvement)"
              >
                <Sparkles className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  System Reasoning
                </span>
              </button>

              {/* 5. CodeBox -- REPLACES the old "Organs" button
                  (2026-09-14, UK: "organ inspection ko remove karke
                  wahan codebox daal do, virtual CLI ke bagal mein
                  icon ke saath"). Organ introspection data still
                  exists (see core/orchestration/organ_introspection.py)
                  and is reachable from the CLI's own diagnostics; it
                  was not deleted, just moved out of the icon row that
                  UK actually uses day to day.
                  Role-gated the same way the sidebar's CodeBox entry
                  is (features.ts) -- admin/owner/co_owner only, so a
                  plain user or guest does not even see the icon. */}
              {isReadyForRole('codebox', session?.role) && (
              <button
                onClick={() => setCurrentView('codebox')}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'codebox'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="CodeBox (Sandboxed Coding, 5-Layer QA)"
              >
                <FileCode className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  CodeBox
                </span>
              </button>
              )}

              {/* REPO-SCALE AGENT -- next to CodeBox on purpose: same
                  capability family, two depths (one script vs a whole
                  project), so they belong side by side rather than in
                  unrelated corners of the nav. */}
              {isReadyForRole('coding_agent', session?.role) && (
              <button
                onClick={() => setCurrentView('coding_agent')}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'coding_agent'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="Coding Agent (repo-scale: plan, edit, test, fix, package)"
              >
                <Bot className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  Coding Agent
                </span>
              </button>
              )}

              {/* 6. Virtual CLI */}
              <button
                onClick={() => setCurrentView('cli')}
                className={`flex-1 h-8 rounded-xl flex items-center justify-center transition-all cursor-pointer relative group ${
                  currentView === 'cli'
                    ? 'bg-brand-600 text-white shadow-xs font-semibold'
                    : isDark
                    ? 'bg-white/[0.02] text-slate-400 hover:text-white hover:bg-white/10 border border-white/5'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 shadow-2xs'
                }`}
                title="Virtual CLI (Diagnostic Shell & Terminal)"
              >
                <Terminal className="w-3.5 h-3.5 sm:w-4 sm:h-4 group-hover:scale-115 transition-transform duration-200 shrink-0" />
                <span className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded text-xs font-medium bg-slate-900 text-white opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-30 shadow-md border border-white/10">
                  Virtual CLI
                </span>
              </button>
            </div>
          </div>
        )}

        {/* View Switcher Routing */}
        <main className="flex-1 min-h-0 relative">
          {/* Home Landing Page (Default View) */}
          {currentView === 'home' && (
            <HomeScreen
              theme={theme}
              onNavigateToView={view => {
                if ((view === 'dashboard' || view === 'cli' || view === 'inspector') && !isAuthenticated) {
                  setIsAuthOpen(true);
                } else {
                  setCurrentView(view);
                }
              }}
              onStartChatWithPrompt={(prompt, attachmentUploadIds) => {
                setCurrentView('user_chat');
                handleSendMessage(prompt, undefined, undefined, undefined, attachmentUploadIds);
              }}
              isAdmin={isAdmin}
              onOpenAuth={() => setIsAuthOpen(true)}
            />
          )}

          {/* User Chat (Always accessible to all users) */}
          {currentView === 'user_chat' && (
            <UserChatView
              theme={theme}
              activeSessionId={activeSessionId}
              activeSessionTitle={activeSession?.title || 'New Conversation'}
              messages={currentMessages}
              onSendMessage={handleSendMessage}
              onAttachThinkingSteps={attachThinkingStepsToLastMessage}
              onLoadEarlierMessages={handleLoadEarlierMessages}
              hasOlderMessages={hasOlderMessages}
              isThinking={isThinking}
              thinkingSeconds={thinkingSeconds}
              isAdmin={isAdmin}
              onUnlockOperator={() => setIsProfileOpen(true)}
            />
          )}

          {/* Admin Protected Views: DashboardScreen */}
          {currentView === 'dashboard' &&
            (isAuthenticated ? (
              <DashboardScreen
                onSelectTurn={navigateToTrace}
                onNavigateToCLI={navigateToCLI}
                theme={theme}
                activeSection={dashboardSection}
                onSelectSection={sec => setDashboardSection(sec)}
              />
            ) : (
              <UserChatView
                theme={theme}
                activeSessionId={activeSessionId}
                activeSessionTitle={activeSession?.title || 'New Conversation'}
                messages={currentMessages}
                onSendMessage={handleSendMessage}
                onAttachThinkingSteps={attachThinkingStepsToLastMessage}
                onLoadEarlierMessages={handleLoadEarlierMessages}
                hasOlderMessages={hasOlderMessages}
                isThinking={isThinking}
                thinkingSeconds={thinkingSeconds}
                isAdmin={isAdmin}
                onUnlockOperator={() => setIsProfileOpen(true)}
              />
            ))}

          {currentView === 'codebox' && isReadyForRole('codebox', session?.role) && <CodeBoxScreen />}

          {currentView === 'coding_agent' && isReadyForRole('coding_agent', session?.role) && <CodingAgentWorkspace />}

          {currentView === 'call' && isReady('call') && <VoiceCallScreen />}

          {/* Admin Protected Views: VirtualCLIScreen */}
          {currentView === 'cli' &&
            (isAuthenticated ? (
              <VirtualCLIScreen theme={theme} />
            ) : (
              <UserChatView
                theme={theme}
                activeSessionId={activeSessionId}
                activeSessionTitle={activeSession?.title || 'New Conversation'}
                messages={currentMessages}
                onSendMessage={handleSendMessage}
                onAttachThinkingSteps={attachThinkingStepsToLastMessage}
                onLoadEarlierMessages={handleLoadEarlierMessages}
                hasOlderMessages={hasOlderMessages}
                isThinking={isThinking}
                thinkingSeconds={thinkingSeconds}
                isAdmin={isAdmin}
                onUnlockOperator={() => setIsProfileOpen(true)}
              />
            ))}

          {/* Admin Protected Views: TraceInspectorScreen */}
          {currentView === 'inspector' &&
            (isAuthenticated ? (
              /* THE ORIGINAL TRACE TREE, RESTORED (2026-09-14).
                 I replaced this whole screen with a new list view last
                 round. That was the wrong call: UK asked for a FILTER on
                 the existing trace, and the existing trace -- the
                 per-stage tree with PERCEPTION / INDEXING / ROUTING /
                 EXECUTION / LEARNING and the detail he actually reads --
                 is what he uses. Replacing a working view to add one
                 feature to it costs him the view.
                 The filter bar now sits ON TOP of it instead. */
              <TraceInspectorScreen
                selectedTurnId={selectedTurnId}
                onSelectTurnId={setSelectedTurnId}
                theme={theme}
                viewerRole={(session?.role as string) || 'guest'}
              />
            ) : (
              <UserChatView
                theme={theme}
                activeSessionId={activeSessionId}
                activeSessionTitle={activeSession?.title || 'New Conversation'}
                messages={currentMessages}
                onSendMessage={handleSendMessage}
                onAttachThinkingSteps={attachThinkingStepsToLastMessage}
                onLoadEarlierMessages={handleLoadEarlierMessages}
                hasOlderMessages={hasOlderMessages}
                isThinking={isThinking}
                thinkingSeconds={thinkingSeconds}
                isAdmin={isAdmin}
                onUnlockOperator={() => setIsProfileOpen(true)}
              />
            ))}
        </main>

        {/* ============================================================= */}
        {/* LANDING PAGE COMPACT FOOTER (Visible only on Home View)       */}
        {/* Compact, clean, 2-line format in corner/bottom, no overflow   */}
        {/* ============================================================= */}
        {currentView === 'home' && (
          <footer
            id="global-app-footer"
            className={`w-full border-t py-1.5 px-4 sm:px-6 font-mono text-xs sm:text-xs transition-colors shrink-0 z-20 ${
              isDark
                ? 'bg-[#050811]/95 backdrop-blur-md border-white/10 text-slate-400'
                : 'bg-slate-100/95 backdrop-blur-md border-slate-200 text-slate-600'
            }`}
          >
            <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-1 text-center sm:text-left">
              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-1.5">
                <span className="font-bold text-slate-900 dark:text-slate-100 tracking-wider">
                  JARVIS CORE
                </span>
                <span className="text-xs px-1 py-0.2 rounded bg-brand-500/15 text-brand-600 dark:text-brand-400 font-semibold border border-brand-500/20">
                  v2026.4
                </span>
                <span>&bull;</span>
                <span className="text-slate-600 dark:text-slate-300">
                  Copyright 2026 JARVIS Core. All rights reserved.
                </span>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center justify-center gap-1.5">
                <span>Cognitive OS Architecture</span>
                <span>&bull;</span>
                <span className="text-emerald-500 font-medium flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Live Telemetry
                </span>
              </div>
            </div>
          </footer>
        )}
      </div>

      {/* Operator Authentication Modal */}
      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onSuccess={handleLoginSuccess}
        theme={theme}
      />

      {/* ChatGPT-Style Categorized Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        theme={theme}
        onToggleTheme={toggleTheme}
        onSetTheme={t => setTheme(t)}
      />

      {/* User Profile & Accounts Modal */}
      <ProfileModal
        isOpen={isProfileOpen}
        onClose={() => setIsProfileOpen(false)}
        isAdmin={isAdmin}
        onLoginSuccess={handleLoginSuccess}
        onLogout={handleLogout}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    </div>
  );
}

export default App;
