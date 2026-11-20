import { api } from '../api/client.js';
import { navigate, useData } from '../hooks/useData.js';
import { formatNumber, formatPercent, formatRelative } from '../utils/format.js';
import { Empty, ErrorBanner } from './ui.jsx';

const TREND = {
  new: { label: 'New', icon: '✦', className: 'trend-new' },
  rising: { label: 'Rising', icon: '↑', className: 'trend-rising' },
  steady: { label: 'Steady', icon: '→', className: 'trend-steady' },
  falling: { label: 'Falling', icon: '↓', className: 'trend-falling' },
};

/** Renders a template with its <placeholders> as subtle tokens. */
export function PatternText({ pattern }) {
  return (
    <span className="pattern-text">
      {pattern.split(/(<(?:url|email|uuid|ip|hex|str|num)>)/).map((part, i) =>
        /^<\w+>$/.test(part) ? (
          <span key={i} className="ph">
            {part.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  );
}

/**
 * Most frequent message patterns for the given filters.
 * Clicking a row opens Explore with a query that finds the underlying logs.
 */
export default function PatternList({ params, deps, interval = 0, size = 10, compact = false }) {
  const report = useData(
    (signal) => api('/api/v1/stats/patterns', { params: { ...params, size }, signal }),
    deps,
    { interval },
  );
  const patterns = report.data?.patterns ?? [];
  const max = Math.max(1, ...patterns.map((p) => p.count));

  if (report.error) return <ErrorBanner error={report.error} onRetry={report.reload} />;
  if (!patterns.length) {
    return <Empty>{report.loading ? 'Analysing…' : 'No logs match — nothing to group yet.'}</Empty>;
  }

  return (
    <div className="patterns">
      <div className="table-scroll">
        <table className="table pattern-table">
          <thead>
            <tr>
              <th>Pattern</th>
              <th className="num">Count</th>
              {!compact && <th className="share-col">Share</th>}
              <th>Trend</th>
              {!compact && <th>Services</th>}
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {patterns.map((p) => {
              const trend = TREND[p.trend];
              const open = () => navigate('explore', { q: p.query });
              return (
                <tr
                  key={p.pattern}
                  className="clickable"
                  tabIndex={0}
                  onClick={open}
                  onKeyDown={(e) => e.key === 'Enter' && open()}
                  title={`Example: ${p.example}\n\nClick to see these logs`}
                >
                  <td className="mono pattern-cell">
                    <PatternText pattern={p.pattern} />
                  </td>
                  <td className="num">{formatNumber(p.count)}</td>
                  {!compact && (
                    <td className="share-col">
                      <div className="share">
                        <div className="share-bar" aria-hidden="true">
                          <span style={{ width: `${(p.count / max) * 100}%` }} />
                        </div>
                        <span className="muted small">{formatPercent(p.share)}</span>
                      </div>
                    </td>
                  )}
                  <td>
                    <span className={`trend ${trend.className}`}>
                      <span aria-hidden="true">{trend.icon}</span> {trend.label}
                    </span>
                  </td>
                  {!compact && (
                    <td className="mono small">
                      {p.services.join(', ')}
                      {p.service_count > p.services.length && (
                        <span className="muted"> +{p.service_count - p.services.length}</span>
                      )}
                    </td>
                  )}
                  <td className="nowrap muted small">{formatRelative(p.last_seen)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="muted small patterns-foot">
        Grouped {formatNumber(report.data.sample_size)}
        {report.data.sampled ? ` most recent of ${formatNumber(report.data.total)}` : ''} logs into{' '}
        {formatNumber(patterns.length)} patterns. Numbers, ids, IPs, URLs and quoted values are masked.
      </div>
    </div>
  );
}
