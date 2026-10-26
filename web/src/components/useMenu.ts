import { useCallback, useRef, useState } from 'react';

/** Opens a menu below an anchor button, or at the pointer for context menus. */
export function useMenu<T>() {
  const [state, setState] = useState<{ at: { x: number; y: number }; target: T } | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);
  const close = useCallback((refocus: boolean) => {
    setState(null);
    if (refocus) anchorRef.current?.focus();
  }, []);
  return {
    state,
    openBelow(anchor: HTMLElement, target: T, alignRight = false, width = 0) {
      const box = anchor.getBoundingClientRect();
      anchorRef.current = anchor;
      setState({ at: { x: alignRight ? box.right - width : box.left, y: box.bottom + 4 }, target });
    },
    openAt(x: number, y: number, target: T, anchor: HTMLElement | null) {
      anchorRef.current = anchor;
      setState({ at: { x, y }, target });
    },
    close,
  };
}
