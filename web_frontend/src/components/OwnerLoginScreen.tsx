import { useState } from 'react';
import { ShieldCheck, Loader2, AlertTriangle, ArrowRight } from 'lucide-react';
import { api } from '../api/client';
import '../styles/jarvis-owner.css';

/**
 * OWNER / CO-OWNER LOGIN -- its own screen, at its own route.
 *
 * WHY SEPARATE
 * ============
 * The public AuthModal carries signup, and signup enforces a
 * three-character minimum username. The owner account is "uk". So the
 * form UK needed most was the one form he could not submit -- it
 * rejected his username before the request ever left the browser.
 *
 * There is no signup here, because owner and co-owner accounts are not
 * created through the web at all. They are created from the machine
 * itself (setup_owner.py, or /owner in cli.py). Anything that could
 * mint an owner over HTTP would be the single most valuable target in
 * the system.
 *
 * A NOTE ON THE ROUTE
 * ===================
 * This lives at /owner, which is a discoverable path. That is worth
 * being clear about rather than pretending otherwise: the route is
 * organisation, not security. What actually protects the account is the
 * password hash (PBKDF2, 200k iterations), the rate limiter, and the
 * fact that no signup path can produce this role. A secret URL adds
 * nothing on top of those, and believing it does is how people end up
 * with a weak password behind a "hidden" page.
 */

interface Props {
  onAuthenticated: (user: { username: string; role: string; display_name?: string }) => void;
  onBack?: () => void;
}

export default function OwnerLoginScreen({ onAuthenticated, onBack }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!username.trim() || !password) {
      setError('Username aur password dono chahiye.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username.trim(), password);
      if (result?.role !== 'owner' && result?.role !== 'co_owner') {
        // A normal account logging in here is not an error worth
        // punishing -- but this screen is not their entrance.
        setError('Yeh account owner ya co-owner nahi hai. Normal login use karo.');
        setBusy(false);
        return;
      }
      onAuthenticated(result);
    } catch (err: any) {
      // Deliberately the same message for unknown user and wrong
      // password -- distinguishing them lets someone enumerate which
      // accounts exist.
      setError(err?.message?.includes('429')
        ? 'Bahut zyada attempts. Thodi der baad try karo.'
        : 'Username ya password galat hai.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="jarvis-owner-screen">
      <div className="jarvis-owner-card">
        <div className="jarvis-owner-badge">
          <ShieldCheck size={22} />
        </div>

        <h1 className="jarvis-owner-title">Owner Access</h1>
        <p className="jarvis-owner-sub">Owner aur co-owner ke liye</p>

        <label className="jarvis-owner-field">
          <span>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="uk"
            disabled={busy}
          />
        </label>

        <label className="jarvis-owner-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            autoComplete="current-password"
            disabled={busy}
          />
        </label>

        {error && (
          <p className="jarvis-owner-error">
            <AlertTriangle size={13} /> {error}
          </p>
        )}

        <button className="jarvis-owner-submit" onClick={submit} disabled={busy}>
          {busy ? <Loader2 size={16} className="jarvis-spin" /> : <ArrowRight size={16} />}
          {busy ? 'Check kar raha hun...' : 'Login'}
        </button>

        <p className="jarvis-owner-hint">
          Account nahi bana? Device pe chalao:
          <code>python3 setup_owner.py</code>
          Owner account web se nahi banta — jaan-boojh kar.
        </p>

        {onBack && (
          <button className="jarvis-owner-back" onClick={onBack}>
            Normal login
          </button>
        )}
      </div>
    </div>
  );
}
