/**
 * ROLE-SCOPED ROUTES.
 *
 * UK's scheme (2026-09-14):
 *
 *     /owner/<uniqueid>
 *     /cowner/<uniqueid>
 *     /admin/<uniqueid>
 *     /<uniqueid>                 normal user
 *     /guest/<tempuniqueid>
 *
 * Owner and co-owner share the same LOGIN SCREEN but land on different
 * path prefixes, which is what he asked for: one UI, two routes.
 *
 * THE ID IS RANDOM, NOT DERIVED
 * =============================
 * It is not the username, and it is not a hash of the username either.
 * Hashing a short username is reversible in seconds against a wordlist,
 * so it would leak precisely the thing the scheme exists to hide. The
 * id is random per session and means nothing on its own.
 *
 * Guest ids are marked temporary and live in sessionStorage only, so
 * they die with the tab -- a guest session is not supposed to be
 * resumable.
 *
 * WHAT THESE PATHS ARE NOT
 * ========================
 * They are not access control, and it matters that this is stated
 * rather than assumed. Anyone can type /owner/anything into a browser.
 * They will get the owner LOGIN FORM and nothing else. Every privileged
 * action is checked server-side against the session token's role --
 * that check is the security. The URL is organisation and privacy: a
 * screenshot or a shoulder-glance does not reveal who is logged in.
 */

export type Role = 'owner' | 'co_owner' | 'admin' | 'user' | 'guest';

const PERSISTENT_ID_KEY = 'jarvis_route_id';
const GUEST_ID_KEY = 'jarvis_guest_route_id';

const ROLE_PREFIX: Record<Role, string> = {
  owner: '/owner',
  co_owner: '/cowner',
  admin: '/admin',
  user: '',
  guest: '/guest',
};

function randomId(length = 14): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = new Uint8Array(length);
  (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}

function readOrCreate(key: string): string {
  try {
    const existing = sessionStorage.getItem(key);
    if (existing) return existing;
    const fresh = randomId();
    sessionStorage.setItem(key, fresh);
    return fresh;
  } catch {
    // Private mode: a fresh id each load is fine, it is only cosmetic.
    return randomId();
  }
}

export function routeIdFor(role: Role): string {
  return readOrCreate(role === 'guest' ? GUEST_ID_KEY : PERSISTENT_ID_KEY);
}

/** The path this session should sit at. */
export function pathFor(role: Role): string {
  const prefix = ROLE_PREFIX[role] ?? '';
  return `${prefix}/${routeIdFor(role)}`;
}

/** Which login screen the current URL is asking for, if any. */
export function loginRouteFromPath(): 'owner' | null {
  const path = window.location.pathname.replace(/\/+$/, '');
  // Owner and co-owner share one login UI, so both prefixes lead to it.
  if (/^\/owner(\/|$)/.test(path) || /^\/cowner(\/|$)/.test(path)) return 'owner';
  return null;
}

/** True if the path already matches what this role should be on. */
export function pathMatchesRole(role: Role): boolean {
  const path = window.location.pathname.replace(/\/+$/, '');
  const prefix = ROLE_PREFIX[role] ?? '';
  if (!prefix) {
    // Normal user: /<id> -- a single segment that is not a known prefix.
    const segments = path.split('/').filter(Boolean);
    return segments.length === 1 && !['owner', 'cowner', 'admin', 'guest'].includes(segments[0]);
  }
  return path.startsWith(`${prefix}/`);
}

/**
 * Put the session on its proper path without a page load.
 * Purely cosmetic -- nothing reads it back to decide permissions.
 */
export function applyRoutePath(role: Role): void {
  try {
    if (pathMatchesRole(role)) return;
    window.history.replaceState({}, '', pathFor(role));
  } catch {
    /* history API unavailable; the app works regardless */
  }
}

export function clearRouteIds(): void {
  try {
    sessionStorage.removeItem(PERSISTENT_ID_KEY);
    sessionStorage.removeItem(GUEST_ID_KEY);
  } catch {
    /* nothing to clear */
  }
}
