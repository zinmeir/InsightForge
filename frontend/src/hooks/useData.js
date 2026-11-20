import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Fetch data and optionally re-fetch on an interval. Pauses while the tab is hidden,
 * cancels in-flight requests on change/unmount, and keeps the previous data while
 * refreshing so charts don't flash.
 */
export function useData(fetcher, deps, { interval = 0 } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async (signal) => {
    try {
      const data = await fetcherRef.current(signal);
      if (!signal.aborted) setState({ data, error: null, loading: false });
    } catch (error) {
      if (!signal.aborted && error.name !== 'AbortError') {
        setState((prev) => ({ ...prev, error, loading: false }));
      }
    }
  }, []);

  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true }));
    run(controller.signal);
    let timer;
    if (interval > 0) {
      timer = setInterval(() => {
        if (document.visibilityState === 'visible') run(controller.signal);
      }, interval);
    }
    return () => {
      controller.abort();
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, interval, tick, run]);

  return { ...state, reload };
}

export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

/** Minimal hash router: "#/explore?service=api" -> { page: 'explore', query: {service: 'api'} } */
export function useHashRoute() {
  const parse = () => {
    const [path, qs = ''] = window.location.hash.replace(/^#\/?/, '').split('?');
    return { page: path || 'overview', query: Object.fromEntries(new URLSearchParams(qs)) };
  };
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function navigate(page, query) {
  const qs = query ? `?${new URLSearchParams(query)}` : '';
  window.location.hash = `#/${page}${qs}`;
}
