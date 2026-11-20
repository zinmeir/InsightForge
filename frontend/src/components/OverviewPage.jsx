import { useState } from 'react';
import { api } from '../api/client.js';
import { useData } from '../hooks/useData.js';
import { useTimeRange } from '../hooks/useTimeRange.js';
import { formatNumber, formatPercent, formatRelative, rangeSeconds } from '../utils/format.js';
import PatternList from './PatternList.jsx';
import ServiceBreakdown from './ServiceBreakdown.jsx';
import VolumeChart from './VolumeChart.jsx';
import { Empty, ErrorBanner, Panel, SeverityBadge, StatusPill } from './ui.jsx';

function Kpi({ label, value, hint, tone }) {
  return (
    <div className={`kpi glass ${tone ? `kpi-${tone}` : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint muted small">{hint}</div>}
    </div>
  );
}

const PATTERN_SCOPES = {
  errors: { label: 'Errors', level: ['ERROR', 'CRITICAL'] },
  warnings: { label: 'Warnings', level: ['WARN'] },
  all: { label: 'All', level: [] },
};

export default function OverviewPage() {
  const { range, refreshMs } = useTimeRange();
  const [scope, setScope] = useState('errors');
  const params = { from: range, to: 'now' };
  const opts = { interval: refreshMs };

  const overview = useData((signal) => api('/api/v1/stats/overview', { params, signal }), [range], opts);
  const histogram = useData((signal) => api('/api/v1/stats/histogram', { params, signal }), [range], opts);
  const services = useData((signal) => api('/api/v1/stats/services', { params, signal }), [range], opts);
  const alerts = useData((signal) => api('/api/v1/alerts', { params: { size: 5 }, signal }), [], opts);

  const o = overview.data;
  const errors = o ? o.by_level.ERROR + o.by_level.CRITICAL : 0;

  return (
    <div className="stack">
      <ErrorBanner error={overview.error || histogram.error} onRetry={overview.reload} />

      <div className="kpis">
        <Kpi label="Logs" value={o ? formatNumber(o.total) : '—'} hint={o && `${formatNumber(o.by_level.WARN)} warnings`} />
        <Kpi
          label="Error rate"
          value={o ? formatPercent(o.error_rate, 2) : '—'}
          hint={o && `${formatNumber(errors)} errors · ${formatNumber(o.by_level.CRITICAL)} critical`}
          tone={o && o.error_rate >= 0.05 ? 'bad' : undefined}
        />
        <Kpi label="Active services" value={o ? formatNumber(o.services) : '—'} />
        <Kpi
          label="Open alerts"
          value={o ? formatNumber(o.open_alerts) : '—'}
          hint={<a href="#/alerts">View alerts →</a>}
          tone={o && o.open_alerts > 0 ? 'bad' : undefined}
        />
      </div>

      <Panel title="Log volume">
        <VolumeChart histogram={histogram.data} rangeSeconds={rangeSeconds(range)} />
      </Panel>

      <Panel
        title="Top patterns"
        actions={
          <div className="segmented" role="group" aria-label="Pattern scope">
            {Object.entries(PATTERN_SCOPES).map(([key, s]) => (
              <button key={key} className={scope === key ? 'active' : ''} onClick={() => setScope(key)}>
                {s.label}
              </button>
            ))}
          </div>
        }
      >
        <PatternList
          params={{ ...params, level: PATTERN_SCOPES[scope].level }}
          deps={[range, scope]}
          interval={refreshMs ? Math.max(refreshMs, 30000) : 0}
          size={8}
        />
      </Panel>

      <div className="grid-2">
        <Panel title="Services">
          <ServiceBreakdown services={services.data} />
        </Panel>
        <Panel title="Open alerts" actions={<a href="#/alerts" className="small">All alerts →</a>}>
          {alerts.data?.items?.length ? (
            <ul className="alert-list">
              {alerts.data.items.map((a) => (
                <li key={a.id}>
                  <div className="alert-line">
                    <SeverityBadge severity={a.severity} />
                    <StatusPill status={a.status} />
                    <span className="muted small">{formatRelative(a.last_seen)}</span>
                  </div>
                  <div className="alert-summary">{a.summary}</div>
                  <div className="muted small">
                    {formatNumber(a.count)} occurrence{a.count === 1 ? '' : 's'}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>All clear — no open alerts.</Empty>
          )}
        </Panel>
      </div>
    </div>
  );
}
