// =============================================================================
// JARVIS.console — app logic
// Split out of the old single index.html so the file is manageable.
// =============================================================================

// PWA Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW Registration Notice:', err.message));
    });
}

// System State Variables
let ws = null;
let activeSessionId = null;
let deferredPrompt = null;
let pingTimer = null;
let alertCount = 0;
let startTime = Date.now();
let userIsScrolledUp = false;

// --- WebSocket connection-stability state ---
// wsGeneration is the fix for the Connected/Disconnected spam: every
// initWebSocket() call mints a new generation number, and any handler
// (onopen/onmessage/onclose/onerror) belonging to an older generation
// bails out immediately instead of acting. That makes it impossible for
// two overlapping sockets -- e.g. one from a scheduled reconnect and one
// triggered manually from sendMessage() -- to both be "live" and fight
// each other, which was the root cause of the rapid flapping in the CLI.
let wsGeneration = 0;
let wsReconnectDelay = 1000;
const WS_RECONNECT_MAX_DELAY = 15000;
let wsReconnectTimer = null;

// Server-side "thinking" state mirrored on the client, keyed by
// session_id. Populated from thinking_sync (on connect) and
// thinking_start/thinking_end (live), and from /api/history's
// is_thinking flag when a thread is opened after being away.
let thinkingSessions = new Set();

// Diagnostic CLI State
let allDiagnosticLogs = [];
let diagnosticDisplayLimit = 5;
// Monotonic counter so "newest first" ordering is guaranteed by an
// explicit sort at render time -- not just by insertion order, which
// could otherwise get scrambled if two log events land in the same
// tick (e.g. a websocket reconnect error arriving around the same
// moment as a long-running query's trace card).
let diagnosticSeqCounter = 0;

// Chat History State
let fullChatHistory = [];
let visibleChatCount = 10;

// Utility: HTML Escaper to Prevent XSS
function escapeHTML(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Utility: normalize any timestamp string (ISO datetime with microseconds,
// locale time string, etc.) down to a plain, standard hh:mm:ss.
function toHHMMSS(str) {
    if (!str) {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    const match = String(str).match(/(\d{1,2}:\d{2}:\d{2})/);
    return match ? match[1] : String(str);
}

// Telemetry Runtime Clock
setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    const hrs = String(Math.floor(elapsed / 3600)).padStart(2, '0');
    const mins = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
    const secs = String(elapsed % 60).padStart(2, '0');
    const timerEl = document.getElementById('jarvis-timer');
    if (timerEl) timerEl.innerText = `${hrs}:${mins}:${secs}`;
}, 1000);

// Initial Initialization
window.addEventListener('DOMContentLoaded', async () => {
    await fetchConfig();
    fetchSessions();
    initWebSocket();
    syncWorkspacePadding();
});

async function fetchConfig() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error('Network error');
        const data = await res.json();
        window.JARVIS_MODE = data.mode || 'dev';
        const modeEl = document.getElementById('mode-label');
        if (modeEl) modeEl.innerText = window.JARVIS_MODE;
    } catch(e) {
        window.JARVIS_MODE = 'dev';
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById('appSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar && overlay) {
        sidebar.classList.toggle('-translate-x-full');
        overlay.classList.toggle('hidden');
    }
}

function toggleDiagnosticsModal() {
    const modal = document.getElementById('diagnosticsModal');
    if (modal) {
        modal.classList.toggle('hidden');
        if (!modal.classList.contains('hidden')) {
            resetAlertBadge();
            renderDiagnosticsList();
        }
    }
}

function incrementAlertBadge() {
    alertCount++;
    const badge = document.getElementById('cli-alert-badge');
    if (badge) {
        badge.innerText = alertCount;
        badge.classList.remove('hidden');
    }
}

function resetAlertBadge() {
    alertCount = 0;
    const badge = document.getElementById('cli-alert-badge');
    if (badge) {
        badge.classList.add('hidden');
        badge.innerText = '0';
    }
}

function autoResizeTextarea(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 128) + 'px';
    // WhatsApp-style: as soon as the textarea's own height changes, the
    // input bar around it changes height too. Nudge the chat area's
    // padding immediately (don't wait for the ResizeObserver's next
    // frame) so there's zero flash of overlap while typing/pasting fast
    // (e.g. pasting a long block of code).
    syncWorkspacePadding();
}

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// -----------------------------------------------------------------------
// WHATSAPP-STYLE INPUT BAR
// -----------------------------------------------------------------------
// #floatingInputBar is a floating absolute-positioned overlay so the chat
// area doesn't reflow every keystroke. That's fine while the bar's height
// is constant -- but the moment the textarea wraps to multiple lines (e.g.
// pasting a chunk of code), the bar grows taller and would otherwise climb
// up OVER the last messages. Fix: continuously measure the bar's real
// rendered height and mirror it onto #workspace-container's
// padding-bottom (with a small gap for breathing room), and re-pin to the
// bottom if the user was already there.
// -----------------------------------------------------------------------
function syncWorkspacePadding() {
    const bar = document.getElementById('floatingInputBar');
    const scrollEl = getScrollContainer();
    if (!bar || !scrollEl) return;

    const barHeight = bar.offsetHeight;
    const breathingRoom = 16;
    const wasPinnedToBottom = !userIsScrolledUp;

    scrollEl.style.paddingBottom = (barHeight + breathingRoom) + 'px';

    if (wasPinnedToBottom) {
        requestAnimationFrame(() => {
            scrollEl.scrollTop = scrollEl.scrollHeight;
        });
    }
}

// Catches every way the bar's height can change: textarea growing/
// shrinking, the footer status line collapsing on keyboard-open, font
// loading shifts, orientation change -- all of it, without having to
// manually call syncWorkspacePadding() from every single place that
// might affect the bar's size.
let __inputBarObserver = null;
function initInputBarObserver() {
    const bar = document.getElementById('floatingInputBar');
    if (!bar) return;
    if ('ResizeObserver' in window) {
        __inputBarObserver = new ResizeObserver(() => syncWorkspacePadding());
        __inputBarObserver.observe(bar);
    } else {
        // Very old browser fallback: poll occasionally instead.
        setInterval(syncWorkspacePadding, 400);
    }
}
document.addEventListener('DOMContentLoaded', initInputBarObserver);

// -----------------------------------------------------------------------
// BUG FIX: mobile keyboard-aware collapse (grid / footer / logo).
// -----------------------------------------------------------------------
// The page's <meta viewport> sets `interactive-widget=resizes-content`,
// which means Android/Chrome *already* shrinks window.innerHeight (and
// visualViewport.height moves in lockstep with it) the instant the
// keyboard opens. The old detection compared
// `window.innerHeight - visualViewport.height`, expecting that gap to
// reveal the keyboard -- but with resizes-content that gap is always
// ~0, since both numbers shrink together. Net effect: `keyboard-active`
// never got added, so the quick-prompt grid/footer never collapsed, and
// on top of that a manual `translateY(-keyboardOffset)` was being added
// to the input bar even though the browser had *already* moved it by
// resizing the layout -- a double-shift that's what made the bar / chat
// bubbles jump around while typing or when the keyboard opened.
//
// Fix: don't compare two APIs that now agree with each other. Instead,
// track the *tallest* viewport height we've seen since load (that's the
// "keyboard fully closed" height for the current orientation) and diff
// the live height against that baseline. Also: drop the manual
// translateY entirely -- resizes-content already repositions the
// absolutely-positioned bar correctly, so JS only needs to toggle the
// `keyboard-active` class for the collapse animation.
// -----------------------------------------------------------------------
function getCurrentViewportHeight() {
    return window.visualViewport ? window.visualViewport.height : window.innerHeight;
}

let maxViewportHeightSeen = getCurrentViewportHeight();
const KEYBOARD_OFFSET_THRESHOLD = 100; // px - well above normal browser-chrome jitter

let __kbRafPending = false;
function positionInputBarForKeyboard() {
    // Coalesce bursts of visualViewport resize/scroll events into one
    // measurement per animation frame, so fast keyboard open/close (or
    // rapid typing that grows the textarea) never causes layout thrash.
    if (__kbRafPending) return;
    __kbRafPending = true;
    requestAnimationFrame(() => {
        __kbRafPending = false;
        _measureAndApplyKeyboardState();
    });
}

function _measureAndApplyKeyboardState() {
    const bar = document.getElementById('floatingInputBar');
    if (!bar) return;

    if (window.innerWidth >= 768) {
        // Desktop: no on-screen keyboard concept, always expanded.
        document.body.classList.remove('keyboard-active');
        syncWorkspacePadding();
        return;
    }

    const currentHeight = getCurrentViewportHeight();

    // The baseline only ever grows -- it represents "keyboard fully
    // closed" for the current orientation. A rotation naturally produces
    // a new, valid max once the keyboard is closed again; while the
    // keyboard is open the height only ever shrinks below it, which is
    // exactly the signal we want.
    if (currentHeight > maxViewportHeightSeen) {
        maxViewportHeightSeen = currentHeight;
    }

    const keyboardOffset = Math.max(0, maxViewportHeightSeen - currentHeight);
    const keyboardOpen = keyboardOffset > KEYBOARD_OFFSET_THRESHOLD;

    // No manual transform here on purpose -- `interactive-widget=
    // resizes-content` already shrinks the layout viewport (and therefore
    // #floatingInputBar's containing block) so the bar sits above the
    // keyboard automatically. Adding a second, manual shift on top of
    // that was the double-shift bug.
    document.body.classList.toggle('keyboard-active', keyboardOpen);

    // Guard against the browser trying to scroll the page (and header)
    // itself when the textarea receives focus.
    if (window.scrollY !== 0) window.scrollTo(0, 0);

    syncWorkspacePadding();
}

function onInputFocus() {
    positionInputBarForKeyboard();
}
function onInputBlur() {
    // Give the viewport a moment to settle, then let the viewport-driven
    // check above be the single source of truth for the collapsed state.
    setTimeout(positionInputBarForKeyboard, 150);
}
if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', positionInputBarForKeyboard);
    window.visualViewport.addEventListener('scroll', positionInputBarForKeyboard);
}
// A plain orientation/resize (not just keyboard) should also re-evaluate
// once things settle, so a rotated phone doesn't get stuck with a stale
// baseline height.
window.addEventListener('orientationchange', () => {
    setTimeout(() => {
        maxViewportHeightSeen = getCurrentViewportHeight();
        positionInputBarForKeyboard();
    }, 300);
});

// The actual scrolling element is #workspace-container (chat-box just
// holds content) — always read/write scroll position on the container.
function getScrollContainer() {
    return document.getElementById('workspace-container');
}

function onChatScroll() {
    const scrollEl = getScrollContainer();
    if (!scrollEl) return;
    const threshold = 80;
    userIsScrolledUp = (scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight) > threshold;
}

async function fetchSessions() {
    try {
        const res = await fetch('/api/sessions');
        const data = await res.json();
        if (data.status === 'success') {
            // Backend already returns sessions ordered pinned-first, then
            // most-recently-active — no client-side re-sort needed.
            renderSessions(data.sessions || []);
        }
    } catch (err) {
        document.getElementById('sessions-today').innerHTML = '<div class="text-[11px] text-gray-500 italic p-2">No active sessions</div>';
    }
}

// Each row: a tap target that opens the thread, plus a "..." button that
// opens the rename/pin/delete sheet — mirrors the Gemini/ChatGPT pattern.
function renderSessions(sessions) {
    const todayContainer = document.getElementById('sessions-today');
    const prevContainer = document.getElementById('sessions-previous');
    todayContainer.innerHTML = '';
    prevContainer.innerHTML = '';

    let todayCount = 0, prevCount = 0;
    sessions.forEach(s => {
        const isActive = s.session_id === activeSessionId;

        const row = document.createElement('div');
        row.className = `flex items-center rounded-xl transition ${
            isActive ? 'bg-cyan-500/15 border border-cyan-500/30 shadow-md' : 'hover:bg-cyberCard'
        }`;

        const mainBtn = document.createElement('button');
        mainBtn.className = `flex-1 min-w-0 text-left pl-3.5 pr-1 py-2.5 text-xs flex items-center gap-2 ${
            isActive ? 'text-cyan-300 font-semibold' : 'text-gray-400 hover:text-white'
        }`;
        mainBtn.onclick = () => switchSession(s.session_id, s.title);
        mainBtn.innerHTML = `
            <i class="fa-solid ${s.pinned ? 'fa-thumbtack text-amber-400' : 'fa-message fa-regular'} text-[10px] shrink-0"></i>
            <span class="truncate flex-1 font-mono">${escapeHTML(s.title)}</span>
            <span class="text-[9px] px-2 py-0.5 rounded-lg bg-cyberDark text-gray-400 font-mono border border-cyberBorder shrink-0">${s.msg_count || 0}</span>
        `;

        const menuBtn = document.createElement('button');
        menuBtn.className = 'shrink-0 w-8 h-8 flex items-center justify-center text-gray-500 hover:text-white rounded-xl mr-1 transition';
        menuBtn.title = 'Thread options';
        menuBtn.innerHTML = '<i class="fa-solid fa-ellipsis-vertical text-[11px]"></i>';
        menuBtn.onclick = (e) => {
            e.stopPropagation();
            openSessionSheet(s.session_id, s.title, !!s.pinned);
        };

        row.appendChild(mainBtn);
        row.appendChild(menuBtn);

        if (s.category === 'Today') {
            todayContainer.appendChild(row);
            todayCount++;
        } else {
            prevContainer.appendChild(row);
            prevCount++;
        }
    });
    if (todayCount === 0) todayContainer.innerHTML = '<div class="text-[11px] text-gray-500 italic px-2">No threads today</div>';
    if (prevCount === 0) prevContainer.innerHTML = '<div class="text-[11px] text-gray-500 italic px-2">No earlier history</div>';
}

// --- Session Action Sheet (rename / pin / delete) ---
let sessionSheetContext = null;

function openSessionSheet(id, title, pinned) {
    sessionSheetContext = { id, title, pinned };
    document.getElementById('sessionSheetTitle').innerText = title;
    document.getElementById('sheetPinLabel').innerText = pinned ? 'Unpin' : 'Pin';
    document.getElementById('sheetPinIcon').className = `fa-solid fa-thumbtack w-4 ${pinned ? 'text-amber-400' : 'text-cyan-400'}`;
    document.getElementById('sessionSheetOverlay').classList.remove('hidden');
    const sheet = document.getElementById('sessionActionSheet');
    sheet.classList.remove('hidden');
    requestAnimationFrame(() => sheet.classList.add('sheet-open'));
}

function closeSessionSheet() {
    const sheet = document.getElementById('sessionActionSheet');
    sheet.classList.remove('sheet-open');
    document.getElementById('sessionSheetOverlay').classList.add('hidden');
    setTimeout(() => sheet.classList.add('hidden'), 200);
    sessionSheetContext = null;
}

async function handleSheetPin() {
    if (!sessionSheetContext) return;
    const { id, pinned } = sessionSheetContext;
    closeSessionSheet();
    try {
        await fetch(`/api/sessions/${id}/pin`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pinned: !pinned })
        });
        fetchSessions();
    } catch (e) { console.error('Pin failed:', e); }
}

function handleSheetRename() {
    if (!sessionSheetContext) return;
    const { id, title } = sessionSheetContext;
    closeSessionSheet();
    openRenameModal(id, title);
}

async function handleSheetDelete() {
    if (!sessionSheetContext) return;
    const { id } = sessionSheetContext;
    closeSessionSheet();
    if (!confirm('Delete this thread? This cannot be undone.')) return;
    try {
        await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        thinkingSessions.delete(id);
        if (id === activeSessionId) goHome();
        fetchSessions();
    } catch (e) { console.error('Delete failed:', e); }
}

// --- Rename Modal ---
let renameContext = null;

function openRenameModal(id, currentTitle) {
    renameContext = id;
    const input = document.getElementById('renameInput');
    input.value = currentTitle;
    const overlay = document.getElementById('renameModalOverlay');
    overlay.classList.remove('hidden');
    overlay.classList.add('flex');
    setTimeout(() => { input.focus(); input.select(); }, 50);
}

function closeRenameModal() {
    const overlay = document.getElementById('renameModalOverlay');
    overlay.classList.add('hidden');
    overlay.classList.remove('flex');
    renameContext = null;
}

async function submitRename() {
    if (!renameContext) return;
    const newTitle = document.getElementById('renameInput').value.trim();
    if (!newTitle) { closeRenameModal(); return; }
    const id = renameContext;
    try {
        await fetch(`/api/sessions/${id}/rename`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        if (id === activeSessionId) {
            document.getElementById('active-thread-title').innerText = newTitle;
        }
        fetchSessions();
    } catch (e) { console.error('Rename failed:', e); }
    closeRenameModal();
}

// --- Smooth home <-> chat view transition (no flicker) ---
function showHomeView() {
    const home = document.getElementById('home-view');
    const chat = document.getElementById('chat-box');
    chat.classList.remove('view-visible');
    chat.classList.add('view-hidden');
    home.classList.remove('view-hidden');
    requestAnimationFrame(() => home.classList.add('view-visible'));
}

function showChatView() {
    const home = document.getElementById('home-view');
    const chat = document.getElementById('chat-box');
    home.classList.remove('view-visible');
    home.classList.add('view-hidden');
    chat.classList.remove('view-hidden');
    requestAnimationFrame(() => chat.classList.add('view-visible'));
}

function goHome() {
    activeSessionId = null;
    removeTypingIndicator();
    document.getElementById('active-thread-title').innerText = "JARVIS Dashboard";
    showHomeView();
    fetchSessions();
    if (window.innerWidth < 768) {
        const sidebar = document.getElementById('appSidebar');
        if (sidebar && sidebar.classList.contains('-translate-x-full') === false) toggleSidebar();
    }
}

async function switchSession(sessionId, title) {
    activeSessionId = sessionId;
    document.getElementById('active-thread-title').innerText = title || "Chat Thread";
    showChatView();
    fetchSessions();
    await loadHistory(sessionId);
    if (window.innerWidth < 768) toggleSidebar();
}

async function createNewThread() {
    try {
        const res = await fetch('/api/sessions/new', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') switchSession(data.session_id, data.title);
    } catch (err) { console.error("Failed to create session:", err); }
}

async function loadHistory(sessionId) {
    visibleChatCount = 10;
    fullChatHistory = [];
    removeTypingIndicator();

    try {
        const res = await fetch(`/api/history?session_id=${sessionId}`);
        const data = await res.json();

        if (data.status === 'success' && data.history && data.history.length > 0) {
            fullChatHistory = data.history;
            renderPaginatedChatHistory();
        } else {
            const box = document.getElementById('chat-box');
            box.innerHTML = `
                <div class="text-center py-12">
                    <div class="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/30 mx-auto flex items-center justify-center text-cyan-400 text-lg mb-2 shadow-xl">
                        <i class="fa-solid fa-comments"></i>
                    </div>
                    <h3 class="text-xs font-bold text-white mb-1">New Neural Thread Started</h3>
                    <p class="text-[10px] text-gray-400">Ask JARVIS anything. Subsystems are active.</p>
                </div>
            `;
        }

        // If the server says this session still has a query in flight
        // (data.is_thinking), restore the "Thinking..." bubble immediately
        // -- this is what makes it survive refresh, going back to home,
        // and switching threads and back.
        if (data.is_thinking) {
            thinkingSessions.add(sessionId);
        } else {
            thinkingSessions.delete(sessionId);
        }
        if (sessionId === activeSessionId && thinkingSessions.has(sessionId)) {
            showTypingIndicator();
        }
    } catch (err) { console.error("Error loading history:", err); }
}

function loadEarlierMessages() {
    visibleChatCount += 10;
    renderPaginatedChatHistory(false);
}

// WhatsApp-style: newest thread opens scrolled to bottom; loading earlier messages
// preserves the reader's current view instead of yanking the scroll position.
function renderPaginatedChatHistory(scrollToBottom = true) {
    const box = document.getElementById('chat-box');
    const scrollEl = getScrollContainer();
    const previousScrollHeight = scrollEl.scrollHeight;
    const previousScrollTop = scrollEl.scrollTop;
    box.innerHTML = '';

    const totalMsgs = fullChatHistory.length;
    const startIndex = Math.max(0, totalMsgs - visibleChatCount);
    const sliceMsgs = fullChatHistory.slice(startIndex, totalMsgs);

    if (startIndex > 0) {
        const loadBtn = document.createElement('div');
        loadBtn.className = 'flex justify-center my-3 cursor-pointer';
        loadBtn.onclick = loadEarlierMessages;
        loadBtn.innerHTML = `
            <span class="bg-cyberCard hover:bg-cyberBorder border border-cyberBorder text-cyan-400 text-[10px] px-3.5 py-1.5 rounded-full shadow-md font-mono flex items-center gap-2 transition">
                <i class="fa-solid fa-clock-rotate-left text-[9px]"></i> Load earlier messages (${startIndex} hidden)
            </span>
        `;
        box.appendChild(loadBtn);
    }

    const dateBadge = document.createElement('div');
    dateBadge.className = 'flex justify-center my-3';
    dateBadge.innerHTML = `
        <span class="bg-cyberCard/90 border border-cyberBorder text-gray-400 text-[9px] font-bold px-3 py-1 rounded-full shadow-sm font-mono tracking-wider uppercase">
            TODAY
        </span>
    `;
    box.appendChild(dateBadge);

    sliceMsgs.forEach(msg => {
        appendMessage(msg.sender, msg.text, msg.source === 'cli' ? 'CLI User' : 'UK', false, msg.timestamp, msg.trace_log);
        if (msg.trace_log) {
            addDiagnosticLogObject(msg.trace_log, msg.timestamp || new Date().toLocaleTimeString(), 'TRACE');
        }
    });

    requestAnimationFrame(() => {
        syncWorkspacePadding();
        if (scrollToBottom) {
            scrollEl.scrollTop = scrollEl.scrollHeight;
        } else {
            // keep the message that was on screen in view, rather than forcing scroll
            scrollEl.scrollTop = previousScrollTop + (scrollEl.scrollHeight - previousScrollHeight);
        }
    });
}

// -----------------------------------------------------------------------
// Push + Pull reconciliation (WhatsApp/Telegram-style reliability)
// -----------------------------------------------------------------------
// WebSocket "push" can occasionally miss a message (e.g. exactly in the
// gap between an old socket closing and a new one finishing its
// reconnect handshake). The server already saved everything to the DB
// regardless, so this silently double-checks against /api/history and
// repairs the UI if anything was missed -- without any visible reload.
async function silentResyncActiveThread() {
    if (!activeSessionId) return;
    try {
        const res = await fetch(`/api/history?session_id=${activeSessionId}`);
        const data = await res.json();
        if (data.status !== 'success') return;

        const serverCount = (data.history || []).length;
        const localCount = fullChatHistory.length;

        if (serverCount !== localCount) {
            await loadHistory(activeSessionId);
        } else if (!data.is_thinking && thinkingSessions.has(activeSessionId)) {
            // Server says processing finished, but the thinking_end
            // websocket signal never arrived -- clear it immediately
            // instead of leaving "Thinking..." stuck on screen.
            thinkingSessions.delete(activeSessionId);
            await loadHistory(activeSessionId);
        }
    } catch (e) { /* network hiccup -- the next poll will retry */ }
}

// Only polls while a session is actually "thinking" -- zero extra load
// the rest of the time.
setInterval(() => {
    if (activeSessionId && thinkingSessions.has(activeSessionId)) {
        silentResyncActiveThread();
    }
}, 3000);

// Catch anything missed while the tab/app was backgrounded.
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') silentResyncActiveThread();
});

// ---------------------------------------------------------------------
// WebSocket lifecycle — single-instance, generation-guarded, with
// exponential backoff and visibility-aware reconnects. See the
// wsGeneration comment above for why this stops the Connected/
// Disconnected flapping seen in the CLI.
// ---------------------------------------------------------------------
function initWebSocket() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    // Detach and close any previous socket first so its callbacks can
    // never fire alongside the new one.
    if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        try { ws.close(); } catch (e) {}
    }

    const myGeneration = ++wsGeneration;
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${wsProtocol}//${location.host}/ws`);
    ws = socket;

    socket.onopen = () => {
        if (myGeneration !== wsGeneration) return;
        wsReconnectDelay = 1000; // reset backoff after a clean connect
        document.getElementById('sync-status').innerText = "Core Live";
        document.getElementById('sync-ping-dot').className = "w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping";
        addDiagnosticLogObject("WebSocket Connected: " + location.host, new Date().toLocaleTimeString(), 'DEBUG');

        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'ping' }));
            }
        }, 15000);

        // Catch up on anything that changed while disconnected (renames,
        // new threads created elsewhere, etc), and reconcile the active
        // thread in case a response was missed during the gap.
        fetchSessions();
        silentResyncActiveThread();
    };

    socket.onmessage = (event) => {
        if (myGeneration !== wsGeneration) return;
        try {
            const data = JSON.parse(event.data);
            const timeStr = data.timestamp || new Date().toLocaleTimeString();

            if (data.type === 'pong') return;

            if (data.type === 'pulse') {
                document.getElementById('beat-count').innerText = `${data.beats || 0} bpm`;
                document.getElementById('sub-state').innerText = data.state || 'Active';
            } else if (data.type === 'cli_log' || data.type === 'debug_log') {
                addDiagnosticLogObject(data.text, timeStr, data.level || 'DEBUG');
                if ((data.level || '').toUpperCase() === 'ERROR') incrementAlertBadge();
            } else if (data.type === 'thinking_sync') {
                // Snapshot sent right after connect: which sessions are
                // still mid-query on the server.
                Object.keys(data.sessions || {}).forEach(sid => thinkingSessions.add(sid));
                if (activeSessionId && thinkingSessions.has(activeSessionId)) {
                    showTypingIndicator();
                }
            } else if (data.type === 'thinking_start') {
                thinkingSessions.add(data.session_id);
                if (data.session_id === activeSessionId) showTypingIndicator();
            } else if (data.type === 'thinking_end') {
                thinkingSessions.delete(data.session_id);
                if (data.session_id === activeSessionId) removeTypingIndicator();
            } else if (data.type === 'session_created') {
                // A brand-new thread exists -- refresh the sidebar
                // immediately instead of waiting for the first AI reply.
                fetchSessions();
            } else if (data.type === 'chat_sync') {
                addDiagnosticLogObject(`Query Processed: "${(data.text || '').substring(0, 35)}..."`, timeStr, 'INGESTION');
                // If this message belongs to the thread currently open
                // in THIS tab/device, render it live instead of only
                // refreshing the sidebar counters.
                if (data.session_id === activeSessionId) {
                    appendMessage('user', data.text, data.source === 'cli' ? 'CLI User' : 'UK', true, timeStr);
                }
                fetchSessions();
            } else if (data.type === 'chat_response') {
                thinkingSessions.delete(data.session_id);
                if (data.session_id === activeSessionId) {
                    removeTypingIndicator();
                    appendMessage('jarvis', data.text, 'JARVIS', true, timeStr, data.trace_log);
                }
                if (data.trace_log) {
                    addDiagnosticLogObject(data.trace_log, timeStr, 'TRACE');
                }
                fetchSessions();
            } else if (data.type === 'system_error') {
                addDiagnosticLogObject(`[ERROR] ${data.source}: ${data.error}\n${data.traceback || ''}`, timeStr, 'ERROR');
                incrementAlertBadge();
            } else if (data.type === 'chat_error') {
                removeTypingIndicator();
                appendMessage('jarvis', `⚠️ ${data.text}`);
                incrementAlertBadge();
            } else if (data.type === 'session_renamed') {
                if (data.session_id === activeSessionId) {
                    document.getElementById('active-thread-title').innerText = data.title;
                }
                fetchSessions();
            } else if (data.type === 'session_deleted') {
                thinkingSessions.delete(data.session_id);
                if (data.session_id === activeSessionId) goHome();
                fetchSessions();
            } else if (data.type === 'session_pinned') {
                fetchSessions();
            } else if (data.type === 'file_sync') {
                addDiagnosticLogObject(data.message || `Live updated: ${data.file}`, timeStr, 'DEBUG');
            }
        } catch (err) {
            addDiagnosticLogObject(event.data, new Date().toLocaleTimeString(), 'DEBUG');
        }
    };

    socket.onclose = (evt) => {
        if (myGeneration !== wsGeneration) return; // superseded by a newer socket, ignore
        document.getElementById('sync-status').innerText = "Reconnecting...";
        document.getElementById('sync-ping-dot').className = "w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse";
        addDiagnosticLogObject(
            `WebSocket Disconnected (code ${evt.code}). Retrying in ${Math.round(wsReconnectDelay / 1000)}s...`,
            new Date().toLocaleTimeString(), 'ERROR'
        );
        incrementAlertBadge();
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }

        wsReconnectTimer = setTimeout(() => {
            // A backgrounded/hidden tab doesn't need to keep retrying on
            // its own timer — visibilitychange below will reconnect the
            // instant it's foregrounded again, which avoids burning
            // battery/network on a tab nobody is looking at.
            if (document.visibilityState === 'hidden') return;
            initWebSocket();
        }, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * 1.7, WS_RECONNECT_MAX_DELAY);
    };

    socket.onerror = () => {
        if (myGeneration !== wsGeneration) return;
        addDiagnosticLogObject('WebSocket Exception encountered.', new Date().toLocaleTimeString(), 'ERROR');
        // onclose always fires right after onerror for a WebSocket, so
        // the actual reconnect scheduling stays there — scheduling it
        // here too would double the reconnect attempts.
    };
}

// Reconnect immediately when the tab regains focus/visibility or the
// device regains network, instead of waiting out a stale backoff timer.
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!ws || ws.readyState === WebSocket.CLOSED)) {
        wsReconnectDelay = 1000;
        initWebSocket();
    }
});
window.addEventListener('online', () => {
    if (!ws || ws.readyState === WebSocket.CLOSED) {
        wsReconnectDelay = 1000;
        initWebSocket();
    }
});

// Android/Chrome sometimes restores a backgrounded tab straight from
// bfcache (no reload). In that case 'ws' can look like it's still
// "OPEN" in JS even though the underlying socket is dead -- pageshow
// with persisted=true catches exactly this and forces a fresh connect.
window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
        wsReconnectDelay = 1000;
        initWebSocket();
        fetchSessions();
    }
});

// Keeps the screen awake only while this tab is actually the visible,
// foreground tab. Note: this is a browser API limitation, not a bug --
// no web API can keep a socket alive once Android fully backgrounds/
// freezes the browser process itself.
let wakeLock = null;
async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator && document.visibilityState === 'visible') {
            wakeLock = await navigator.wakeLock.request('screen');
        }
    } catch (e) { /* silently ignore -- not all devices support it */ }
}
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') requestWakeLock();
});
requestWakeLock();

function addDiagnosticLogObject(text, timeStr, type = 'TRACE') {
    allDiagnosticLogs.unshift({ text, timeStr, type, seq: diagnosticSeqCounter++ });
    const modal = document.getElementById('diagnosticsModal');
    if (!modal.classList.contains('hidden')) {
        renderDiagnosticsList();
        // A fresh alert just landed while the panel is open -- scroll
        // it into view at the top instead of leaving the reader
        // stranded wherever they'd scrolled to.
        const diagLog = document.getElementById('diagnostics-log');
        if (diagLog) diagLog.scrollTop = 0;
    }
}

function loadMoreDiagnostics() {
    diagnosticDisplayLimit += 5;
    renderDiagnosticsList();
}

function renderDiagnosticsList() {
    const diagLog = document.getElementById('diagnostics-log');
    if (!diagLog) return;

    if (allDiagnosticLogs.length === 0) {
        diagLog.innerHTML = '<div class="text-gray-500 italic p-4 text-center">No trace logs for this session yet.</div>';
        return;
    }

    diagLog.innerHTML = '';
    // Defensive sort: newest-first is guaranteed by seq (assigned in
    // strict arrival order), regardless of how/when each entry was
    // pushed in. This is what fixes error/debug cards ever appearing
    // below an older trace card.
    const sortedLogs = [...allDiagnosticLogs].sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));
    const sliceLogs = sortedLogs.slice(0, diagnosticDisplayLimit);

    sliceLogs.forEach(log => {
        const card = buildTraceCardElement(log.text, log.timeStr, log.type);
        diagLog.appendChild(card);
    });

    if (allDiagnosticLogs.length > diagnosticDisplayLimit) {
        const remaining = allDiagnosticLogs.length - diagnosticDisplayLimit;
        const divider = document.createElement('div');
        divider.className = 'relative flex py-3 items-center justify-center cursor-pointer group';
        divider.onclick = loadMoreDiagnostics;
        divider.innerHTML = `
            <div class="flex-grow border-t border-cyberBorder group-hover:border-cyan-500/50 transition"></div>
            <span class="flex-shrink mx-3 bg-cyberCard px-3.5 py-1.5 rounded-full border border-cyberBorder group-hover:border-cyan-500/40 text-cyan-400 text-[10px] font-mono shadow-md flex items-center gap-2">
                <i class="fa-solid fa-arrows-rotate text-[9px] group-hover:rotate-180 transition duration-500"></i>
                Load More Entries (${remaining} remaining)
            </span>
            <div class="flex-grow border-t border-cyberBorder group-hover:border-cyan-500/50 transition"></div>
        `;
        diagLog.appendChild(divider);
    }
}

function buildTraceCardElement(text, timeStr, type = 'TRACE') {
    const card = document.createElement('div');
    const upperType = (type || 'TRACE').toUpperCase();

    if (text && text.includes('COGNITIVE EXECUTION TRACE')) {
        let latency = "N/A";
        let source = "WEB";
        let traceId = "TRC-LIVE";
        let eventIngestion = "USER_INPUT via 'web' interface";
        let faissDetail = "0 direct vector matches";
        let topMatchHtml = "";
        let kgDetail = "No explicit graph links detected";
        let pipelineDetail = "Episode logged & validated";
        let neuralDetail = "Context synthesized -> Response streamed";

        const latMatch = text.match(/Latency:\s*([0-9.]+s)/i);
        if (latMatch) latency = latMatch[1];

        const srcMatch = text.match(/Source:\s*([A-Z]+)/i);
        if (srcMatch) source = srcMatch[1];

        const idMatch = text.match(/Trace ID:\s*([A-Z0-9-]+)/i);
        if (idMatch) traceId = idMatch[1];

        const lines = text.split('\n');
        lines.forEach(line => {
            const l = line.trim();
            if (l.includes('Event Ingestion:')) {
                eventIngestion = escapeHTML(l.replace(/.*Event Ingestion:/, '').trim());
            } else if (l.includes('FAISS Vector Index:')) {
                faissDetail = escapeHTML(l.replace(/.*FAISS Vector Index:/, '').trim());
            } else if (l.includes('Top Match Frame:')) {
                const matchContent = escapeHTML(l.replace(/.*Top Match Frame:/, '').trim());
                topMatchHtml = `<div class="bg-black/50 px-3 py-2 rounded-xl border border-cyberBorder text-[10px] text-cyan-300 font-mono break-all mt-1.5">Top Match: ${matchContent}</div>`;
            } else if (l.includes('Knowledge Graph:') || l.includes('NetworkX Knowledge Graph:')) {
                kgDetail = escapeHTML(l.replace(/.*Knowledge Graph:/, '').replace(/.*NetworkX Knowledge Graph:/, '').trim());
            } else if (l.includes('ExperienceEngine:') || l.includes('Pipeline State:')) {
                pipelineDetail = escapeHTML(l.replace(/.*ExperienceEngine:/, '').replace(/.*Pipeline State:/, '').trim());
            } else if (l.includes('Neural Inference') || l.includes('LlamaCpp')) {
                if (l.includes('->')) {
                    const parts = l.split('->');
                    neuralDetail = escapeHTML(parts[parts.length - 1].trim());
                } else {
                    neuralDetail = escapeHTML(l.replace(/.*Neural Inference.*?:/, '').trim());
                }
            }
        });

        card.className = `p-4 sm:p-5 rounded-2xl matrix-card-trace shadow-2xl space-y-3 font-mono text-[11px] w-full overflow-hidden`;
        card.innerHTML = `
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-cyberBorder pb-2.5">
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="px-2.5 py-1 rounded-lg text-[9px] font-bold uppercase border text-purple-300 border-purple-500/40 bg-purple-500/15">TRACE</span>
                    <span class="text-[10px] text-cyan-300 bg-cyan-500/10 border border-cyan-500/30 px-2.5 py-1 rounded-lg font-bold">${escapeHTML(traceId)}</span>
                </div>
                <span class="text-[9px] text-gray-400 flex items-center gap-1.5 bg-cyberDark px-2.5 py-1 rounded-lg border border-cyberBorder font-mono">
                    <i class="fa-regular fa-clock"></i> ${escapeHTML(timeStr || new Date().toLocaleTimeString())}
                </span>
            </div>

            <div class="grid grid-cols-2 gap-2 bg-black/40 p-2.5 rounded-xl border border-cyberBorder">
                <div class="flex flex-col px-2.5 py-1.5 bg-cyberCard rounded-xl border border-cyberBorder">
                    <span class="text-gray-400 text-[9px] uppercase font-semibold">Source</span>
                    <span class="text-purple-300 font-bold text-xs truncate mt-0.5">${escapeHTML(source)}</span>
                </div>
                <div class="flex flex-col px-2.5 py-1.5 bg-cyan-500/10 rounded-xl border border-cyan-500/20">
                    <span class="text-gray-400 text-[9px] uppercase font-semibold">Latency</span>
                    <span class="text-cyan-300 font-bold text-xs truncate mt-0.5">${escapeHTML(latency)}</span>
                </div>
            </div>

            <div class="space-y-2">
                <div class="text-[9px] text-gray-500 uppercase tracking-widest font-bold px-0.5">Pipeline Architecture</div>

                <div class="bg-cyberCard px-3.5 py-2.5 rounded-xl border border-cyberBorder shadow-sm space-y-1">
                    <div class="text-gray-300 flex items-center gap-2 text-[10px] font-semibold">
                        <i class="fa-solid fa-bolt text-cyan-400 shrink-0"></i> Event Ingestion
                    </div>
                    <div class="text-cyan-200 text-[10px] bg-cyan-500/10 border border-cyan-500/25 py-1.5 px-3 rounded-lg break-words">
                        ${eventIngestion}
                    </div>
                </div>

                <div class="bg-cyberCard px-3.5 py-2.5 rounded-xl border border-cyberBorder shadow-sm space-y-1">
                    <div class="text-gray-300 flex items-center gap-2 text-[10px] font-semibold">
                        <i class="fa-solid fa-database text-cyan-400 shrink-0"></i> FAISS Vector Index
                    </div>
                    <div class="text-emerald-400 text-[10px] bg-emerald-500/10 border border-emerald-500/30 py-1.5 px-3 rounded-lg break-words">
                        ${faissDetail}
                    </div>
                    ${topMatchHtml}
                </div>

                <div class="bg-cyberCard px-3.5 py-2.5 rounded-xl border border-cyberBorder shadow-sm space-y-1">
                    <div class="text-gray-300 flex items-center gap-2 text-[10px] font-semibold">
                        <i class="fa-solid fa-network-wired text-purple-400 shrink-0"></i> Knowledge Graph
                    </div>
                    <div class="text-purple-300 text-[10px] bg-purple-500/10 border border-purple-500/30 py-1.5 px-3 rounded-lg break-words">
                        ${kgDetail}
                    </div>
                </div>

                <div class="bg-cyberCard px-3.5 py-2.5 rounded-xl border border-cyberBorder shadow-sm space-y-1">
                    <div class="text-gray-300 flex items-center gap-2 text-[10px] font-semibold">
                        <i class="fa-solid fa-shield-halved text-blue-400 shrink-0"></i> Learning Pipeline (ExperienceEngine)
                    </div>
                    <div class="text-blue-300 text-[10px] bg-blue-500/10 border border-blue-500/30 py-1.5 px-3 rounded-lg break-words">
                        ${pipelineDetail}
                    </div>
                </div>

                <div class="bg-cyberCard px-3.5 py-2.5 rounded-xl border border-cyberBorder shadow-sm space-y-1">
                    <div class="text-gray-300 flex items-center gap-2 text-[10px] font-semibold">
                        <i class="fa-solid fa-brain text-amber-400 shrink-0"></i> Neural Inference (LlamaCpp)
                    </div>
                    <div class="text-cyan-300 text-[10px] bg-cyan-500/10 border border-cyan-500/30 py-1.5 px-3 rounded-lg break-words">
                        ${neuralDetail}
                    </div>
                </div>
            </div>
        `;
    } else {
        let cardClass = 'matrix-card-trace';
        let badgeColor = 'text-purple-300 border-purple-500/40 bg-purple-500/15';
        let icon = 'fa-microchip';

        if (upperType === 'INGESTION' || upperType === 'DEBUG') {
            cardClass = 'matrix-card-ingestion';
            badgeColor = 'text-cyan-300 border-cyan-500/40 bg-cyan-500/15';
            icon = 'fa-bolt';
        } else if (upperType === 'ERROR') {
            cardClass = 'matrix-card-error';
            badgeColor = 'text-red-300 border-red-500/45 bg-red-500/20';
            icon = 'fa-triangle-exclamation';
        }

        card.className = `p-4 rounded-2xl ${cardClass} shadow-xl space-y-2.5 font-mono text-[11px] w-full overflow-hidden`;
        card.innerHTML = `
            <div class="flex items-center justify-between border-b border-cyberBorder pb-2">
                <span class="px-3 py-1 rounded-xl text-[9px] font-bold uppercase border ${badgeColor} flex items-center gap-2 shrink-0">
                    <i class="fa-solid ${icon}"></i> ${escapeHTML(upperType)}
                </span>
                <span class="text-[9px] text-gray-400 flex items-center gap-1.5 font-mono shrink-0 bg-cyberDark px-2.5 py-1 rounded-xl border border-cyberBorder">
                    <i class="fa-regular fa-clock text-[8px]"></i> ${escapeHTML(timeStr || new Date().toLocaleTimeString())}
                </span>
            </div>
            <div class="text-gray-200 leading-relaxed whitespace-pre-wrap break-words px-1">${escapeHTML(text)}</div>
        `;
    }
    return card;
}

async function sendMessage() {
    const input = document.getElementById('userInput');
    const text = input.value.trim();
    if (!text) return;

    // Switch views first, without any flash of empty state
    if (document.getElementById('home-view').classList.contains('view-visible')) {
        showChatView();
    }

    if (!activeSessionId) {
        try {
            const res = await fetch('/api/sessions/new', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                activeSessionId = data.session_id;
                document.getElementById('active-thread-title').innerText = data.title;
                // Don't wait for the AI's reply to show the new thread --
                // the sidebar should reflect it the instant it's created.
                fetchSessions();
            }
        } catch(e) { console.error("Auto session create failed:", e); return; }
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        appendMessage('jarvis', '⚠️ Server disconnected. Reconnecting...');
        wsReconnectDelay = 1000;
        initWebSocket();
        return;
    }

    const currentTime = new Date().toLocaleTimeString();
    appendMessage('user', text, 'UK', true, currentTime);
    thinkingSessions.add(activeSessionId);
    showTypingIndicator();
    addDiagnosticLogObject(`Query Processed: "${text}"`, currentTime, 'INGESTION');

    ws.send(JSON.stringify({
        type: 'user_message',
        text: text,
        session_id: activeSessionId
    }));

    input.value = '';
    input.style.height = 'auto';
    syncWorkspacePadding();
    input.blur();
}

function quickPrompt(text) {
    const input = document.getElementById('userInput');
    input.value = text;
    autoResizeTextarea(input);
    sendMessage();
}

function copyMessage(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = 'fa-solid fa-check text-emerald-400';
            setTimeout(() => icon.className = 'fa-regular fa-copy', 2000);
        }
    });
}

// Clean bubble: "Sender • time" joined on one line so short bubbles never
// look cramped, plus an optional compact DEV TRACE badge underneath.
//
// BUG FIX (long code paste making the bubble "jump"/overflow): the text
// node now carries the `msg-bubble-text` class (see style.css), which
// forces long unbroken tokens -- a long line of code, a hash, a URL -- to
// wrap inside the bubble instead of stretching the row width and shoving
// everything else around.
function appendMessage(role, text, label = null, animate = true, timestamp = null, traceLog = null) {
    const box = document.getElementById('chat-box');
    const isUser = role === 'user';
    const timeStr = timestamp || new Date().toLocaleTimeString();
    const safeText = escapeHTML(text);

    const msgDiv = document.createElement('div');
    msgDiv.className = `flex flex-col gap-1 w-full ${isUser ? 'items-end' : 'items-start'}`;

    const copyBtnHtml = !isUser ? `
        <button onclick="copyMessage(this, \`${safeText.replace(/`/g, '\\`')}\`)" class="opacity-0 group-hover:opacity-100 transition text-gray-400 hover:text-white text-[10px]" title="Copy Message">
            <i class="fa-regular fa-copy"></i>
        </button>
    ` : '';

    let devBadgeHtml = '';
    if (window.JARVIS_MODE === 'dev' && !isUser && traceLog) {
        devBadgeHtml = `
            <div class="ml-11 flex items-center gap-1.5 text-[9px] font-mono text-cyan-400/90 bg-cyan-500/5 border border-cyan-500/20 px-2.5 py-1 rounded-full">
                <i class="fa-solid fa-microchip text-[8px]"></i>
                <span class="font-semibold tracking-wide">DEV TRACE</span>
                <span class="text-gray-500">&bull;</span>
                <span class="text-gray-400">Time: ${escapeHTML(toHHMMSS(timeStr))}</span>
            </div>
        `;
    }

    msgDiv.innerHTML = `
        <div class="flex gap-3 sm:gap-4 max-w-[92%] sm:max-w-[85%] ${isUser ? 'flex-row-reverse' : 'flex-row'} group">
            <div class="w-8 h-8 rounded-2xl bg-gradient-to-tr ${isUser ? 'from-purple-600 to-indigo-600' : 'from-cyan-500 to-purple-600'} flex items-center justify-center text-white text-xs font-bold shrink-0 shadow-lg">
                ${isUser ? 'UK' : 'J'}
            </div>
            <div class="relative rounded-3xl p-4 sm:p-5 text-xs sm:text-sm leading-relaxed font-mono ${isUser ? 'bg-purple-600/20 border border-purple-500/30 text-purple-100 rounded-tr-sm shadow-lg' : 'bg-cyberCard border border-cyberBorder text-gray-200 rounded-tl-sm shadow-2xl'} break-words min-w-0">
                <div class="flex items-center justify-between gap-3 mb-1 text-[9px] text-gray-400 font-bold border-b border-cyberBorder/40 pb-1">
                    <span class="truncate">${isUser ? 'UK Admin' : 'JARVIS Core'}</span>
                    ${copyBtnHtml}
                </div>
                <div class="msg-bubble-text whitespace-pre-wrap">${safeText}</div>
            </div>
        </div>
        ${devBadgeHtml}
    `;
    box.appendChild(msgDiv);
    if (animate && !userIsScrolledUp) {
        const scrollEl = getScrollContainer();
        requestAnimationFrame(() => { scrollEl.scrollTop = scrollEl.scrollHeight; });
    }
}

function showTypingIndicator() {
    removeTypingIndicator();
    const box = document.getElementById('chat-box');
    const indicator = document.createElement('div');
    indicator.id = 'typing-indicator';
    indicator.className = 'flex gap-3 items-center';
    indicator.innerHTML = `
        <div class="w-8 h-8 rounded-2xl bg-gradient-to-tr from-cyan-500 to-purple-600 flex items-center justify-center text-white text-xs font-bold shrink-0 shadow-lg">J</div>
        <div class="inline-flex items-center gap-2 bg-cyberCard border border-cyberBorder rounded-full px-3.5 py-2 shadow-lg font-mono text-cyan-400">
            <div class="flex items-center gap-1">
                <span class="w-1 h-1 rounded-full bg-cyan-400 animate-bounce"></span>
                <span class="w-1 h-1 rounded-full bg-cyan-400 animate-bounce [animation-delay:0.15s]"></span>
                <span class="w-1 h-1 rounded-full bg-cyan-400 animate-bounce [animation-delay:0.3s]"></span>
            </div>
            <span class="text-[10px] text-gray-400">Thinking&hellip;</span>
        </div>
    `;
    box.appendChild(indicator);
    if (!userIsScrolledUp) {
        const scrollEl = getScrollContainer();
        requestAnimationFrame(() => { scrollEl.scrollTop = scrollEl.scrollHeight; });
    }
}

function removeTypingIndicator() {
    const ind = document.getElementById('typing-indicator');
    if (ind) ind.remove();
}

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    document.getElementById('installBtn')?.classList.remove('hidden');
});

async function installApp() {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
        document.getElementById('installBtn')?.classList.add('hidden');
    }
    deferredPrompt = null;
}
