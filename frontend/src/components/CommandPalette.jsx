import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../hooks/useAuth.jsx';
import { navigate } from '../hooks/useData.js';
import { formatRelative } from '../utils/format.js';
import { Icon } from './ui.jsx';

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const shortcutLabel = isMac ? '⌘K' : 'Ctrl K';

const PAGES = [
  { page: 'overview', title: 'Overview', subtitle: 'Volume, error rate and service health', icon: 'overview' },
  { page: 'explore', title: 'Explore', subtitle: 'Search and filter logs', icon: 'explore' },
  { page: 'live', title: 'Live Tail', subtitle: 'Stream logs as they arrive', icon: 'live' },
  { page: 'alerts', title: 'Alerts', subtitle: 'Firing, acknowledged and resolved', icon: 'alerts' },
  { page: 'rules', title: 'Alert Rules', subtitle: 'Conditions and notification channels', icon: 'rules' },
];

const GROUP_ORDER = ['Top Hit', 'Suggestions', 'Pages', 'Actions', 'Open alerts', 'Services'];
const PER_GROUP = 6;
const TRACE_ID = /^[0-9a-f-]{12,64}$/i;

/** Prefix > every word is a word-prefix > substring > in-order subsequence; 0 means no match. */
export function fuzzyScore(text, query) {
  if (!query) return 1;
  const t = text.toLowerCase();
  const q = query.toLowerCase().trim();
  const at = t.indexOf(q);
  if (at === 0) return 100;
  const words = t.split(/[^a-z0-9]+/).filter(Boolean);
  const tokens = q.split(/\s+/).filter(Boolean);
  if (tokens.every((tok) => words.some((w) => w.startsWith(tok)))) {
    return words[0]?.startsWith(tokens[0]) ? 92 : 86;
  }
  if (at > 0) return 80 - Math.min(at, 40) / 2;
  let from = 0;
  let gaps = 0;
  for (const ch of q) {
    if (ch === ' ') continue;
    const found = t.indexOf(ch, from);
    if (found < 0) return 0;
    gaps += found - from;
    from = found + 1;
  }
  return Math.max(1, 40 - gaps);
}

export default function CommandPalette({ open, onClose }) {
  const { isAdmin, logout, authDisabled } = useAuth();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [services, setServices] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Fresh data each time it opens.
  useEffect(() => {
    if (!open) return undefined;
    setQuery('');
    setActive(0);
    setStatus(null);
    const controller = new AbortController();
    const { signal } = controller;
    api('/api/v1/stats/services', { params: { from: 'now-24h', size: 200 }, signal })
      .then(setServices)
      .catch(() => {});
    api('/api/v1/alerts', { params: { size: 20 }, signal })
      .then((r) => setAlerts(r.items))
      .catch(() => {});
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => controller.abort();
  }, [open]);

  const items = useMemo(() => {
    const q = query.trim();
    const all = [];
    const add = (group, item) => all.push({ group, ...item });

    if (q) {
      add('Suggestions', {
        id: 'search',
        title: `Search logs for “${q}”`,
        subtitle: 'Full-text search in Explore',
        icon: 'explore',
        run: () => navigate('explore', { q }),
        pinned: true,
      });
      if (TRACE_ID.test(q)) {
        add('Suggestions', {
          id: 'trace',
          title: `Find trace ${q.slice(0, 16)}${q.length > 16 ? '…' : ''}`,
          subtitle: 'Every log carrying this trace id',
          icon: 'live',
          run: () => navigate('explore', { trace_id: q }),
          pinned: true,
        });
      }
    }

    PAGES.forEach((p) => add('Pages', { id: `page-${p.page}`, ...p, run: () => navigate(p.page) }));

    add('Actions', {
      id: 'patterns',
      title: 'Show log patterns',
      subtitle: 'Group similar messages',
      icon: 'overview',
      keywords: 'cluster group similar templates',
      run: () => navigate('explore', { view: 'patterns' }),
    });
    if (isAdmin) {
      add('Actions', {
        id: 'new-rule',
        title: 'New alert rule…',
        subtitle: 'Create an alerting condition',
        icon: 'rules',
        run: () => navigate('rules', { new: '1' }),
      });
      ['INFO', 'WARN', 'ERROR', 'CRITICAL'].forEach((level) =>
        add('Actions', {
          id: `test-${level}`,
          title: `Send test ${level} log`,
          subtitle: 'Inject a log from the dashboard',
          icon: 'send',
          keepOpen: true,
          run: async () => {
            try {
              await api('/api/v1/logs', {
                method: 'POST',
                body: { level, service: 'dashboard-test', message: `Test ${level} log sent from the command palette` },
              });
              setStatus(`Sent a ${level} log`);
            } catch (err) {
              setStatus(err.message);
            }
          },
        }),
      );
    }
    if ('Notification' in window && Notification.permission === 'default') {
      add('Actions', {
        id: 'notify',
        title: 'Enable desktop notifications',
        subtitle: 'Get notified about new alerts when this tab is in the background',
        icon: 'alerts',
        run: () => Notification.requestPermission(),
      });
    }
    if (!authDisabled) {
      add('Actions', { id: 'logout', title: 'Sign out', subtitle: '', icon: 'logout', run: logout });
    }

    alerts.forEach((a) =>
      add('Open alerts', {
        id: `alert-${a.id}`,
        title: a.summary,
        subtitle: `${a.severity} · ${a.status} · ${formatRelative(a.last_seen)}`,
        icon: 'alerts',
        keywords: `${a.service ?? ''} ${a.rule_name}`,
        run: () => navigate('alerts'),
      }),
    );
    services.forEach((s) =>
      add('Services', {
        id: `svc-${s.service}`,
        title: s.service,
        subtitle: `${s.total.toLocaleString()} logs in 24h · ${(s.error_rate * 100).toFixed(1)}% errors`,
        icon: 'explore',
        mono: true,
        run: () => navigate('explore', { service: s.service }),
      }),
    );

    // Score, filter, cap per group, then order groups.
    const scored = all
      .map((item) => ({
        ...item,
        score: item.pinned ? 1000 : fuzzyScore(`${item.title} ${item.keywords ?? ''}`, q),
      }))
      .filter((item) => item.score > 0);
    scored.sort((a, b) => b.score - a.score);
    // Like Spotlight: a strong prefix/substring match becomes the "Top Hit" above the search suggestion,
    // so typing "new rule" + Enter runs the action rather than searching logs for "new rule".
    const groups = new Map();
    const topHit = q ? scored.find((item) => !item.pinned && item.score >= 80) : null;
    if (topHit) groups.set('Top Hit', [{ ...topHit, group: 'Top Hit' }]);
    for (const item of scored) {
      if (item === topHit) continue;
      const list = groups.get(item.group) ?? [];
      if (list.length < (q ? PER_GROUP : item.group === 'Open alerts' ? 3 : PER_GROUP)) list.push(item);
      groups.set(item.group, list);
    }
    if (!q) groups.delete('Services'); // keep the empty state short
    return GROUP_ORDER.flatMap((g) => groups.get(g) ?? []);
  }, [query, services, alerts, isAdmin, authDisabled, logout]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  if (!open) return null;

  const runItem = async (item) => {
    await item.run();
    if (!item.keepOpen) onClose();
  };

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && items[active]) {
      e.preventDefault();
      runItem(items[active]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  let lastGroup = null;
  return (
    <div className="spotlight-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="spotlight glass" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="spotlight-input">
          <Icon name="explore" size={22} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search logs, services, alerts and actions"
            aria-label="Command"
            aria-controls="spotlight-results"
            aria-activedescendant={items[active] ? `cmd-${items[active].id}` : undefined}
            role="combobox"
            aria-expanded="true"
            spellCheck={false}
            autoComplete="off"
          />
          <kbd>esc</kbd>
        </div>
        {items.length > 0 && (
          <ul className="spotlight-results" id="spotlight-results" role="listbox" ref={listRef}>
            {items.map((item, i) => {
              const header = item.group !== lastGroup ? item.group : null;
              lastGroup = item.group;
              return (
                <li key={item.id} role="presentation">
                  {header && <div className="spotlight-group">{header}</div>}
                  <div
                    id={`cmd-${item.id}`}
                    role="option"
                    aria-selected={i === active}
                    data-active={i === active}
                    className={`spotlight-item ${i === active ? 'active' : ''}`}
                    onMouseMove={() => i !== active && setActive(i)}
                    onClick={() => runItem(item)}
                  >
                    <span className="spotlight-icon">
                      <Icon name={item.icon} size={16} />
                    </span>
                    <span className="spotlight-text">
                      <span className={`spotlight-title ${item.mono ? 'mono' : ''}`}>{item.title}</span>
                      {item.subtitle && <span className="spotlight-subtitle">{item.subtitle}</span>}
                    </span>
                    {i === active && <kbd>↵</kbd>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <div className="spotlight-foot">
          <span>{status ?? 'Type to search everything'}</span>
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> navigate <kbd>↵</kbd> open
          </span>
        </div>
      </div>
    </div>
  );
}
