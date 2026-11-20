import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../hooks/useAuth.jsx';
import { useData } from '../hooks/useData.js';
import { useTimeRange } from '../hooks/useTimeRange.js';
import { TIME_RANGES } from '../utils/format.js';
import CommandPalette, { shortcutLabel } from './CommandPalette.jsx';
import NotificationBanners from './NotificationBanners.jsx';
import { Icon, Logo, TrafficLights } from './ui.jsx';

const NAV = [
  { section: 'Monitor' },
  { page: 'overview', label: 'Overview', icon: 'overview', subtitle: 'Volume, error rate and service health' },
  { page: 'explore', label: 'Explore', icon: 'explore', subtitle: 'Search and filter every log' },
  { page: 'live', label: 'Live Tail', icon: 'live', subtitle: 'Logs as they arrive' },
  { section: 'Alerting' },
  { page: 'alerts', label: 'Alerts', icon: 'alerts', subtitle: 'Firing, acknowledged and resolved' },
  { page: 'rules', label: 'Rules', icon: 'rules', subtitle: 'Conditions and notification channels' },
];

const REFRESH = [
  { value: 0, label: 'Off' },
  { value: 5000, label: '5s' },
  { value: 10000, label: '10s' },
  { value: 30000, label: '30s' },
  { value: 60000, label: '1m' },
];

export default function Layout({ page, children }) {
  const { user, logout, isAdmin, authDisabled } = useAuth();
  const { range, setRange, refreshMs, setRefreshMs } = useTimeRange();
  const openAlerts = useData((signal) => api('/api/v1/alerts', { params: { size: 50 }, signal }), [], {
    interval: 10000,
  });
  const count = openAlerts.data?.total ?? 0;
  const current = NAV.find((n) => n.page === page);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // ⌘K / Ctrl+K toggles the palette; "/" opens it when you're not typing somewhere.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (e.key === '/' && !e.target.closest?.('input, textarea, select, [contenteditable]')) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar glass">
        <TrafficLights />
        <a className="brand" href="#/overview">
          <Logo size={26} />
          <span>InsightForge</span>
        </a>
        <nav aria-label="Main">
          {NAV.map((item) =>
            item.section ? (
              <div key={item.section} className="nav-section">
                {item.section}
              </div>
            ) : (
              <a
                key={item.page}
                href={`#/${item.page}`}
                className={`nav-item ${page === item.page ? 'active' : ''}`}
                aria-current={page === item.page ? 'page' : undefined}
              >
                <Icon name={item.icon} className="nav-icon" />
                {item.label}
                {item.page === 'alerts' && count > 0 && <span className="nav-count">{count}</span>}
              </a>
            ),
          )}
        </nav>
        <div className="sidebar-foot">
          <div className="avatar" aria-hidden="true">
            {user.username.slice(0, 1).toUpperCase()}
          </div>
          <div className="user-meta">
            <div className="user-name">{user.username}</div>
            <div className="muted small">{user.role === 'admin' ? 'Administrator' : 'Viewer'}</div>
          </div>
          {!authDisabled && (
            <button className="icon-btn" onClick={logout} title="Sign out" aria-label="Sign out">
              <Icon name="logout" size={17} />
            </button>
          )}
        </div>
      </aside>

      <div className="main">
        <header className="toolbar">
          <div className="toolbar-title">
            <h1>{current?.label}</h1>
            <span className="muted small">{current?.subtitle}</span>
          </div>
          <div className="toolbar-groups">
            <button className="capsule glass search-capsule" onClick={() => setPaletteOpen(true)}>
              <Icon name="explore" size={15} />
              <span>Search</span>
              <kbd>{shortcutLabel}</kbd>
            </button>
            {isAdmin && <TestLogMenu />}
            {page !== 'live' && page !== 'rules' && (
              <div className="capsule glass">
                <label className="capsule-field">
                  <Icon name="calendar" size={15} />
                  <span className="sr-only">Time range</span>
                  <select value={range} onChange={(e) => setRange(e.target.value)}>
                    {TIME_RANGES.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="capsule-divider" aria-hidden="true" />
                <label className="capsule-field" title="Auto-refresh">
                  <Icon name="refresh" size={15} />
                  <span className="sr-only">Auto-refresh</span>
                  <select value={refreshMs} onChange={(e) => setRefreshMs(Number(e.target.value))}>
                    {REFRESH.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <NotificationBanners alerts={openAlerts.data?.items} />
    </div>
  );
}

/** The original UI tester, kept for demos: inject a log at a chosen level. */
function TestLogMenu() {
  const [status, setStatus] = useState(null);
  const send = async (level) => {
    try {
      await api('/api/v1/logs', {
        method: 'POST',
        body: { level, service: 'dashboard-test', message: `Test ${level} log sent from the dashboard` },
      });
      setStatus(`Sent ${level}`);
    } catch (err) {
      setStatus(err.message);
    }
    setTimeout(() => setStatus(null), 2000);
  };
  return (
    <div className="capsule glass" role="group" aria-label="Send a test log">
      <span className="capsule-label">
        <Icon name="send" size={14} />
        {status ?? 'Test log'}
      </span>
      {['INFO', 'WARN', 'ERROR', 'CRITICAL'].map((level) => (
        <button key={level} className="capsule-btn" onClick={() => send(level)}>
          {level}
        </button>
      ))}
    </div>
  );
}
