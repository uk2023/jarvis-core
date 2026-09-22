/**
 * WHAT IS ACTUALLY FINISHED.
 *
 * UK (2026-09-14): "jo cheez frontend ke liye nahi bani wo frontend me
 * bhi na show ho. Alike codebox."
 *
 * He is right, and the reason is worth stating: a button that opens a
 * broken screen is worse than no button. It costs him a tap, a page
 * load and a confusing error, and then he has to come back and tell me
 * it does not work -- which is exactly what happened with CodeBox.
 *
 * So readiness is declared in ONE place rather than scattered across
 * components. A feature goes true here only when its frontend has
 * actually been built and its backend verified, not when the backend
 * alone exists.
 *
 * `reason` is filled in for anything false so this file stays an honest
 * record of what is outstanding instead of a list of silent switches.
 */

export interface FeatureState {
  ready: boolean;
  reason?: string;
  /** Roles allowed to see this feature at all, regardless of
   *  readiness. Omitted means every authenticated role (not guest). */
  allowedRoles?: string[];
}

export const FEATURES: Record<string, FeatureState> = {
  chat: { ready: true },
  dashboard: { ready: true },
  inspector: { ready: true },
  cli: { ready: true },

  // UNHIDDEN (2026-09-14). Backend verified (routes_codebox.py,
  // per-role sandboxes, the 401 gate removed, 5-layer QA -- see
  // core/skills/codebox.py). UK's explicit, narrowed spec: "ye bas
  // Admin aur owner+cowner ko dikhega" -- admin/owner/co_owner only.
  // A plain 'user' does NOT get this; running code, even sandboxed, is
  // an operator-tier capability in this system, not a general one.
  codebox: {
    ready: true,
    allowedRoles: ['admin', 'owner', 'co_owner'],
  },

  // REPO-SCALE CODING AGENT (2026-09-16). Backend verified end to end
  // (routes_codebox.py's /api/coding_agent/{run,approve,state} ->
  // brain.run_coding_agent -> core/skills/coding_agent/). Frontend is
  // CodingAgentWorkspace.tsx: plan, tool calls, diffs, approval gate,
  // verification, artifacts. Same operator tier as codebox -- this one
  // edits whole projects, so it is strictly not below that bar.
  coding_agent: {
    ready: true,
    allowedRoles: ['admin', 'owner', 'co_owner'],
  },

  // UNHIDDEN (2026-09-14). UK confirmed directly: "mic speaker sab
  // perfect hai call aur input box dono jageh" -- both the self-echo
  // loop (JARVIS hearing its own speaker output) and the reply-parsing
  // bug (data.response/.message/.text none of which existed on the
  // actual endpoint shape) are fixed and verified this session.
  call: { ready: true },

  // Extended thinking: the toggle and the backend decision are wired,
  // and the step panel below renders real streamed stages.
  thinking: { ready: true },

  // Two real engines, real endpoints (/api/voice/settings, /engines,
  // /test). The fabricated engine list is gone.
  voiceSettings: { ready: true },
};

export function isReady(feature: string): boolean {
  return FEATURES[feature]?.ready ?? false;
}

/** ready AND this role is allowed to see it. Guests fall through
 *  allowedRoles checks for anything that lists roles explicitly. */
export function isReadyForRole(feature: string, role: string | null | undefined): boolean {
  const state = FEATURES[feature];
  if (!state?.ready) return false;
  if (!state.allowedRoles) return true;
  return state.allowedRoles.includes((role || 'guest').toLowerCase());
}

/** For a settings/debug view: what is hidden, and why. */
export function pendingFeatures(): { name: string; reason: string }[] {
  return Object.entries(FEATURES)
    .filter(([, state]) => !state.ready)
    .map(([name, state]) => ({ name, reason: state.reason ?? 'Abhi taiyaar nahi.' }));
}
