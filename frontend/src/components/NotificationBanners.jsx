import { useCallback, useEffect, useRef, useState } from 'react';
import { navigate } from '../hooks/useData.js';
import { SEVERITY_COLORS } from '../utils/format.js';
import { Logo } from './ui.jsx';

const VISIBLE_MS = 7000;
const MAX_BANNERS = 3;

/**
 * macOS-style notification banners for alerts that opened since the page loaded.
 * Alerts already open on first load are treated as seen, so a refresh doesn't replay them.
 * When the tab is hidden and permission was granted, a system notification is shown too.
 */
export default function NotificationBanners({ alerts }) {
  const [banners, setBanners] = useState([]);
  const seen = useRef(null);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setBanners((list) => list.map((b) => (b.id === id ? { ...b, leaving: true } : b)));
    setTimeout(() => setBanners((list) => list.filter((b) => b.id !== id)), 260);
  }, []);

  const schedule = useCallback(
    (id) => {
      clearTimeout(timers.current.get(id));
      timers.current.set(id, setTimeout(() => dismiss(id), VISIBLE_MS));
    },
    [dismiss],
  );

  useEffect(() => {
    if (!alerts) return;
    if (seen.current === null) {
      seen.current = new Set(alerts.map((a) => a.id));
      return;
    }
    const fresh = alerts.filter((a) => a.status === 'firing' && !seen.current.has(a.id));
    alerts.forEach((a) => seen.current.add(a.id));
    if (!fresh.length) return;

    setBanners((list) => [...fresh.map((a) => ({ id: a.id, alert: a })), ...list].slice(0, MAX_BANNERS));
    fresh.forEach((a) => schedule(a.id));

    if (document.visibilityState === 'hidden' && 'Notification' in window && Notification.permission === 'granted') {
      fresh.forEach((a) => {
        const n = new Notification(`${a.severity.toUpperCase()} · InsightForge`, {
          body: a.summary,
          tag: a.fingerprint, // collapses repeats of the same alert
        });
        n.onclick = () => {
          window.focus();
          navigate('alerts');
          n.close();
        };
      });
    }
  }, [alerts, schedule]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  if (!banners.length) return null;
  return (
    <div className="banners" role="status" aria-live="polite">
      {banners.map(({ id, alert, leaving }) => (
        <div
          key={id}
          className={`banner-note glass ${leaving ? 'leaving' : ''}`}
          onMouseEnter={() => clearTimeout(timers.current.get(id))}
          onMouseLeave={() => schedule(id)}
        >
          <button
            className="banner-body"
            onClick={() => {
              navigate('alerts');
              dismiss(id);
            }}
          >
            <span className="banner-app">
              <Logo size={20} />
              <span>InsightForge</span>
              <span className="banner-time">now</span>
            </span>
            <span className="banner-title">
              <span className="banner-sev" style={{ color: SEVERITY_COLORS[alert.severity] }} aria-hidden="true">
                ●
              </span>
              {alert.severity === 'critical' ? 'Critical alert' : alert.severity === 'warning' ? 'Warning' : 'Alert'}
              {alert.service ? ` · ${alert.service}` : ''}
            </span>
            <span className="banner-text">{alert.summary}</span>
          </button>
          <button className="banner-close" onClick={() => dismiss(id)} aria-label="Dismiss notification">
            <svg width="8" height="8" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
