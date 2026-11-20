import { useMemo, useState } from 'react';
import { navigate } from '../hooks/useData.js';
import { formatNumber, formatPercent } from '../utils/format.js';
import { Empty } from './ui.jsx';

const OK_COLOR = '#3987e5';
const ERROR_COLOR = '#d55181';

/** Ranked bars per service: blue = healthy logs, magenta = errors & critical. */
export default function ServiceBreakdown({ services }) {
  const [sortBy, setSortBy] = useState('total');
  const rows = useMemo(() => {
    const list = [...(services ?? [])];
    list.sort((a, b) => (sortBy === 'total' ? b.total - a.total : b.error_rate - a.error_rate));
    return list;
  }, [services, sortBy]);
  const max = Math.max(1, ...rows.map((r) => r.total));

  if (!rows.length) return <Empty>No services have reported logs in this range.</Empty>;

  return (
    <div>
      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: OK_COLOR }} aria-hidden="true" />
          Other logs
        </span>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: ERROR_COLOR }} aria-hidden="true" />
          Errors &amp; critical
        </span>
        <div className="segmented" role="group" aria-label="Sort services">
          <button className={sortBy === 'total' ? 'active' : ''} onClick={() => setSortBy('total')}>
            Volume
          </button>
          <button className={sortBy === 'errors' ? 'active' : ''} onClick={() => setSortBy('errors')}>
            Error rate
          </button>
        </div>
      </div>
      <table className="table service-table">
        <thead>
          <tr>
            <th>Service</th>
            <th className="bar-col">Volume</th>
            <th className="num">Logs</th>
            <th className="num">Error rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const errors = s.by_level.ERROR + s.by_level.CRITICAL;
            const okWidth = ((s.total - errors) / max) * 100;
            const errWidth = (errors / max) * 100;
            return (
              <tr
                key={s.service}
                className="clickable"
                tabIndex={0}
                onClick={() => navigate('explore', { service: s.service })}
                onKeyDown={(e) => e.key === 'Enter' && navigate('explore', { service: s.service })}
                title={`${s.service}: ${formatNumber(s.total)} logs, ${formatNumber(errors)} errors — click to explore`}
              >
                <td className="mono">{s.service}</td>
                <td className="bar-col">
                  <div className="hbar" aria-hidden="true">
                    {okWidth > 0 && <span style={{ width: `${okWidth}%`, background: OK_COLOR }} />}
                    {errWidth > 0 && <span style={{ width: `${errWidth}%`, background: ERROR_COLOR }} />}
                  </div>
                </td>
                <td className="num">{formatNumber(s.total)}</td>
                <td className="num">{formatPercent(s.error_rate)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
