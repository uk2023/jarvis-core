/**
 * ROUTES BY ROLE -- and why usernames never appear in one.
 *
 * UK's requirement: owner and co-owner share /owner; admins sit under
 * /admin/<id>; users get an opaque path; guests keep the plain session.
 * The stated reason is the right one -- "username expose nahi karna".
 *
 * So the per-session id is NOT derived from the username. Not hashed
 * from it either: a hash of a short username is trivially reversed by
 * hashing a wordlist, so it would leak exactly what it was meant to
 * hide. It is random per session, stored alongside the session token,
 * and means nothing on its own.
 *
 * WHAT THESE PATHS ARE AND ARE NOT
 * ================================
 * They are organisation and privacy: a shoulder-surfer or a screenshot
 * does not reveal who is logged in. They are NOT access control. Every
 * privileged action is checked server-side against the session token's
 * role, and that check is what actually protects anything. Anyone can
 * type /owner into a browser; they will get the login form and nothing
 * else. Treating a URL as a secret is how people end up with a weak
 * password behind a "hidden" page.
 */

export type Role = 'owner' | 'co_owner' | 'admin' | 'user' | 'guest';

const SESSION_PATH_KEY = 'jarvis_session_path';

/** Opaque, random, meaningless. Regenerated per session. */
function makeOpaqueId(length = 14): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = new Uint8Array(length);
  (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}

/**
 * The path this session should live at. Stable for the session (stored),
 * so a refresh does not shuffle the URL.
 */
export function sessionPathFor(role: Role): string {
  if (role === 'owner' || role === 'co_owner') return '/owner';
  if (role === 'guest') return '/';

  let id: string | null = null;
  try {
    id = sessionStorage.getItem(SESSION_PATH_KEY);
  } catch {
    /* private mode -- fall back to a fresh id each load */
  }
  if (!id) {
    id = makeOpaqueId();
    try { sessionStorage.setItem(SESSION_PATH_KEY, id); } catch { /* ignore */ }
  }

  return role === 'admin' ? `/admin/${id}` : `/${id}`;
}

export function clearSessionPath(): void {
  try { sessionStorage.removeItem(SESSION_PATH_KEY); } catch { /* ignore */ }
}

/** True when the current URL is the owner entrance. */
export function isOwnerRoute(): boolean {
  return window.location.pathname.replace(/\/+$/, '') === '/owner';
}

/**
 * Put the session path in the address bar without a page load.
 * Purely cosmetic -- nothing reads it back to decide permissions.
 */
export function applySessionPath(role: Role): void {
  try {
    const path = sessionPathFor(role);
    if (window.location.pathname !== path) {
      window.history.replaceState({}, '', path);
    }
  } catch {
    /* history API unavailable -- the app works regardless */
  }
}
