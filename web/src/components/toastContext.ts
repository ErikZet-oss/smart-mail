import { createContext, useContext, useMemo } from 'react';

export type ToastKind = 'info' | 'success' | 'error';
export type ToastAction = { label: string; onClick: () => void };
export type ToastInput = {
  kind?: ToastKind;
  message: string;
  action?: ToastAction;
  durationMs?: number;
  /** Click on the message itself (sent confirmation opens the message in Odoslané). */
  onActivate?: () => void;
};

export const ToastContext = createContext<(toast: ToastInput) => void>(() => undefined);

export function useToast(): (toast: ToastInput) => void {
  return useContext(ToastContext);
}

/** Memoised toast helpers for a screen. */
export function useToasts() {
  const push = useToast();
  return useMemo(
    () => ({
      info: (message: string, durationMs?: number) => push({ kind: 'info', message, durationMs }),
      success: (message: string, action?: ToastAction) => push({ kind: 'success', message, action }),
      error: (message: string, action?: ToastAction) => push({ kind: 'error', message, action }),
    }),
    [push],
  );
}
