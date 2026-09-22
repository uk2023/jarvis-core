import { useState, useRef, useEffect } from 'react';
import { Brain, Check, Gauge } from 'lucide-react';

/**
 * BRAIN ICON MENU -- extended thinking + effort, in one place.
 *
 * UK: "Brain icon pe click karo to extended thinking option aur effort
 * collapse/expand menu appear ho jaaye jaha inhe choose kar sakein."
 * And separately: "multi-turn/step-turn sab extended thinking se hi
 * hoga on karne pe. Effort 5 level: low, medium, high, aggressive,
 * deep."
 *
 * So this is ONE menu, not two features glued together: turning
 * thinking on and picking an effort level are the same click surface,
 * because task_loop.py and thinking.py are now driven by the same
 * effort dial on the backend (see effort_levels.py). Picking "deep"
 * here means deeper reasoning stages AND more thorough multi-step task
 * completion, together -- that pairing is the whole point of the
 * unification UK asked for.
 */

export type ThinkingMode = 'normal' | 'extended';
export type EffortLevel = 'low' | 'medium' | 'high' | 'aggressive' | 'deep';

const EFFORT_ORDER: EffortLevel[] = ['low', 'medium', 'high', 'aggressive', 'deep'];

// TWO MODES, NO AUTO (2026-09-16, UK: "auto mechanism ko off karo,
// wahan par keval do hi option honge -- Normal aur Extended Thinking").
//
// Auto is gone for a concrete reason, not just because he asked: it
// made the system's behaviour unpredictable from the outside. UK would
// send a message and could not tell in advance whether it would take
// one turn or ten, because a classifier decided for him. Two explicit
// modes mean the cost of a message is a choice he makes, not one made
// for him.
//
//   Normal    -- exactly one turn. Answer and stop.
//   Extended  -- multi-turn: plan, act, verify, and carry the task to
//                a conclusion. This is where the effort dial applies.
const MODE_META: Record<ThinkingMode, { label: string; note: string }> = {
  normal: { label: 'Normal', note: 'Ek turn -- seedha jawab' },
  extended: { label: 'Extended Thinking', note: 'Multi-turn -- plan, kaam, verify' },
};

const EFFORT_META: Record<EffortLevel, { label: string; note: string }> = {
  low: { label: 'Low', note: 'Sabse tez, ek hi pass' },
  medium: { label: 'Medium', note: 'Thodi soch, default' },
  high: { label: 'High', note: 'Options explore + ek retry' },
  aggressive: { label: 'Aggressive', note: 'Poora thinking cycle' },
  deep: { label: 'Deep', note: 'Sabse dheema, sab explicit' },
};

export default function EffortMenu({
  thinkingMode,
  onThinkingModeChange,
  effort,
  onEffortChange,
  isDark = true,
}: {
  thinkingMode: ThinkingMode;
  onThinkingModeChange: (m: ThinkingMode) => void;
  effort: EffortLevel;
  onEffortChange: (e: EffortLevel) => void;
  isDark?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, [open]);

  const active = thinkingMode === 'extended';

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Thinking mode aur effort"
        aria-expanded={open}
        title={
          thinkingMode === 'normal'
            ? 'Normal -- ek turn'
            : `Extended Thinking -- effort: ${EFFORT_META[effort].label}`
        }
        className={`jarvis-composer-icon ${active ? 'is-active' : ''}`}
      >
        <Brain size={16} />
      </button>

      {open && (
        <div
          role="menu"
          className={`jarvis-effort-menu ${isDark ? 'is-dark' : 'is-light'}`}
        >
          <div className="jarvis-effort-menu-section">
            <p className="jarvis-effort-menu-title">Mode</p>
            {(['normal', 'extended'] as ThinkingMode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="menuitemradio"
                aria-checked={thinkingMode === m}
                className="jarvis-effort-menu-row jarvis-effort-level-row"
                onClick={() => onThinkingModeChange(m)}
              >
                <span className="jarvis-effort-level-label">
                  {MODE_META[m].label}
                  <span className="jarvis-effort-level-note">{MODE_META[m].note}</span>
                </span>
                {thinkingMode === m && <Check size={13} />}
              </button>
            ))}
          </div>

          <div className="jarvis-effort-menu-divider" />

          <div className="jarvis-effort-menu-section">
            <p className="jarvis-effort-menu-title">
              <Gauge size={11} style={{ marginRight: 4, verticalAlign: -2 }} />
              Effort {thinkingMode === 'normal' && (
                <span className="jarvis-effort-disabled-note">(Extended Thinking ke liye)</span>
              )}
            </p>
            {EFFORT_ORDER.map((level) => (
              <button
                key={level}
                type="button"
                role="menuitemradio"
                aria-checked={effort === level}
                disabled={thinkingMode === 'normal'}
                className="jarvis-effort-menu-row jarvis-effort-level-row"
                onClick={() => onEffortChange(level)}
              >
                <span className="jarvis-effort-level-label">
                  {EFFORT_META[level].label}
                  <span className="jarvis-effort-level-note">{EFFORT_META[level].note}</span>
                </span>
                {effort === level && <Check size={13} />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
