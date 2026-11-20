// Thin API client: bearer auth, query-string building, consistent errors, SSE streaming.

const TOKEN_KEY = 'insightforge.session';
const listeners = new Set();

export class ApiError extends Error {
  constructor(status, detail, requestId) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

// --- session -------------------------------------------------------------------

export function loadSession() {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw);
    return session.expiresAt > Date.now() ? session : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    if (session) localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): session lives in memory only */
  }
}

export function onUnauthorized(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function authHeaders() {
  const session = loadSession();
  return session?.token ? { Authorization: `Bearer ${session.token}` } : {};
}

// --- requests ------------------------------------------------------------------

export function toQuery(params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, v));
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export async function api(path, { method = 'GET', params, body, signal, raw = false } = {}) {
  const headers = { ...authHeaders() };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${path}${toQuery(params)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (res.status === 401 && !path.endsWith('/auth/login')) {
    listeners.forEach((fn) => fn());
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = Array.isArray(data.detail)
        ? data.detail.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ')
        : data.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, res.headers.get('x-request-id'));
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

export async function download(path, params, filename) {
  const res = await api(path, { params, raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- live tail (SSE over fetch, so the Authorization header can be sent) ---------

const sleep = (ms, signal) =>
  new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      resolve();
    });
  });

export async function streamLogs({ params, onLogs, onStatus, signal }) {
  let backoff = 1000;
  while (!signal.aborted) {
    try {
      onStatus('connecting');
      const res = await fetch(`/api/v1/stream${toQuery(params)}`, {
        headers: { ...authHeaders(), Accept: 'text/event-stream' },
        signal,
      });
      if (res.status === 401) {
        listeners.forEach((fn) => fn());
        return;
      }
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      onStatus('live');
      backoff = 1000;
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value.replace(/\r\n/g, '\n');
        let split;
        while ((split = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          let event = 'message';
          const data = [];
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
          }
          if (event === 'logs' && data.length) onLogs(JSON.parse(data.join('\n')));
        }
      }
    } catch (err) {
      if (signal.aborted) return;
      console.warn('live tail disconnected', err);
    }
    if (signal.aborted) return;
    onStatus('reconnecting');
    await sleep(backoff, signal);
    backoff = Math.min(backoff * 2, 15000);
  }
}
