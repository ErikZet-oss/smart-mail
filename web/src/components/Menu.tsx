import { Check } from 'lucide-react';
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';

export type MenuEntry =
  | {
      kind: 'item';
      id: string;
      label: string;
      icon?: ReactNode;
      onSelect: () => void;
      disabled?: boolean;
      danger?: boolean;
      /** Radio-like item (Prepnúť schránku): check left and right when current. */
      checked?: boolean;
      hint?: string;
    }
  | { kind: 'label'; id: string; label: string }
  | { kind: 'divider'; id: string };

type Props = {
  label: string;
  entries: MenuEntry[];
  /** Viewport coordinates of the top-left corner (clamped into the window). */
  at: { x: number; y: number };
  width: number;
  onClose: (refocus: boolean) => void;
};

const ITEM = '[role="menuitem"]:not([aria-disabled="true"]),[role="menuitemradio"]:not([aria-disabled="true"])';
const MARGIN = 8;

/** Figma `Menu` / `MenuItem` (32 px rows, section labels, dividers): Arrow keys, Home/End, Esc and Tab close. */
export function Menu({ label, entries, at, width, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(at);

  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    const height = box?.height ?? 0;
    setPos({
      x: Math.max(MARGIN, Math.min(at.x, window.innerWidth - width - MARGIN)),
      y: Math.max(MARGIN, Math.min(at.y, window.innerHeight - height - MARGIN)),
    });
  }, [at, width]);

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>(ITEM)?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [onClose]);

  function onKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault();
      onClose(true);
      return;
    }
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(ITEM) ?? []);
    if (items.length === 0) return;
    const at = items.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    if (event.key === 'ArrowDown') next = (at + 1) % items.length;
    if (event.key === 'ArrowUp') next = (at - 1 + items.length) % items.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = items.length - 1;
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus();
  }

  return (
    <div
      ref={ref}
      role="menu"
      aria-label={label}
      onKeyDown={onKey}
      style={{ left: pos.x, top: pos.y, width }}
      className="fixed z-40 flex flex-col rounded-md border border-border-default bg-bg-canvas py-1.5 text-left shadow-e2"
    >
      {entries.map((entry) => {
        if (entry.kind === 'divider') {
          return (
            <div key={entry.id} role="separator" className="py-1">
              <div className="h-px bg-border-default" />
            </div>
          );
        }
        if (entry.kind === 'label') {
          return (
            <div key={entry.id} className="type-micro flex h-7 items-center px-3 uppercase text-text-tertiary">
              {entry.label}
            </div>
          );
        }
        const radio = entry.checked !== undefined;
        return (
          <button
            key={entry.id}
            type="button"
            role={radio ? 'menuitemradio' : 'menuitem'}
            aria-checked={radio ? entry.checked : undefined}
            aria-disabled={entry.disabled || undefined}
            title={entry.hint}
            onClick={() => {
              if (entry.disabled) return;
              onClose(true);
              entry.onSelect();
            }}
            className={`type-body flex h-8 shrink-0 items-center gap-2.5 px-3 text-left focus-visible:bg-bg-subtle focus-visible:outline-none ${
              entry.disabled
                ? 'cursor-not-allowed text-text-tertiary'
                : `hover:bg-bg-subtle ${entry.danger ? 'text-danger-600' : 'text-text-primary'}`
            }`}
          >
            {radio && entry.checked ? (
              <Check size={16} aria-hidden="true" className="shrink-0" />
            ) : (
              <span className="flex shrink-0" aria-hidden="true">
                {entry.icon}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate">{entry.label}</span>
            {radio && entry.checked ? (
              <Check size={16} aria-hidden="true" className="shrink-0 text-brand-primary-600" />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
