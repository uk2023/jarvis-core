# JARVIS Organism -- Web Frontend (V6)

React + TypeScript + Vite UI for the JARVIS Organism backend
(`backend/server.py`, FastAPI). This replaces the old Node/Express
mock server entirely -- every endpoint it calls now hits the real
organism (see `backend/routes_frontend_v6.py`).

## Getting a fresh AI Studio export into this folder

If you're iterating on the UI in AI Studio and bringing a new export
back here: **you can copy almost everything from the export straight
over this folder's `src/` and `index.html`.** The frontend now
connects to the backend directly by hostname:8000 (see
`src/api/client.ts`'s `computeDefaultBackendUrl()`), not through any
Vite proxy config -- so `vite.config.ts` no longer needs any
project-specific customization to keep working.

**One thing to check by hand each time** (this is a single line, not
a script): AI Studio's own `package.json` has `"dev": "tsx server.ts"`
-- that launches AI Studio's OWN standalone Express demo server, not
Vite. If you copy AI Studio's `package.json` over this one, open it
and make sure the `dev` script says:
```json
"dev": "vite"
```
Everything else in `package.json` (dependencies, `build`/`preview`/
`lint`) can be safely taken from the fresh export.

`src/api/client.ts` specifically also carries a handful of methods
this project's real backend depends on that AI Studio doesn't know
about (`sendCliCommand`, `getResources`, the voice settings methods,
`getSafetyHistory`) -- if a fresh export's `client.ts` is missing
them, the Virtual CLI's `/commands`, the voice control panel, and the
diagnostics panel will silently stop working. Worth a quick search
for `sendCliCommand` in the new file before replacing the old one.

## Dev (hot reload)

```bash
cd web_frontend
npm install
npm run dev
```

Start the Python backend first (`python3 cli.py`, option 2 or 3),
then `npm run dev` here and edit components -- changes appear
instantly, no rebuild. If the backend is running on a different
machine (e.g. your Android device while you develop from a laptop),
open the app once and call `api.setBackendUrl('http://<that-machine>:8000')`
from the browser console, or set `VITE_BACKEND_URL` and rebuild.

## Production build

```bash
cd web_frontend
npm install
npm run build
```

This outputs straight into `../frontend/dist_v6`. The backend
(`backend/routes_http.py`) automatically serves that build at `/`
once it exists -- no copy step, no separate server process. If the
build doesn't exist yet, the backend falls back to the legacy static
dashboard in `frontend/`.

## What talks to what

Every network call this app makes lives in `src/api/client.ts`. No
other component touches the network directly. Endpoints:

| Endpoint | Real data source |
|---|---|
| `GET /api/organism/state` | heartbeat, Brain.status(), all attached organs |
| `GET/POST/DELETE /api/memory/engrams` | `SemanticMemory` (FAISS + SQLite) |
| `GET/POST /api/autonomy/state`, `/trigger-idle` | `GoalManager`, `Curiosity`, `IdleLoop`, `EvolutionEngine` |
| `POST /api/chat` | `Brain.think_and_respond()` -- same pipeline as the CLI and `/ws` |
| `POST /api/cli_command` | `cli.py`'s own `handle_cli_command()`, output captured live |
| `GET/POST /api/voice/*` | `core/runtime/voice.py` (real Termux:API TTS/STT) |
| `GET /api/resources`, `/api/health` | `backend/routes_frontend_v6_extra.py` |
| `GET/POST /api/sessions`, `GET /api/history` | `backend/database.py` (SQLite chat history) |
