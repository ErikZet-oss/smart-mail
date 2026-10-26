import { useSyncExternalStore } from 'react';

/** Tailwind `sm` breakpoint: below it the mobile frames (M-…) apply. */
export const MOBILE_QUERY = '(max-width: 639.98px)';

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== 'function') return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches,
    () => false,
  );
}
