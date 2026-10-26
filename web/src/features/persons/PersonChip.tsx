import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronDown, LoaderCircle } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Avatar } from '../../components/Avatar';
import { Toast } from '../../components/Toast';
import type { Person } from '../auth/authApi';
import { choosePerson, fetchPicker, initials, PICKER_KEY } from './personsApi';

const TOAST_MS = 2000;

/** Ctrl+Shift+P (UX_SPEC W2b). */
function isShortcut(event: KeyboardEvent): boolean {
  return event.ctrlKey && event.shiftKey && !event.altKey && event.key.toLowerCase() === 'p';
}

/**
 * W2b PersonChip (rail bottom): avatar + first name; click or Ctrl+Shift+P opens "Kto pracuje?" with the people of
 * the branch, one click switches the person of this session (no logout, no PIN — D9) and a toast confirms it.
 */
export function PersonChip() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker });
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
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
    if (!canSwitch) return;
    const onKey = (event: KeyboardEvent) => {
      if (!isShortcut(event)) return;
      event.preventDefault();
      setOpen((value) => !value);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canSwitch]);

  useEffect(() => {
    if (!open) return;
    const items = menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]');
    const checked = menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]');
    (checked ?? items?.[0])?.focus();
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open, close]);

  async function switchTo(person: Person) {
    if (person.id === currentId) {
      close(true);
      return;
    }
    close(true);
    setSwitching(true);
    try {
      const me = await choosePerson(person.id, true);
      queryClient.setQueryData(['me'], me);
      await queryClient.invalidateQueries({ queryKey: PICKER_KEY });
      setToast(t('person.switched', { name: person.first_name }));
    } catch {
      await picker.refetch();
    } finally {
      setSwitching(false);
    }
  }

  function onMenuKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close(true);
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? []);
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = (at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }

  const closeToast = useCallback(() => setToast(null), []);

  if (!current) return null;

  const face = (
    <>
      <span className="flex items-center gap-0.5">
        {switching ? (
          <span className="inline-flex size-8 items-center justify-center">
            <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
          </span>
        ) : (
          <Avatar initials={initials(current, 1)} seed={current.id} size={32} />
        )}
        {canSwitch ? <ChevronDown size={12} aria-hidden="true" /> : null}
      </span>
      <span className="type-micro max-w-[64px] truncate">{current.first_name}</span>
    </>
  );

  return (
    <div ref={rootRef} className="relative">
      {canSwitch ? (
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
          {face}
        </button>
      ) : (
        <div
          className="flex h-[60px] w-[72px] flex-col items-center justify-center gap-1 text-text-on-rail-active"
          aria-label={t('person.chipLabel', { name: current.full_name })}
          role="img"
        >
          {face}
        </div>
      )}
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          aria-label={t('person.switch')}
          onKeyDown={onMenuKey}
          className="absolute bottom-0 left-full z-40 ml-2 flex w-[280px] flex-col gap-2.5 rounded-md border border-border-default bg-bg-canvas p-3 text-left shadow-e2"
        >
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
        </div>
      ) : null}
      {toast ? (
        <Toast message={toast} closeLabel={t('person.close')} durationMs={TOAST_MS} onClose={closeToast} />
      ) : null}
    </div>
  );
}
