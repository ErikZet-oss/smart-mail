import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronDown, LoaderCircle, Power, User } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Avatar } from '../../components/Avatar';
import { useToast } from '../../components/toastContext';
import { refreshAfterPersonChange } from '../../lib/sessionCache';
import type { Person } from '../auth/authApi';
import { choosePerson, fetchPicker, initials, PICKER_KEY } from './personsApi';

const TOAST_MS = 2000;
export const PROFILE_PATH = '/settings/identity/profile';

/** Ctrl+Shift+P (UX_SPEC W2b). */
function isShortcut(event: KeyboardEvent): boolean {
  return event.ctrlKey && event.shiftKey && !event.altKey && event.key.toLowerCase() === 'p';
}

/** Rail items that move into this menu when the window is lower than 820 px (G1). */
export type ChipExtra = { id: string; label: string; icon: ReactNode; onSelect?: () => void; hint?: string };

type Props = { onLogout: () => void; extras?: ChipExtra[] };

const ITEMS = '[role="menuitemradio"],[role="menuitem"]:not([aria-disabled="true"])';
const ITEM_CLASS =
  'type-body flex h-8 items-center gap-2.5 rounded-sm px-1.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500';

/**
 * W2b PersonChip (rail bottom): avatar + first name; click or Ctrl+Shift+P opens the menu. With several people it
 * starts with "Kto pracuje?" (one click switches the person of this session — no logout, no PIN, D9); it always holds
 * Môj profil and Odhlásiť, also for a login with one person.
 */
export function PersonChip({ onLogout, extras = [] }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker });
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ left: number; bottom: number }>({ left: 80, bottom: 8 });
  const [switching, setSwitching] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const chipRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const persons = picker.data?.persons ?? [];
  const currentId = picker.data?.current_person_id ?? null;
  const current = persons.find((p) => p.id === currentId);
  const canSwitch = persons.length > 1;

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) chipRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!isShortcut(event)) return;
      event.preventDefault();
      setOpen((value) => !value);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const box = chipRef.current?.getBoundingClientRect();
    if (box) setAnchor({ left: box.right + 8, bottom: Math.max(8, window.innerHeight - box.bottom) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const checked = menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]');
    (checked ?? menuRef.current?.querySelector<HTMLButtonElement>(ITEMS))?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open, close]);

  async function switchTo(person: Person) {
    close(true);
    if (person.id === currentId) return;
    setSwitching(true);
    try {
      const me = await choosePerson(person.id, true);
      queryClient.setQueryData(['me'], me);
      await refreshAfterPersonChange(queryClient);
      toast({ message: t('person.switched', { name: person.first_name }), durationMs: TOAST_MS });
    } catch {
      await picker.refetch();
    } finally {
      setSwitching(false);
    }
  }

  function onMenuKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault();
      close(true);
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>(ITEMS) ?? []);
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = (at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }

  if (!current) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={chipRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('person.chipLabel', { name: current.full_name })}
        aria-keyshortcuts="Control+Shift+P"
        disabled={switching}
        onClick={() => setOpen((value) => !value)}
        className="flex h-[60px] w-[72px] flex-col items-center justify-center gap-1 text-text-on-rail-active hover:bg-bg-rail-active focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500"
      >
        <span className="flex items-center gap-0.5">
          {switching ? (
            <span className="inline-flex size-8 items-center justify-center">
              <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
            </span>
          ) : (
            <Avatar initials={initials(current, 1)} seed={current.id} size={32} />
          )}
          <ChevronDown size={12} aria-hidden="true" />
        </span>
        <span className="type-micro max-w-[64px] truncate">{current.first_name}</span>
      </button>
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          aria-label={canSwitch ? t('person.switch') : t('person.menu')}
          onKeyDown={onMenuKey}
          style={anchor}
          className="fixed z-40 flex w-[280px] flex-col gap-2.5 rounded-md border border-border-default bg-bg-canvas p-3 text-left shadow-e2"
        >
          {canSwitch ? (
            <>
              <p className="type-heading text-text-primary" aria-hidden="true">
                {t('person.switch')}
              </p>
              <div className="flex flex-col gap-0.5">
                {persons.map((person) => {
                  const isCurrent = person.id === currentId;
                  return (
                    <button
                      key={person.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={isCurrent}
                      onClick={() => void switchTo(person)}
                      className={`flex h-11 items-center gap-2.5 rounded-sm px-1.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
                        isCurrent ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                      }`}
                    >
                      <Avatar initials={initials(person, 1)} seed={person.id} size={32} />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className={`truncate text-text-primary ${isCurrent ? 'type-label' : 'type-body'}`}>
                          {person.full_name}
                        </span>
                        {person.function ? (
                          <span className="type-caption truncate text-text-secondary">{person.function}</span>
                        ) : null}
                      </span>
                      {isCurrent ? (
                        <Check size={16} aria-hidden="true" className="shrink-0 text-brand-primary-600" />
                      ) : null}
                    </button>
                  );
                })}
              </div>
              <div role="separator" className="h-px bg-border-default" />
            </>
          ) : (
            <div className="flex items-center gap-2.5 px-1.5">
              <Avatar initials={initials(current, 1)} seed={current.id} size={32} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="type-label truncate text-text-primary">{current.full_name}</span>
                {current.function ? (
                  <span className="type-caption truncate text-text-secondary">{current.function}</span>
                ) : null}
              </span>
            </div>
          )}
          <div className="flex flex-col gap-0.5">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                close(false);
                navigate(PROFILE_PATH);
              }}
              className={`${ITEM_CLASS} text-text-primary hover:bg-bg-subtle`}
            >
              <User size={16} aria-hidden="true" className="shrink-0 text-text-secondary" />
              {t('person.profile')}
            </button>
            {extras.map((extra) => (
              <button
                key={extra.id}
                type="button"
                role="menuitem"
                aria-disabled={extra.onSelect ? undefined : true}
                title={extra.hint}
                onClick={() => {
                  if (!extra.onSelect) return;
                  close(false);
                  extra.onSelect();
                }}
                className={`${ITEM_CLASS} ${extra.onSelect ? 'text-text-primary hover:bg-bg-subtle' : 'cursor-not-allowed text-text-tertiary'}`}
              >
                <span className="flex shrink-0 text-text-secondary" aria-hidden="true">
                  {extra.icon}
                </span>
                {extra.label}
              </button>
            ))}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                close(false);
                onLogout();
              }}
              className={`${ITEM_CLASS} text-danger-600 hover:bg-bg-subtle`}
            >
              <Power size={16} aria-hidden="true" className="shrink-0" />
              {t('rail.logout')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
