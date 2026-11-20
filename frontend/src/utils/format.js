export const LEVELS = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'];

// Badge dot colors (status palette). Always shown next to the level's text label.
export const LEVEL_COLORS = {
  DEBUG: '#8a8984',
  INFO: '#3987e5',
  WARN: '#fab219',
  ERROR: '#ec835a',
  CRITICAL: '#d03b3b',
};

// Volume chart series - validated for color-vision deficiency on the dark surface (#1a1a19).
export const VOLUME_SERIES = [
  { key: 'info', label: 'Info & debug', color: '#3987e5', levels: ['DEBUG', 'INFO'] },
  { key: 'warn', label: 'Warnings', color: '#c98500', levels: ['WARN'] },
  { key: 'error', label: 'Errors & critical', color: '#d55181', levels: ['ERROR', 'CRITICAL'] },
];

export const SEVERITY_COLORS = { info: '#3987e5', warning: '#fab219', critical: '#d03b3b' };

export const TIME_RANGES = [
  { value: 'now-15m', label: 'Last 15 minutes' },
  { value: 'now-1h', label: 'Last hour' },
  { value: 'now-6h', label: 'Last 6 hours' },
  { value: 'now-24h', label: 'Last 24 hours' },
  { value: 'now-7d', label: 'Last 7 days' },
  { value: 'now-30d', label: 'Last 30 days' },
];

const RANGE_SECONDS = { m: 60, h: 3600, d: 86400 };
export function rangeSeconds(value) {
  const m = /^now-(\d+)([mhd])$/.exec(value);
  return m ? Number(m[1]) * RANGE_SECONDS[m[2]] : 3600;
}

const numberFmt = new Intl.NumberFormat();
const compactFmt = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });

export const formatNumber = (n) => numberFmt.format(n ?? 0);
export const formatCompact = (n) => compactFmt.format(n ?? 0);
export const formatPercent = (ratio, digits = 1) => `${((ratio ?? 0) * 100).toFixed(digits)}%`;

export function formatTime(iso, { withDate = false, withMillis = false } = {}) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    ...(withMillis ? { fractionalSecondDigits: 3 } : {}),
  });
  if (!withDate) return time;
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${time}`;
}

export function formatRelative(iso) {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatDuration(seconds) {
  if (!seconds) return 'never';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}
