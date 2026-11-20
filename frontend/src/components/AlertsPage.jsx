import { useState } from 'react';
import { api } from '../api/client.js';
import { navigate, useData } from '../hooks/useData.js';
import { useTimeRange } from '../hooks/useTimeRange.js';
import { formatNumber, formatRelative, formatTime } from '../utils/format.js';
import { Empty, ErrorBanner, Panel, SeverityBadge, StatusPill } from './ui.jsx';

const TABS = [
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
];

export default function AlertsPage() {
  const { refreshMs } = useTimeRange();
  const [tab, setTab] = useState('open');
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const alerts = useData(
    (signal) => api('/api/v1/alerts', { params: { status: tab, size: 200 }, signal }),
    [tab],
    { interval: refreshMs },
  );

  const act = async (alert, action) => {
    setBusy(alert.id);
    setActionError(null);
    try {
      await api(`/api/v1/alerts/${alert.id}/${action}`, { method: 'POST' });
      alerts.reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  };

  const items = alerts.data?.items ?? [];
  const [permission, setPermission] = useState(() => ('Notification' in window ? Notification.permission : 'unsupported'));
  const enableNotifications = async () => setPermission(await Notification.requestPermission());

  return (
    <div className="stack">
      <div className="row gap alerts-bar">
      <div className="segmented" role="tablist" aria-label="Alert status">
        {TABS.map((t) => (
          <button key={t.value} role="tab" aria-selected={tab === t.value} className={tab === t.value ? 'active' : ''} onClick={() => setTab(t.value)}>
            {t.label}
          </button>
        ))}
      </div>
        {permission === 'default' && (
          <button className="btn btn-sm" onClick={enableNotifications}>
            Enable desktop notifications
          </button>
        )}
        {permission === 'granted' && <span className="muted small">Desktop notifications on</span>}
      </div>
      <ErrorBanner error={alerts.error || actionError} onRetry={alerts.reload} />
      <Panel title={<>Alerts <span className="muted small">{formatNumber(alerts.data?.total ?? 0)}</span></>}>
        {items.length === 0 ? (
          <Empty>{tab === 'open' ? 'All clear — no open alerts.' : 'No alerts here.'}</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Alert</th>
                  <th>Service</th>
                  <th className="num">Count</th>
                  <th>First seen</th>
                  <th>Last seen</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id}>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td><StatusPill status={a.status} /></td>
                    <td>
                      <div>{a.summary}</div>
                      {a.sample_message && <div className="mono muted small truncate" title={a.sample_message}>{a.sample_message}</div>}
                      {a.acknowledged_by && <div className="muted small">Acknowledged by {a.acknowledged_by}</div>}
                      {a.resolved_reason && <div className="muted small">Resolved: {a.resolved_reason.replace(':', ' by ')}</div>}
                    </td>
                    <td className="mono nowrap">{a.service ?? 'all'}</td>
                    <td className="num">{formatNumber(a.count)}</td>
                    <td className="nowrap" title={a.first_seen}>{formatTime(a.first_seen, { withDate: true })}</td>
                    <td className="nowrap" title={a.last_seen}>{formatRelative(a.last_seen)}</td>
                    <td className="nowrap actions">
                      {a.service && (
                        <button className="btn btn-ghost btn-sm" onClick={() => navigate('explore', { service: a.service })}>
                          Logs
                        </button>
                      )}
                      {a.status === 'firing' && (
                        <button className="btn btn-sm" disabled={busy === a.id} onClick={() => act(a, 'acknowledge')}>
                          Acknowledge
                        </button>
                      )}
                      {a.status !== 'resolved' && (
                        <button className="btn btn-sm" disabled={busy === a.id} onClick={() => act(a, 'resolve')}>
                          Resolve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
