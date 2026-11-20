import { useEffect, useRef, useState } from 'react';
import { streamLogs } from '../api/client.js';
import { useDebounced } from '../hooks/useData.js';
import { LEVELS, formatTime } from '../utils/format.js';
import { Empty, LevelBadge, Panel } from './ui.jsx';

const MAX_LINES = 1000;
const STATUS_TEXT = { connecting: 'Connecting…', live: 'Live', reconnecting: 'Reconnecting…', paused: 'Paused' };

export default function LiveTailPage() {
  const [lines, setLines] = useState([]);
  const [status, setStatus] = useState('connecting');
  const [paused, setPaused] = useState(false);
  const [levels, setLevels] = useState([]);
  const [serviceText, setServiceText] = useState('');
  const [text, setText] = useState('');
  const [rate, setRate] = useState(0);
  const service = useDebounced(serviceText, 400);
  const q = useDebounced(text, 400);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const counter = useRef(0);
  const scroller = useRef(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    const controller = new AbortController();
    streamLogs({
      params: { level: levels, service: service || undefined, q: q || undefined },
      signal: controller.signal,
      onStatus: setStatus,
      onLogs: (batch) => {
        counter.current += batch.length;
        if (pausedRef.current) return;
        setLines((prev) => {
          const next = prev.concat(batch);
          return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
        });
      },
    });
    return () => controller.abort();
  }, [levels, service, q]);

  // Logs-per-second readout, sampled every 2s.
  useEffect(() => {
    const t = setInterval(() => {
      setRate(counter.current / 2);
      counter.current = 0;
    }, 2000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const onScroll = () => {
    const el = scroller.current;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const toggleLevel = (lvl) =>
    setLevels((cur) => (cur.includes(lvl) ? cur.filter((l) => l !== lvl) : [...cur, lvl]));

  const shownStatus = paused ? 'paused' : status;

  return (
    <div className="stack fill">
      <div className="filters">
        <input
          placeholder="Service, e.g. payment-*"
          value={serviceText}
          onChange={(e) => setServiceText(e.target.value)}
          aria-label="Service filter"
        />
        <input
          className="search"
          placeholder="Message contains…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Message filter"
        />
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
      </div>

      <Panel
        className="fill"
        title={
          <span className="row gap">
            <span className={`live-dot live-${shownStatus}`} aria-hidden="true" />
            {STATUS_TEXT[shownStatus]}
            <span className="muted small">{rate.toFixed(1)} logs/s</span>
          </span>
        }
        actions={
          <>
            <button className="btn btn-sm" onClick={() => setPaused((p) => !p)}>
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setLines([])}>
              Clear
            </button>
          </>
        }
      >
        <div className="terminal" ref={scroller} onScroll={onScroll} aria-live="off">
          {lines.length === 0 ? (
            <Empty>Waiting for logs… Send one with the test buttons above or run the load generator.</Empty>
          ) : (
            lines.map((log) => (
              <div key={log.id} className={`term-line term-${log.level.toLowerCase()}`}>
                <span className="muted">{formatTime(log.timestamp, { withMillis: true })}</span>
                <LevelBadge level={log.level} />
                <span className="term-service">{log.service}</span>
                <span className="term-msg">{log.message}</span>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
