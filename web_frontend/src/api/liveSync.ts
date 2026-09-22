// Real-time sync with the backend's /ws endpoint -- the actual, missing
// piece behind "Virtual CLI should sync with the terminal, no latency,
// same result". Every component that wants live push updates (a
// terminal-originated chat turn, a pulse/heartbeat tick, a system
// toast) subscribes here instead of each opening its own socket --
// ONE shared connection, many listeners.
//
// Backend counterpart: backend/routes_ws.py's /ws endpoint. Terminal-
// originated turns broadcast {"type":"chat_response", sender:"jarvis",
// text, session_id, timestamp, source:"cli"|"web"} -- the exact same
// shape whether the turn came from the terminal or another browser
// tab, so a listener never needs to special-case the source.

export interface LiveSyncMessage {
  type: string;
  [key: string]: any;
}

type Listener = (msg: LiveSyncMessage) => void;

class LiveSyncClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelayMs = 1000;
  private manuallyClosed = false;
  private lastBaseUrl: string | null = null;

  connect(baseUrl: string) {
    this.manuallyClosed = false;
    this.lastBaseUrl = baseUrl;
    this._open(baseUrl);
    this._ensureVisibilityListener();
  }

  // CHROME MINIMIZE FIX (2026-09-12, UK's explicit bug report: "chrome
  // minimise hota hai to session disconnect ho jata hai, phir kholta
  // hu to lag/refresh ho jata hai"). Android Chrome throttles or fully
  // suspends background tabs, which silently kills the WebSocket
  // without firing onclose promptly -- the existing exponential
  // backoff (up to 15s) would otherwise leave the app looking "stuck"
  // for several seconds after returning to the tab. Reacting directly
  // to visibilitychange forces an immediate reconnect attempt instead
  // of waiting out whatever backoff delay happened to be in flight
  // when the tab was backgrounded.
  private _visibilityListenerAttached = false;
  private _ensureVisibilityListener() {
    if (this._visibilityListenerAttached || typeof document === 'undefined') return;
    this._visibilityListenerAttached = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible' || this.manuallyClosed || !this.lastBaseUrl) return;
      if (this.isConnected()) return;
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      this.reconnectDelayMs = 1000; // fresh attempt, not whatever backoff had grown to
      this._open(this.lastBaseUrl);
    });
  }

  private _open(baseUrl: string) {
    const wsUrl = `${(baseUrl || window.location.origin).replace(/^http/, 'ws').replace(/\/+$/, '')}/ws`;
    try {
      this.ws = new WebSocket(wsUrl);
    } catch {
      this._scheduleReconnect(baseUrl);
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelayMs = 1000; // reset backoff on a successful connect
    };

    this.ws.onmessage = (event) => {
      let data: LiveSyncMessage;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data.type === 'ping' || data.type === 'pong') return;
      this.listeners.forEach((fn) => {
        try {
          fn(data);
        } catch {
          // one bad listener must never break delivery to the others
        }
      });
    };

    this.ws.onclose = () => {
      if (!this.manuallyClosed) this._scheduleReconnect(baseUrl);
    };

    this.ws.onerror = () => {
      try {
        this.ws?.close();
      } catch {}
    };
  }

  private _scheduleReconnect(baseUrl: string) {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 1.5, 15000);
      this._open(baseUrl);
    }, this.reconnectDelayMs);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  disconnect() {
    this.manuallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }
}

// One shared instance for the whole app -- every screen that mounts
// just subscribes/unsubscribes, it never owns the socket itself.
export const liveSync = new LiveSyncClient();
