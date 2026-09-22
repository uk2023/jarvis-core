import { useState, useRef, useEffect } from 'react';
import { User, Settings, LogIn, LogOut, ShieldCheck, Users, Crown, UserCog } from 'lucide-react';

/**
 * PROFILE DROPDOWN -- one click surface for identity, settings, logout.
 *
 * UK's report and request, combined:
 *   - "sidebar mein sirf Login button hai" -- true for a guest, but
 *     there was NO logout anywhere for a logged-in user or admin. The
 *     onLogout prop existed on the sidebar component and was never
 *     rendered -- a real "built but never wired" case.
 *   - "login button ko profile pe click karne se hona chahiye jahan
 *     profile settings aur logout dono ho" -- so this replaces the
 *     bare Login button with a click-triggered dropdown on the avatar
 *     itself, for EVERY state (guest, user, admin, owner, co-owner).
 *   - "guest/user/admin/owner ka current status yahan show hona
 *     chahiye" -- the role badge and label are read from the real
 *     session, not inferred from a single isAdmin boolean.
 *
 * ONE COMPONENT, ALL FIVE ROLES. The previous footer only distinguished
 * "admin" vs "guest" -- co-owner, plain user and the actual owner all
 * collapsed into one of those two buckets. This reads the real role
 * string and renders the right label, icon and action set for each.
 */

export type SessionRole = 'owner' | 'co_owner' | 'admin' | 'user' | 'guest';

interface ProfileDropdownProps {
  role: SessionRole;
  displayName?: string | null;
  onOpenAuth?: () => void;      // guest -> login
  onOpenSettings?: () => void;  // profile settings
  onLogout?: () => void;        // any authenticated role -> logout
}

const ROLE_META: Record<SessionRole, { label: string; icon: any; tone: string }> = {
  owner: { label: 'Owner', icon: Crown, tone: 'owner' },
  co_owner: { label: 'Co-Owner', icon: Crown, tone: 'owner' },
  admin: { label: 'Admin', icon: UserCog, tone: 'admin' },
  user: { label: 'User', icon: ShieldCheck, tone: 'user' },
  guest: { label: 'Guest', icon: Users, tone: 'guest' },
};

export default function ProfileDropdown({
  role,
  displayName,
  onOpenAuth,
  onOpenSettings,
  onLogout,
}: ProfileDropdownProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const isGuest = role === 'guest';
  const meta = ROLE_META[role] ?? ROLE_META.guest;
  const RoleIcon = meta.icon;

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, [open]);

  const name = displayName || (isGuest ? 'Guest User' : meta.label);

  return (
    <div ref={rootRef} className="jarvis-profile-root">
      <button
        type="button"
        className={`jarvis-profile-trigger jarvis-profile-tone-${meta.tone}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Profile"
      >
        <span className="jarvis-profile-avatar">
          <User size={14} />
          <span className="jarvis-profile-dot" />
        </span>
        <span className="jarvis-profile-text">
          <span className="jarvis-profile-name">{name}</span>
          <span className="jarvis-profile-role">
            <RoleIcon size={9} /> {meta.label.toUpperCase()}
          </span>
        </span>
      </button>

      {open && (
        <div role="menu" className="jarvis-profile-menu">
          <div className="jarvis-profile-menu-header">
            <span className={`jarvis-profile-status-badge jarvis-profile-tone-${meta.tone}`}>
              <RoleIcon size={11} /> {meta.label}
            </span>
            <span className="jarvis-profile-menu-name">{name}</span>
          </div>

          <div className="jarvis-profile-menu-divider" />

          {isGuest ? (
            <button
              type="button"
              role="menuitem"
              className="jarvis-profile-menu-row jarvis-profile-menu-primary"
              onClick={() => { setOpen(false); onOpenAuth?.(); }}
            >
              <LogIn size={14} /> Login
            </button>
          ) : (
            <>
              <button
                type="button"
                role="menuitem"
                className="jarvis-profile-menu-row"
                onClick={() => { setOpen(false); onOpenSettings?.(); }}
              >
                <Settings size={14} /> Profile Settings
              </button>
              <button
                type="button"
                role="menuitem"
                className="jarvis-profile-menu-row jarvis-profile-menu-danger"
                onClick={() => { setOpen(false); onLogout?.(); }}
              >
                <LogOut size={14} /> Logout
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
