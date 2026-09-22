# JARVIS Organism Console — Next Iteration Brief for AI Studio

## 1. What this project genuinely is (do not invent details beyond this)

JARVIS is a personal, offline-first AI companion built by and for one operator
("UK"). The **real backend** is a Python FastAPI server
(`backend/server.py` + `routes_http.py` + `routes_ws.py` +
`routes_frontend_v6.py` + `routes_frontend_v6_extra.py` +
`routes_state.py`), wrapping a cognitive pipeline (`core/orchestration/brain.py`)
that runs natively first and falls back to an LLM (Groq's
`openai/gpt-oss-120b` by default, with a second provider — Gemini, via its
OpenAI-compatible endpoint — available as a fallback) only when native
understanding genuinely can't resolve something. Persistent memory is
SQLite + FAISS. There is no "Qwen 3B" model anywhere in this project —
if you have seen that name in an earlier version of this app, it was a
placeholder invented by a previous scaffold and must be removed.

**Do not fabricate organ names, model names, or metrics.** Every screen
below must read real data from the endpoints listed in Section 3, with
loading and empty states — never `Math.random()` or hardcoded sample
numbers standing in for real data.

## 2. Tech stack and visual identity — KEEP THESE, do not redesign

- Vite + React 19 + TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`),
  `lucide-react` for icons, `motion` (Framer Motion successor) for
  animation, `canvas-confetti` for the rare celebratory moment.
- Fonts: `Plus Jakarta Sans` (body), `JetBrains Mono` (code/monospace,
  `.font-mono`).
- Palette: dark background, **cyan-400/500/600 as the primary accent**,
  emerald-400/500 as the secondary/success accent, glassmorphism panels
  (`.glass-panel`, `.glass-panel-dark`, `.glass-card` utility classes
  already defined in `src/index.css` — reuse them, don't reinvent).
  Background texture utilities `.bg-grid-dots` and `.bg-cyber-lines`
  already exist and are used across screens.
- Existing screens/components to preserve and extend, not replace:
  `HomeScreen`, `DashboardScreen`, `VirtualCLIScreen`,
  `TraceInspectorScreen`, `UserChatView`, `ChatThreadsSidebar`,
  `StatusNotificationPopover`, `AuthModal`, `ProfileSettingsModal`,
  `MemoryGraphViewer`, `OrganMatrix`, `OrganismCore`, `AutonomyCuriosity`,
  `DiagnosticsModal`, `PythonCodeHub`, `SessionActionSheet`,
  `TraceTreeViewer`.
- Two roles: `guest` (chat only, via `UserChatView`) and `admin`/operator
  (everything, unlocked via `AuthModal` against `/api/auth/login`).

## 3. Real, current backend contract — build against this exactly

All endpoints below exist today and return real data (no mocks):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| POST | `/api/auth/login` | `{password}` → `{success, token, role}` |
| GET | `/api/live_state` | Real-time pipeline stage, extraction attempts, logs (matches `LiveStateResponse` in `types.ts`) |
| GET | `/api/status` | Organ matrix, heartbeat, async learning queue |
| GET | `/api/resources` | Process RSS/CPU, LLM budget, self-evaluation, knowledge, evolution counts (matches `SystemResourcesData`) |
| GET | `/api/organism/state` | `OrganismTelemetry`: pulse, organs array with health |
| GET/POST/DELETE | `/api/memory/engrams` | `EngramFact[]` — subject/predicate/value/confidence/evidenceCount/status |
| GET | `/api/autonomy/state` | Curiosity goals + evolution proposals |
| POST | `/api/autonomy/trigger-idle` | Manually trigger one idle cycle |
| GET/POST | `/api/sessions` | Chat thread list/create |
| GET | `/api/history` | Cross-session activity history |
| POST | `/api/chat` | `{message, sessionId}` → real reply + trace |
| WS | `/ws` | `{type:"user_message", text, session_id}` → `chat_response`/`chat_sync`/`thinking_sync` frames |

## 4. NEW capabilities this brief adds (build UI for these — backend already has them)

The Python backend has real capabilities the current UI has no screen
for at all. Add these, in the same visual language as the existing
screens:

### 4a. Voice Control Panel (new tab or modal off `ProfileSettingsModal`)
Backend: TTS/STT live in `core/runtime/voice.py`, driven by Termux:API
on-device (not cloud) by default, with Whisper-via-Groq as an explicit,
opt-in fallback only.
- Pitch / rate / language sliders (current defaults: pitch 0.55, rate
  1.1, lang `hi-IN`) with a "Test phrase" button.
- A voice/engine picker (`termux-tts-engines` output — list of
  `{name, ...}` objects) since not every installed engine sounds the
  same and the operator should be able to compare.
- A toggle for "spoken replies" and a separate toggle for "Whisper
  fallback for voice input" (explicitly opt-in — local STT is the
  default, cloud is the fallback, never the reverse).
- **This is the mic-button ask**: the mic button in `UserChatView` and
  `VirtualCLIScreen` should stream raw audio over a WebSocket audio
  channel to the FastAPI backend (a NEW endpoint, distinct from `/ws`'s
  text-message protocol) where a server-side STT interface transcribes
  it (Whisper/Faster-Whisper) and streams back partial + final text.
  The final text is submitted through the exact same path as typed
  text — no special-casing downstream. This makes the mic work
  identically on Android, desktop browser, or any device, and means
  swapping the STT engine later never touches the frontend.

### 4b. Organ Introspection Viewer (new panel in `DashboardScreen` or `OrganMatrix`)
Backend: `core/orchestration/organ_introspection.py` — each organ
answers 10 fixed questions (who are you / responsibility / received /
produced / why / evidence / confidence / state changed / persisted /
unverified) from real per-turn data, never a bare "working correctly".
- One expandable card per organ (Perception, Semantic Understanding,
  Brain) showing all 10 answers plainly, monospace, no jargon.

### 4c. Overnight / Idle Learning Report (new card, e.g. on `HomeScreen` or `AutonomyCuriosity`)
Backend: `core/autonomy/idle_loop.py`'s `overnight_log` — real,
sandbox-tested vocabulary/pattern candidates found while idle, each
with genuine PASS/FAIL test evidence, never a fabricated "I learned a
lot" claim. Show: timestamp, what was reviewed, findings, and for each
finding whether it was sandbox-tested and the pass/fail counts.
Include an honest empty state ("nothing met the evidence threshold
last night") — don't hide it or fake activity.

### 4d. Self-Improvement Requests (new list view)
Backend: `core/learning/improvement_requests.py` — every time the
operator tells JARVIS "this is a bug" / "I want this feature" in chat,
it's recorded durably with an honest scope classification (`narrow` —
JARVIS can sandbox-test it itself — vs `broad` — needs a developer).
Show a simple list: request text, timestamp, scope badge, status.

### 4e. Runtime / Uptime widget (small, e.g. top bar or `OrganismCore`)
Backend: `core/identity/jarvis_identity.py`'s `runtime_info()` —
three distinct numbers, show all three, don't conflate them:
`session_uptime_seconds` (this process only), `cumulative_runtime_seconds`
(all sessions ever, persisted), `age_seconds` (time since first boot,
includes offline time).

### 4f. Safety Check History (small section in `DiagnosticsModal`)
Backend: `brain.safety_check_history` — a prompt-injection classifier
(Llama Prompt Guard 2) runs on every input; this is diagnostic-only
today (flags, never blocks). Show recent checks with their label
(benign/malicious) so the operator can see it's working, and a note
that flagged inputs are recorded but not yet auto-blocked.

## 5. What NOT to do

- Don't reintroduce a Node/Express mock server or `@google/genai`
  client-side calls — all AI inference happens server-side in Python.
- Don't invent new color schemes, fonts, or a different visual identity.
- Don't hardcode organ counts, model names, or example numbers anywhere
  in component code — every number must come from a fetch.
- Don't remove the guest/admin distinction or the existing auth flow.

## 6. Deliverable

A `.zip` of the updated `web_frontend/`-equivalent React project
(same `package.json` shape: `dev`/`build`/`preview`/`lint` scripts,
plain `vite`/`vite build`, no bundled server), containing the new
components described in Section 4 alongside everything already
working, all in the existing dark cyan/emerald glass aesthetic.
