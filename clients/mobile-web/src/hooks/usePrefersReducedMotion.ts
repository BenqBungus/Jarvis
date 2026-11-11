import { useEffect, useState } from 'preact/hooks';

/**
 * Mirrors `prefers-reduced-motion` into JS for the few places a component
 * needs to know it (not just CSS) -- e.g. skipping a JS-driven animation
 * loop entirely rather than relying on CSS alone to hide its effect. All
 * *styling* still lives behind the CSS media query itself (motion is
 * opt-in, not opt-out, everywhere in styles/global.css); this hook is for
 * behavior, not paint.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = () => setReduced(query.matches);
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);

  return reduced;
}
