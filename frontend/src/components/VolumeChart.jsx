import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { VOLUME_SERIES, formatCompact, formatNumber, formatTime } from '../utils/format.js';
import { Empty } from './ui.jsx';

const SURFACE = "rgba(22, 23, 32, 0.95)"; // matches the glass panel tint, so stacked segments read as separate

function toSeries(buckets) {
  return buckets.map((b) => {
    const row = { time: b.time };
    for (const s of VOLUME_SERIES) row[s.key] = s.levels.reduce((sum, lvl) => sum + (b[lvl] ?? 0), 0);
    row.total = VOLUME_SERIES.reduce((sum, s) => sum + row[s.key], 0);
    return row;
  });
}

function VolumeTooltip({ active, payload, label, withDate }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip glass">
      <div className="tooltip-title">{formatTime(label, { withDate })}</div>
      {[...VOLUME_SERIES].reverse().map((s) => (
        <div key={s.key} className="tooltip-row">
          <span className="line-key" style={{ background: s.color }} aria-hidden="true" />
          <strong>{formatNumber(row[s.key])}</strong>
          <span className="muted">{s.label}</span>
        </div>
      ))}
      <div className="tooltip-row tooltip-total">
        <strong>{formatNumber(row.total)}</strong>
        <span className="muted">total</span>
      </div>
    </div>
  );
}

export default function VolumeChart({ histogram, rangeSeconds }) {
  const [showTable, setShowTable] = useState(false);
  const data = useMemo(() => toSeries(histogram?.buckets ?? []), [histogram]);
  const withDate = rangeSeconds > 86400;
  const hasData = data.some((d) => d.total > 0);

  return (
    <div className="chart">
      <div className="chart-legend">
        {VOLUME_SERIES.map((s) => (
          <span key={s.key} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} aria-hidden="true" />
            {s.label}
          </span>
        ))}
        <span className="muted small legend-interval">per {histogram?.interval ?? '—'}</span>
        <button className="btn btn-ghost btn-sm" onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
          {showTable ? 'Chart' : 'Table'}
        </button>
      </div>

      {!hasData ? (
        <Empty>No logs in this time range yet.</Empty>
      ) : showTable ? (
        <div className="table-scroll chart-table">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                {VOLUME_SERIES.map((s) => (
                  <th key={s.key} className="num">{s.label}</th>
                ))}
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.filter((d) => d.total > 0).map((d) => (
                <tr key={d.time}>
                  <td>{formatTime(d.time, { withDate })}</td>
                  {VOLUME_SERIES.map((s) => (
                    <td key={s.key} className="num">{formatNumber(d[s.key])}</td>
                  ))}
                  <td className="num">{formatNumber(d.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-area" role="img" aria-label="Log volume over time by level">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke="#2e2d2a" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => formatTime(t, { withDate }).replace(/:\d\d$/, '')}
                stroke="#8a8984"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#3a3935' }}
                minTickGap={40}
              />
              <YAxis
                tickFormatter={formatCompact}
                stroke="#8a8984"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={44}
                allowDecimals={false}
              />
              <Tooltip
                cursor={{ fill: 'rgba(240,239,236,0.06)' }}
                content={<VolumeTooltip withDate={withDate} />}
                isAnimationActive={false}
              />
              {VOLUME_SERIES.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  stackId="volume"
                  fill={s.color}
                  stroke={SURFACE}
                  strokeWidth={1}
                  radius={i === VOLUME_SERIES.length - 1 ? [3, 3, 0, 0] : 0}
                  isAnimationActive={false}
                  name={s.label}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
