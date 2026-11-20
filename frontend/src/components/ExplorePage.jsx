import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, download } from '../api/client.js';
import { useData, useDebounced } from '../hooks/useData.js';
import { useTimeRange } from '../hooks/useTimeRange.js';
import { LEVELS, formatNumber, formatTime, rangeSeconds } from '../utils/format.js';
import PatternList from './PatternList.jsx';
import { Empty, ErrorBanner, LevelBadge, Modal, Panel } from './ui.jsx';

const PAGE_SIZE = 100;

export default function ExplorePage({ query }) {
  const { range } = useTimeRange();
  const [text, setText] = useState(query.q ?? '');
  const [levels, setLevels] = useState([]);
  const [service, setService] = useState(query.service ?? '');
  const [traceId, setTraceId] = useState(query.trace_id ?? '');
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState(query.view === 'patterns' ? 'patterns' : 'logs');
  const q = useDebounced(text, 350);

  // Follow links like #/explore?service=api from other pages.
  useEffect(() => {
    setService(query.service ?? '');
    setTraceId(query.trace_id ?? '');
    if (query.q !== undefined) setText(query.q);
    setView(query.view === 'patterns' ? 'patterns' : 'logs'); // clicking a pattern lands on its logs
  }, [query.service, query.trace_id, query.q, query.view]);

  const filters = useMemo(
    () => ({ q, level: levels, service: service || undefined, trace_id: traceId || undefined, from: range, to: 'now' }),
    [q, levels, service, traceId, range],
  );

  const services = useData(
    (signal) => api('/api/v1/stats/services', { params: { from: range, size: 200 }, signal }),
    [range],
  );

  const [pages, setPages] = useState({ items: [], cursor: null, total: 0, lowerBound: false });
  const [loadingMore, setLoadingMore] = useState(false);
  const first = useData((signal) => api('/api/v1/logs', { params: { ...filters, size: PAGE_SIZE }, signal }), [filters]);

  useEffect(() => {
    if (first.data) {
      setPages({
        items: first.data.items,
        cursor: first.data.next_cursor,
        total: first.data.total,
        lowerBound: first.data.total_is_lower_bound,
      });
    }
  }, [first.data]);

  const loadMore = useCallback(async () => {
    if (!pages.cursor) return;
    setLoadingMore(true);
    try {
      const next = await api('/api/v1/logs', { params: { ...filters, size: PAGE_SIZE, cursor: pages.cursor } });
      setPages((p) => ({ ...p, items: [...p.items, ...next.items], cursor: next.next_cursor }));
    } finally {
      setLoadingMore(false);
    }
  }, [filters, pages.cursor]);

  const toggleLevel = (lvl) =>
    setLevels((cur) => (cur.includes(lvl) ? cur.filter((l) => l !== lvl) : [...cur, lvl]));

  const exportAs = (format) =>
    download('/api/v1/logs/export', { ...filters, format, limit: 10000 }, `insightforge-logs.${format}`);

  const withDate = rangeSeconds(range) > 86400;

  return (
    <div className="stack">
      <div className="filters">
        <input
          className="search"
          type="search"
          placeholder='Search messages — "exact phrase", -exclude, a | b'
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Search log messages"
        />
        <select value={service} onChange={(e) => setService(e.target.value)} aria-label="Service">
          <option value="">All services</option>
          {service && !services.data?.some((s) => s.service === service) && <option value={service}>{service}</option>}
          {services.data?.map((s) => (
            <option key={s.service} value={s.service}>
              {s.service}
            </option>
          ))}
        </select>
        <div className="chips" role="group" aria-label="Levels">
          {LEVELS.map((lvl) => (
            <button
              key={lvl}
              className={`chip ${levels.includes(lvl) ? 'active' : ''}`}
              onClick={() => toggleLevel(lvl)}
              aria-pressed={levels.includes(lvl)}
            >
              <LevelBadge level={lvl} />
            </button>
          ))}
        </div>
        {traceId && (
          <span className="chip active">
            trace {traceId.slice(0, 8)}…
            <button className="chip-x" onClick={() => setTraceId('')} aria-label="Clear trace filter">
              ✕
            </button>
          </span>
        )}
      </div>

      <ErrorBanner error={first.error} onRetry={first.reload} />

      <div className="row gap">
        <div className="segmented" role="tablist" aria-label="Result view">
          <button role="tab" aria-selected={view === 'logs'} className={view === 'logs' ? 'active' : ''} onClick={() => setView('logs')}>
            Logs
          </button>
          <button role="tab" aria-selected={view === 'patterns'} className={view === 'patterns' ? 'active' : ''} onClick={() => setView('patterns')}>
            Patterns
          </button>
        </div>
      </div>

      {view === 'patterns' ? (
        <Panel title="Patterns in these results">
          <PatternList params={filters} deps={[filters]} size={50} />
        </Panel>
      ) : (
      <Panel
        title={
          <>
            Results{' '}
            <span className="muted small">
              {formatNumber(pages.total)}
              {pages.lowerBound ? '+' : ''} matching
            </span>
          </>
        }
        actions={
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => exportAs('csv')} disabled={!pages.total}>
              Export CSV
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => exportAs('ndjson')} disabled={!pages.total}>
              Export NDJSON
            </button>
          </>
        }
      >
        {pages.items.length === 0 && !first.loading ? (
          <Empty>No logs match these filters.</Empty>
        ) : (
          <div className="table-scroll">
            <table className={`table log-table ${first.loading ? 'is-loading' : ''}`}>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Level</th>
                  <th>Service</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {pages.items.map((log) => (
                  <tr
                    key={log.id}
                    className="clickable"
                    tabIndex={0}
                    onClick={() => setSelected(log)}
                    onKeyDown={(e) => e.key === 'Enter' && setSelected(log)}
                  >
                    <td className="mono nowrap muted">{formatTime(log.timestamp, { withDate, withMillis: true })}</td>
                    <td>
                      <LevelBadge level={log.level} />
                    </td>
                    <td className="mono nowrap">{log.service}</td>
                    <td className="mono message">{log.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages.cursor && (
          <div className="load-more">
            <button className="btn" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading…' : `Load ${PAGE_SIZE} more`}
            </button>
          </div>
        )}
      </Panel>
      )}

      {selected && (
        <LogDetail
          log={selected}
          onClose={() => setSelected(null)}
          onTrace={(id) => {
            setSelected(null);
            setTraceId(id);
          }}
        />
      )}
    </div>
  );
}

function LogDetail({ log, onClose, onTrace }) {
  const [copied, setCopied] = useState(false);
  const fields = [
    ['Timestamp', new Date(log.timestamp).toISOString()],
    ['Service', log.service],
    ['Host', log.host],
    ['Environment', log.environment],
    ['Trace ID', log.trace_id],
    ['Span ID', log.span_id],
    ['Log ID', log.id],
  ].filter(([, v]) => v);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(log, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <Modal title="Log details" onClose={onClose} wide>
      <div className="detail">
        <div className="detail-head">
          <LevelBadge level={log.level} />
          <span className="mono muted">{formatTime(log.timestamp, { withDate: true, withMillis: true })}</span>
        </div>
        <pre className="detail-message">{log.message}</pre>
        <dl className="kv">
          {fields.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className="mono">{v}</dd>
            </div>
          ))}
          {Object.entries(log.attributes ?? {}).map(([k, v]) => (
            <div key={k}>
              <dt>attributes.{k}</dt>
              <dd className="mono">{String(v)}</dd>
            </div>
          ))}
        </dl>
        <div className="row gap">
          {log.trace_id && (
            <button className="btn" onClick={() => onTrace(log.trace_id)}>
              Show all logs in this trace
            </button>
          )}
          <button className="btn btn-ghost" onClick={copy}>
            {copied ? 'Copied' : 'Copy JSON'}
          </button>
        </div>
      </div>
    </Modal>
  );
}
