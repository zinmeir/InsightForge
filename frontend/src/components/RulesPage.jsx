import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../hooks/useAuth.jsx';
import { useData } from '../hooks/useData.js';
import { LEVELS, formatDuration } from '../utils/format.js';
import { Empty, ErrorBanner, LevelBadge, Modal, Panel, SeverityBadge } from './ui.jsx';

const CHANNELS = [
  { value: 'slack', label: 'Slack' },
  { value: 'pagerduty', label: 'PagerDuty' },
  { value: 'webhook', label: 'Webhook' },
];

const EMPTY_RULE = {
  name: '',
  description: '',
  enabled: true,
  severity: 'warning',
  condition: { levels: ['ERROR', 'CRITICAL'], services: [], message_contains: '', threshold: 10, window_seconds: 60 },
  group_by_service: true,
  cooldown_seconds: 300,
  auto_resolve_seconds: 900,
  notify: [],
};

function describeCondition(c) {
  const parts = [];
  parts.push(c.levels.length ? c.levels.join(' / ') : 'any level');
  if (c.services.length) parts.push(`from ${c.services.join(', ')}`);
  if (c.message_contains) parts.push(`containing “${c.message_contains}”`);
  parts.push(c.threshold === 1 ? 'any occurrence' : `≥ ${c.threshold} within ${formatDuration(c.window_seconds)}`);
  return parts.join(' · ');
}

export default function RulesPage({ query = {} }) {
  const { isAdmin } = useAuth();
  const rules = useData((signal) => api('/api/v1/rules', { signal }), []);
  const channels = useData((signal) => api('/api/v1/notifications/channels', { signal }), []);
  const [editing, setEditing] = useState(null); // null | rule | EMPTY_RULE
  const [error, setError] = useState(null);

  // #/rules?new=1 (from the command palette) opens the editor straight away.
  useEffect(() => {
    if (query.new && isAdmin) setEditing(EMPTY_RULE);
  }, [query.new, isAdmin]);

  const run = async (fn) => {
    setError(null);
    try {
      await fn();
      rules.reload();
    } catch (err) {
      setError(err);
    }
  };

  const toggle = (rule) =>
    run(() => api(`/api/v1/rules/${rule.id}`, { method: 'PATCH', body: { enabled: !rule.enabled } }));
  const remove = (rule) => {
    if (window.confirm(`Delete rule “${rule.name}”? Its open alerts will be resolved.`)) {
      run(() => api(`/api/v1/rules/${rule.id}`, { method: 'DELETE' }));
    }
  };

  const configured = channels.data?.configured ?? [];

  return (
    <div className="stack">
      <ErrorBanner error={rules.error || error} onRetry={rules.reload} />
      <Panel
        title="Alert rules"
        actions={
          isAdmin && (
            <button className="btn btn-primary btn-sm" onClick={() => setEditing(EMPTY_RULE)}>
              New rule
            </button>
          )
        }
      >
        {!rules.data?.length ? (
          <Empty>No rules yet. {isAdmin && 'Create one to start alerting.'}</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Enabled</th>
                  <th>Rule</th>
                  <th>Severity</th>
                  <th>Condition</th>
                  <th>Cooldown / auto-resolve</th>
                  <th>Notify</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.data.map((r) => (
                  <tr key={r.id} className={r.enabled ? '' : 'is-disabled'}>
                    <td>
                      <label className="switch">
                        <input type="checkbox" checked={r.enabled} disabled={!isAdmin} onChange={() => toggle(r)} />
                        <span className="sr-only">{r.enabled ? 'Disable' : 'Enable'} {r.name}</span>
                      </label>
                    </td>
                    <td>
                      <div>{r.name}</div>
                      {r.description && <div className="muted small">{r.description}</div>}
                    </td>
                    <td><SeverityBadge severity={r.severity} /></td>
                    <td className="small">
                      {describeCondition(r.condition)}
                      {!r.group_by_service && <span className="muted"> · across all services</span>}
                    </td>
                    <td className="small nowrap">
                      {formatDuration(r.cooldown_seconds)} / {formatDuration(r.auto_resolve_seconds)}
                    </td>
                    <td className="small">
                      {r.notify.length
                        ? r.notify.map((c) => (
                            <span key={c} className={`tag ${configured.includes(c) ? '' : 'tag-off'}`} title={configured.includes(c) ? 'Configured' : 'Not configured on the server'}>
                              {c}
                            </span>
                          ))
                        : <span className="muted">dashboard only</span>}
                    </td>
                    <td className="nowrap actions">
                      {isAdmin && (
                        <>
                          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(r)}>Edit</button>
                          <button className="btn btn-ghost btn-sm btn-danger" onClick={() => remove(r)}>Delete</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <NotificationsPanel channels={channels.data} isAdmin={isAdmin} />

      {editing && (
        <RuleForm
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            rules.reload();
          }}
        />
      )}
    </div>
  );
}

function NotificationsPanel({ channels, isAdmin }) {
  const [results, setResults] = useState({});
  const test = async (channel) => {
    setResults((r) => ({ ...r, [channel]: 'Sending…' }));
    try {
      const res = await api('/api/v1/notifications/test', { method: 'POST', body: { channel } });
      setResults((r) => ({ ...r, [channel]: res.delivered ? 'Delivered ✓' : 'Delivery failed — check server logs' }));
    } catch (err) {
      setResults((r) => ({ ...r, [channel]: err.message }));
    }
  };
  const configured = channels?.configured ?? [];
  return (
    <Panel title="Notification channels">
      <p className="muted small">
        Channels are configured on the server with <code>SLACK_WEBHOOK_URL</code>, <code>PAGERDUTY_ROUTING_KEY</code> and{' '}
        <code>ALERT_WEBHOOK_URL</code>. Rules only notify channels that are configured.
      </p>
      <div className="channel-grid">
        {CHANNELS.map((c) => {
          const on = configured.includes(c.value);
          return (
            <div key={c.value} className="channel">
              <div>
                <strong>{c.label}</strong>
                <div className={`small ${on ? '' : 'muted'}`}>{on ? '● Configured' : '○ Not configured'}</div>
                {results[c.value] && <div className="small muted">{results[c.value]}</div>}
              </div>
              {isAdmin && (
                <button className="btn btn-sm" disabled={!on} onClick={() => test(c.value)}>
                  Send test
                </button>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function RuleForm({ initial, onClose, onSaved }) {
  const isNew = !initial.id;
  const [form, setForm] = useState(() => ({
    ...initial,
    description: initial.description ?? '',
    condition: {
      ...initial.condition,
      message_contains: initial.condition.message_contains ?? '',
      services: initial.condition.services ?? [],
    },
  }));
  const [servicesText, setServicesText] = useState((initial.condition.services ?? []).join(', '));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setCond = (patch) => setForm((f) => ({ ...f, condition: { ...f.condition, ...patch } }));
  const toggleIn = (list, value) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      enabled: form.enabled,
      severity: form.severity,
      group_by_service: form.group_by_service,
      cooldown_seconds: Number(form.cooldown_seconds),
      auto_resolve_seconds: Number(form.auto_resolve_seconds),
      notify: form.notify,
      condition: {
        levels: form.condition.levels,
        services: servicesText.split(',').map((s) => s.trim()).filter(Boolean),
        message_contains: form.condition.message_contains.trim() || null,
        threshold: Number(form.condition.threshold),
        window_seconds: Number(form.condition.window_seconds),
      },
    };
    try {
      if (isNew) await api('/api/v1/rules', { method: 'POST', body });
      else await api(`/api/v1/rules/${initial.id}`, { method: 'PATCH', body });
      onSaved();
    } catch (err) {
      setError(err);
      setSaving(false);
    }
  };

  return (
    <Modal title={isNew ? 'New alert rule' : `Edit “${initial.name}”`} onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field span-2">
            <span>Name</span>
            <input value={form.name} onChange={(e) => set({ name: e.target.value })} required maxLength={120} />
          </label>
          <label className="field span-2">
            <span>Description</span>
            <input value={form.description} onChange={(e) => set({ description: e.target.value })} maxLength={1000} />
          </label>

          <fieldset className="field span-2">
            <legend>Match levels <span className="muted small">(none selected = any)</span></legend>
            <div className="chips">
              {LEVELS.map((lvl) => (
                <button
                  type="button"
                  key={lvl}
                  className={`chip ${form.condition.levels.includes(lvl) ? 'active' : ''}`}
                  aria-pressed={form.condition.levels.includes(lvl)}
                  onClick={() => setCond({ levels: toggleIn(form.condition.levels, lvl) })}
                >
                  <LevelBadge level={lvl} />
                </button>
              ))}
            </div>
          </fieldset>

          <label className="field">
            <span>Services <span className="muted small">(comma-separated, wildcards ok)</span></span>
            <input value={servicesText} onChange={(e) => setServicesText(e.target.value)} placeholder="any service" />
          </label>
          <label className="field">
            <span>Message contains</span>
            <input
              value={form.condition.message_contains}
              onChange={(e) => setCond({ message_contains: e.target.value })}
              placeholder="optional, case-insensitive"
              maxLength={256}
            />
          </label>

          <label className="field">
            <span>Threshold (matching logs)</span>
            <input type="number" min={1} value={form.condition.threshold} onChange={(e) => setCond({ threshold: e.target.value })} required />
          </label>
          <label className="field">
            <span>Window (seconds)</span>
            <input type="number" min={1} max={86400} value={form.condition.window_seconds} onChange={(e) => setCond({ window_seconds: e.target.value })} required />
          </label>

          <label className="field">
            <span>Severity</span>
            <select value={form.severity} onChange={(e) => set({ severity: e.target.value })}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </label>
          <label className="field checkbox">
            <input type="checkbox" checked={form.group_by_service} onChange={(e) => set({ group_by_service: e.target.checked })} />
            <span>Track each service separately</span>
          </label>

          <label className="field">
            <span>Cooldown (seconds)</span>
            <input type="number" min={0} max={86400} value={form.cooldown_seconds} onChange={(e) => set({ cooldown_seconds: e.target.value })} />
          </label>
          <label className="field">
            <span>Auto-resolve after quiet (seconds, 0 = never)</span>
            <input type="number" min={0} value={form.auto_resolve_seconds} onChange={(e) => set({ auto_resolve_seconds: e.target.value })} />
          </label>

          <fieldset className="field span-2">
            <legend>Notify</legend>
            <div className="chips">
              {CHANNELS.map((c) => (
                <label key={c.value} className="field checkbox">
                  <input type="checkbox" checked={form.notify.includes(c.value)} onChange={() => set({ notify: toggleIn(form.notify, c.value) })} />
                  <span>{c.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field checkbox span-2">
            <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
            <span>Enabled</span>
          </label>
        </div>
        <ErrorBanner error={error} />
        <div className="row gap end">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : isNew ? 'Create rule' : 'Save changes'}</button>
        </div>
      </form>
    </Modal>
  );
}
