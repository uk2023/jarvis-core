import React, { useState, useRef, useEffect } from 'react';
import {
  Radio,
  CheckCircle2,
  ChevronRight,
  X,
} from 'lucide-react';
import { AppTheme, TurnTrace, SystemResourcesData } from '../types';
import { api } from '../api/client';
import { liveSync } from '../api/liveSync';

interface StatusNotificationPopoverProps {
  theme: AppTheme;
  isAdmin: boolean;
  onNavigateToTrace?: (turnId: string) => void;
}

export function StatusNotificationPopover({
  theme,
  isAdmin,
  onNavigateToTrace,
}: StatusNotificationPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [lastTrace, setLastTrace] = useState<TurnTrace | null>(null);
  const [resources, setResources] = useState<SystemResourcesData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const history = api.getHistory();
    if (history && history.length > 0) {
      setLastTrace(history[0].trace);
    }
    if (isOpen && isAdmin) {
      api.getResources().then(setResources).catch(() => setResources(null));
    }
  }, [isOpen, isAdmin]);

  useEffect(() => {
    liveSync.connect(api.getBackendUrl());
    const interval = setInterval(() => setIsConnected(liveSync.isConnected()), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleInspect = (turnId: string) => {
    setIsOpen(false);
    if (onNavigateToTrace) {
      onNavigateToTrace(turnId);
    }
  };

  const statusColor = isConnected ? 'var(--jarvis-success)' : 'var(--jarvis-danger)';

  return (
    <div className="relative" ref={popoverRef}>
      {/* A single glowing status button -- no "Online"/"Offline" text
          label on the collapsed trigger (UK's explicit ask). The
          glow/pulse itself communicates state; the word only appears
          inside the expanded popover where there's room to explain
          it properly. */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative w-9 h-9 rounded-full border flex items-center justify-center transition-colors"
        style={{
          backgroundColor: 'var(--jarvis-surface)',
          borderColor: isOpen ? statusColor : 'var(--jarvis-border)',
        }}
        title={isConnected ? 'Connected' : 'Disconnected'}
        aria-label={isConnected ? 'Connected' : 'Disconnected'}
      >
        {isConnected && (
          <span
            className="absolute inline-flex h-full w-full rounded-full animate-ping opacity-20"
            style={{ backgroundColor: statusColor }}
          />
        )}
        <Radio size={16} style={{ color: statusColor }} />
        <span
          className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2"
          style={{ backgroundColor: statusColor, borderColor: 'var(--jarvis-surface)' }}
        />
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs z-50 sm:hidden"
            onClick={() => setIsOpen(false)}
          />

          <div
            className="fixed sm:absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 sm:top-full sm:right-0 sm:left-auto sm:translate-x-0 sm:translate-y-0 sm:mt-2 w-[calc(100vw-2rem)] max-w-sm sm:w-96 rounded-2xl border shadow-2xl z-50 p-4 space-y-3.5 max-h-[85vh] overflow-y-auto"
            style={{ backgroundColor: 'var(--jarvis-surface-raised)', borderColor: 'var(--jarvis-border)' }}
          >
            <div className="flex items-center justify-between pb-2.5 border-b" style={{ borderColor: 'var(--jarvis-border)' }}>
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: 'var(--jarvis-accent-dim)' }}>
                  <Radio size={15} style={{ color: 'var(--jarvis-accent)' }} />
                </div>
                <div className="min-w-0">
                  <h3 className="font-semibold text-sm truncate">Connection</h3>
                  <p className="text-xs truncate" style={{ color: 'var(--jarvis-text-muted)' }}>
                    {isAdmin ? 'Live telemetry stream' : 'Real-time link'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 rounded-lg shrink-0 ml-2"
                style={{ color: 'var(--jarvis-text-muted)' }}
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-3 rounded-xl border flex items-center justify-between" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}>
              <span className="text-sm flex items-center gap-1.5" style={{ color: 'var(--jarvis-text)' }}>
                <Radio size={14} style={{ color: 'var(--jarvis-accent)' }} />
                Live channel
              </span>
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                style={{
                  backgroundColor: isConnected ? 'rgba(52,211,153,0.12)' : 'rgba(220,38,38,0.12)',
                  color: statusColor,
                }}
              >
                <CheckCircle2 size={11} />
                {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>

            {isAdmin && (
              <>
                {resources ? (
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="p-2 rounded-xl border" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}>
                      <div className="text-xs" style={{ color: 'var(--jarvis-text-muted)' }}>Memory</div>
                      <div className="text-sm font-semibold mt-0.5" style={{ color: 'var(--jarvis-accent-strong)' }}>
                        {Math.round(resources.process.max_rss_mb)} MB
                      </div>
                    </div>
                    <div className="p-2 rounded-xl border" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}>
                      <div className="text-xs" style={{ color: 'var(--jarvis-text-muted)' }}>LLM</div>
                      <div className="text-sm font-semibold mt-0.5" style={{ color: resources.llm.ready ? 'var(--jarvis-success)' : 'var(--jarvis-warning)' }}>
                        {resources.llm.ready ? 'Ready' : 'Down'}
                      </div>
                    </div>
                    <div className="p-2 rounded-xl border" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)' }}>
                      <div className="text-xs" style={{ color: 'var(--jarvis-text-muted)' }}>Facts learned</div>
                      <div className="text-sm font-semibold mt-0.5" style={{ color: 'var(--jarvis-accent-strong)' }}>
                        {resources.knowledge.accepted}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-center py-2" style={{ color: 'var(--jarvis-text-muted)' }}>Loading vitals...</div>
                )}

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-medium" style={{ color: 'var(--jarvis-text-muted)' }}>
                    <span className="flex items-center gap-1.5">Last turn</span>
                    {lastTrace?.turn_id && <span className="font-mono">#{lastTrace.turn_id}</span>}
                  </div>

                  {lastTrace ? (
                    <div className="p-3 rounded-xl border space-y-2 text-sm" style={{ backgroundColor: 'var(--jarvis-accent-dim)', borderColor: 'var(--jarvis-border)' }}>
                      <p className="line-clamp-2">{lastTrace.query}</p>
                      <div className="text-xs line-clamp-2 border-t pt-1.5" style={{ borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text-muted)' }}>
                        <span className="font-medium mr-1" style={{ color: 'var(--jarvis-accent-strong)' }}>JARVIS:</span>
                        {lastTrace.response_preview}
                      </div>
                      <div className="flex items-center justify-between pt-1 border-t text-xs" style={{ borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text-muted)' }}>
                        <span>Route: {lastTrace.cognitive_route?.mode || '—'}</span>
                        <span>{lastTrace.timings?.total?.toFixed(2) || '—'}s</span>
                      </div>
                      {lastTrace.turn_id && (
                        <button
                          onClick={() => handleInspect(lastTrace.turn_id!)}
                          className="w-full mt-1 py-1.5 px-3 rounded-lg font-medium text-xs flex items-center justify-center gap-1.5 transition-colors"
                          style={{ backgroundColor: 'var(--jarvis-accent)', color: 'white' }}
                        >
                          Inspect full trace
                          <ChevronRight size={14} />
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="p-3 rounded-xl border text-center text-xs" style={{ backgroundColor: 'var(--jarvis-surface)', borderColor: 'var(--jarvis-border)', color: 'var(--jarvis-text-muted)' }}>
                      No recent turns yet.
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
