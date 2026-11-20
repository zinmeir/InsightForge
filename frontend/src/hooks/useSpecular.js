// Liquid Glass "specular" highlight: glass surfaces catch a soft light where the pointer is.
// One passive listener for the whole app writes --mx/--my on the hovered glass element;
// the actual highlight is pure CSS (see `.glass::after` in styles.css).

const SELECTOR = '.glass, .btn, .nav-item, .chip, .capsule-btn';

export function installSpecularHighlights() {
  if (typeof window === 'undefined') return () => {};
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return () => {};
  let frame = 0;
  let last = null;
  const onMove = (e) => {
    last = e;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const el = last.target instanceof Element ? last.target.closest(SELECTOR) : null;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      el.style.setProperty('--mx', `${last.clientX - rect.left}px`);
      el.style.setProperty('--my', `${last.clientY - rect.top}px`);
    });
  };
  window.addEventListener('pointermove', onMove, { passive: true });
  return () => window.removeEventListener('pointermove', onMove);
}
