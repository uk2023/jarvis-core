import React, { useEffect, useState } from 'react';
import { Wifi, WifiOff } from 'lucide-react';
import { liveSync } from '../api/liveSync';
import { api } from '../api/client';

/**
 * A small, always-visible connection indicator, top-right -- UK's
 * explicit ask: know at a glance whether the live /ws link to JARVIS
 * is up, for both guest and admin. Quiet by design (a dot + label,
 * no modal, no sound) since this is ambient status, not an alert --
 * it only grows into a fuller toast-style message on the moment of
 * an actual state CHANGE (just connected / just disconnected), then
 * settles back to the quiet dot after a few seconds.
 */
export function WebSocketStatusIndicator() {
  const [connected, setConnected] = useState(false);
  const [justChanged, setJustChanged] = useState<'connected' | 'disconnected' | null>(null);

  useEffect(() => {
    liveSync.connect(api.getBackendUrl());

    const interval = setInterval(() => {
      setConnected((prevConnected) => {
        const nowConnected = liveSync.isConnected();
        if (nowConnected !== prevConnected) {
          setJustChanged(nowConnected ? 'connected' : 'disconnected');
          window.setTimeout(() => setJustChanged(null), 3000);
        }
        return nowConnected;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  const showLabel = justChanged !== null;

  return (
    <div
      className="fixed top-4 right-4 z-[100] flex items-center gap-2 pointer-events-none select-none"
      aria-live="polite"
    >
      <div
        className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-300 ${
          showLabel ? 'glass-panel-dark opacity-100' : 'opacity-70'
        }`}
        style={{
          borderColor: connected ? 'rgba(52, 211, 153, 0.35)' : 'rgba(241, 101, 101, 0.35)',
          backgroundColor: showLabel ? undefined : 'transparent',
        }}
      >
        <span className="relative flex h-2 w-2">
          {connected && (
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: 'var(--jarvis-success)' }}
            />
          )}
          <span
            className="relative inline-flex h-2 w-2 rounded-full"
            style={{ backgroundColor: connected ? 'var(--jarvis-success)' : 'var(--jarvis-danger)' }}
          />
        </span>
        {(showLabel || connected === false) && (
          <span className="flex items-center gap-1.5" style={{ color: connected ? 'var(--jarvis-success)' : 'var(--jarvis-danger)' }}>
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
            {justChanged === 'connected' && 'Connected'}
            {justChanged === 'disconnected' && 'Disconnected'}
            {!justChanged && !connected && 'Offline'}
          </span>
        )}
      </div>
    </div>
  );
}
