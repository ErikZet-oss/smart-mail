import { Info, X } from 'lucide-react';
import { useEffect } from 'react';

type Props = { message: string; closeLabel: string; durationMs: number; onClose: () => void };

/** Figma `Toast` (info, dark): bottom left next to the rail, closes itself after `durationMs`. */
export function Toast({ message, closeLabel, durationMs, onClose }: Props) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, durationMs);
    return () => window.clearTimeout(timer);
  }, [message, durationMs, onClose]);

  return (
    <div
      role="status"
      className="type-small fixed bottom-9 left-[88px] z-50 flex w-[360px] max-w-[calc(100vw-104px)] items-center gap-2.5 rounded-md bg-bg-rail py-2.5 pl-3.5 pr-3 text-text-on-rail-active shadow-e2"
    >
      <Info size={18} aria-hidden="true" className="shrink-0" />
      <span className="flex-1">{message}</span>
      <button
        type="button"
        onClick={onClose}
        aria-label={closeLabel}
        className="shrink-0 rounded-xs text-text-on-rail hover:text-text-on-rail-active focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
