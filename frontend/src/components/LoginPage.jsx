import { useEffect, useState } from 'react';
import { useAuth } from '../hooks/useAuth.jsx';
import { Icon, Logo } from './ui.jsx';

/** macOS lock-screen style sign-in. */
export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);
  const now = useClock();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.status === 401 ? 'Incorrect username or password' : err.message);
      setShake(true);
      setTimeout(() => setShake(false), 500);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="lock-clock" aria-hidden="true">
        <div className="lock-date">
          {now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
        </div>
        <div className="lock-time">
          {now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', hour12: false })}
        </div>
      </div>

      <form className={`login-card glass ${shake ? 'shake' : ''}`} onSubmit={submit}>
        <div className="login-avatar">
          <Logo size={56} />
        </div>
        <h1>InsightForge</h1>
        <p className="muted small">Sign in to your observability workspace</p>
        <label className="sr-only" htmlFor="login-user">Username</label>
        <input
          id="login-user"
          className="lock-input"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
          required
        />
        <div className="lock-password">
          <label className="sr-only" htmlFor="login-pass">Password</label>
          <input
            id="login-pass"
            className="lock-input"
            type="password"
            placeholder="Enter Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          <button className="lock-go" disabled={busy || !password} aria-label="Sign in">
            {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="arrow" size={16} />}
          </button>
        </div>
        <div className="lock-error" role="alert">{error}</div>
      </form>
    </div>
  );
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(t);
  }, []);
  return now;
}
