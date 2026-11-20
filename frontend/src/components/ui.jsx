// Small shared presentational components.
import { useEffect } from 'react';
import { LEVEL_COLORS, SEVERITY_COLORS } from '../utils/format.js';

export function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#3987e5" />
      <path d="M7 21l5-6 4 3 6-8 3 3" stroke="white" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function LevelBadge({ level }) {
  return (
    <span className="badge">
      <span className="dot" style={{ background: LEVEL_COLORS[level] ?? '#8a8984' }} aria-hidden="true" />
      {level}
    </span>
  );
}

const SEVERITY_ICON = { critical: '▲', warning: '●', info: 'i' };

export function SeverityBadge({ severity }) {
  return (
    <span className="badge">
      <span className="severity-icon" style={{ color: SEVERITY_COLORS[severity] }} aria-hidden="true">
        {SEVERITY_ICON[severity]}
      </span>
      {severity}
    </span>
  );
}

const STATUS_LABEL = { firing: 'Firing', acknowledged: 'Acknowledged', resolved: 'Resolved' };
export function StatusPill({ status }) {
  return <span className={`pill pill-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function Panel({ title, actions, children, className = '' }) {
  return (
    <section className={`panel glass ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function ErrorBanner({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="banner banner-error" role="alert">
      <span>
        {error.message}
        {error.requestId && <span className="muted"> · request {error.requestId.slice(0, 8)}</span>}
      </span>
      {onRetry && (
        <button className="btn btn-ghost btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

export function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal glass ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="panel-head">
          <h2>{title}</h2>
          <button className="icon-btn sheet-close" onClick={onClose} aria-label="Close">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

// --- macOS chrome ------------------------------------------------------------------

/** Window controls. Decorative: the dashboard runs in a browser tab, not a native window. */
export function TrafficLights() {
  return (
    <div className="traffic-lights" aria-hidden="true">
      <span className="tl tl-close" />
      <span className="tl tl-min" />
      <span className="tl tl-max" />
    </div>
  );
}

// SF Symbols-style line icons (24px grid, 1.7 stroke).
const ICON_PATHS = {
  overview: 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z',
  explore: 'M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 20 20',
  live: 'M3 12h3l2.5-6 4 12 2.5-6H21',
  alerts: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2.2 2.2 0 0 0 4 0',
  rules: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4',
  logout: 'M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10',
  calendar: 'M5 6h14v14H5zM5 10h14M9 4v4M15 4v4',
  refresh: 'M19 12a7 7 0 1 1-2.05-4.95M19 4v4h-4',
  send: 'M4 12 20 4l-5 16-3-7z',
  arrow: 'M5 12h14M13 6l6 6-6 6',
};

export function Icon({ name, size = 18, className = '' }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

/** Fixed desktop wallpaper the glass refracts. Pure CSS - no image download. */
export function Wallpaper() {
  return (
    <div className="wallpaper" aria-hidden="true">
      <span className="blob blob-1" />
      <span className="blob blob-2" />
      <span className="blob blob-3" />
      <span className="blob blob-4" />
    </div>
  );
}
