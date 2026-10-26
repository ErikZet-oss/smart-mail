import { CircleCheck, CircleX, Info, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ToastContext, type ToastInput, type ToastKind } from './toastContext';

type ToastItem = ToastInput & { id: number };

const MAX = 3;
const PLAIN_MS = 5000;
const WITH_ACTION_MS = 10000;

/** G4 toast stack: bottom-left next to the rail, max 3, 5 s (10 s with an action), paused while hovered. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((toast: ToastInput) => {
    const id = nextId.current++;
    setItems((current) => [...current, { ...toast, id }].slice(-MAX));
  }, []);
  const remove = useCallback((id: number) => setItems((current) => current.filter((t) => t.id !== id)), []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      {items.length > 0 ? (
        <div className="fixed bottom-9 left-[88px] z-50 flex w-[360px] max-w-[calc(100vw-104px)] flex-col gap-2">
          {items.map((item) => (
            <ToastView key={item.id} item={item} onClose={() => remove(item.id)} />
          ))}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

const ICON: Record<ToastKind, ReactNode> = {
  info: <Info size={18} aria-hidden="true" className="shrink-0" />,
  success: <CircleCheck size={18} aria-hidden="true" className="shrink-0" />,
  error: <CircleX size={18} aria-hidden="true" className="shrink-0" />,
};

function ToastView({ item, onClose }: { item: ToastItem; onClose: () => void }) {
  const { t } = useTranslation();
  const [paused, setPaused] = useState(false);
  const total = item.durationMs ?? (item.action ? WITH_ACTION_MS : PLAIN_MS);
  const left = useRef(total);
  const startedAt = useRef(0);

  useEffect(() => {
    if (paused) return;
    startedAt.current = Date.now();
    const timer = window.setTimeout(onClose, left.current);
    return () => {
      window.clearTimeout(timer);
      left.current -= Date.now() - startedAt.current;
    };
  }, [paused, onClose]);

  const kind = item.kind ?? 'info';
  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className="type-small flex items-center gap-2.5 rounded-md bg-bg-rail py-2.5 pl-3.5 pr-3 text-text-on-rail-active shadow-e2"
    >
      {ICON[kind]}
      <span className="flex-1">{item.message}</span>
      {item.action ? (
        <button
          type="button"
          onClick={() => {
            item.action?.onClick();
            onClose();
          }}
          className="type-label shrink-0 rounded-xs text-brand-primary-400 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
        >
          {item.action.label}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onClose}
        aria-label={t('common.close')}
        className="shrink-0 rounded-xs text-text-on-rail hover:text-text-on-rail-active focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
