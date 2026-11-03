import { useQuery } from '@tanstack/react-query';
import { Search, X } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { api } from '../../lib/api';
import { booksKey, fetchBooks, fetchContacts, fetchGroups, type Contact } from '../contacts/contactsApi';
import { contactRows, matches, selectAllState, toggleAll, type PickEntry, type PickTarget } from './addressPicker';

type Source = 'recent' | 'personal' | 'shared' | 'branches' | 'money';
const SOURCES: Source[] = ['recent', 'personal', 'shared', 'branches', 'money'];
type Summary = Record<Source, number>;
type MoneyPage = { items: PickEntry[]; total: number; page: number };

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('') || '?';

function useDebounced(value: string, ms = 250): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

/**
 * W4g Adresár – výber príjemcov (Figma `192:89654`) and, on mobile, M4b (`195:3`) as a full-screen sheet (#203).
 * Read-only: Money – adresár comes from the read cache; nothing is written anywhere until the person adds the picked
 * addresses to Komu / Kópia / Skrytá kópia of the message.
 */
export function AddressPicker({
  target,
  mobile,
  onClose,
  onAdd,
}: {
  target: PickTarget;
  mobile: boolean;
  onClose: () => void;
  onAdd: (target: PickTarget, picked: PickEntry[]) => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState<Source>('recent');
  const [q, setQ] = useState('');
  const term = useDebounced(q);
  const [selected, setSelected] = useState<Map<string, PickEntry>>(new Map());
  const [mobileTarget, setMobileTarget] = useState<PickTarget>(target);

  const summary = useQuery({
    queryKey: ['contacts', 'picker', 'summary'],
    queryFn: () => api<Summary>('GET', '/api/contacts/picker/summary'),
  });
  const books = useQuery({ queryKey: booksKey, queryFn: fetchBooks });
  const bookId =
    source === 'personal' || source === 'shared' ? books.data?.find((b) => b.kind === source)?.id : undefined;
  const contacts = useQuery({
    queryKey: ['contacts', bookId, term],
    queryFn: () => fetchContacts(bookId ?? '', term),
    enabled: !!bookId,
  });
  const groups = useQuery({
    queryKey: ['contacts', 'groups', bookId],
    queryFn: () => fetchGroups(bookId ?? ''),
    enabled: !!bookId,
  });
  const recent = useQuery({
    queryKey: ['contacts', 'picker', 'recent'],
    queryFn: () => api<PickEntry[]>('GET', '/api/contacts/picker/recent'),
    enabled: source === 'recent',
  });
  const branches = useQuery({
    queryKey: ['contacts', 'picker', 'branches'],
    queryFn: () => api<PickEntry[]>('GET', '/api/contacts/picker/branches'),
    enabled: source === 'branches',
  });
  const money = useQuery({
    queryKey: ['contacts', 'picker', 'money', term],
    queryFn: () =>
      api<MoneyPage>('GET', `/api/contacts/picker/money?q=${encodeURIComponent(term.trim())}`, undefined, {
        global: false,
      }),
    enabled: source === 'money' && term.trim().length >= 2,
    retry: false,
  });

  const allContacts: Contact[] = useMemo(() => contacts.data ?? [], [contacts.data]);
  const groupRows = (groups.data ?? [])
    .map((g) => ({ ...g, members: allContacts.filter((c) => c.group_ids.includes(g.id)).flatMap(contactRows) }))
    .filter((g) => g.members.length > 0 && (!term.trim() || g.name.toLowerCase().includes(term.trim().toLowerCase())));
  const rows: PickEntry[] = useMemo(() => {
    if (source === 'personal' || source === 'shared') return allContacts.flatMap(contactRows);
    if (source === 'recent') return (recent.data ?? []).filter((e) => matches(e, term));
    if (source === 'branches') return (branches.data ?? []).filter((e) => matches(e, term));
    return money.data?.items ?? [];
  }, [source, allContacts, recent.data, branches.data, money.data, term]);
  const loading =
    (bookId ? contacts.isLoading : false) ||
    (source === 'recent' && recent.isLoading) ||
    (source === 'branches' && branches.isLoading) ||
    (source === 'money' && money.isFetching);
  const all = selectAllState(rows, selected);
  const toggle = (e: PickEntry) => {
    const next = new Map(selected);
    if (next.has(e.key)) next.delete(e.key);
    else next.set(e.key, e);
    setSelected(next);
  };
  const toggleGroup = (members: PickEntry[]) => setSelected(toggleAll(members, selected));
  const add = (to: PickTarget) => onAdd(to, [...selected.values()]);
  const count = selected.size;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('input[type="search"]')?.focus();
    return () => opener?.focus();
  }, []);

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    const target = event.target as HTMLElement;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && target.dataset.pickRow) {
      event.preventDefault();
      const items = Array.from(box.current?.querySelectorAll<HTMLElement>('[data-pick-row]') ?? []);
      const i = items.indexOf(target);
      items[event.key === 'ArrowDown' ? Math.min(i + 1, items.length - 1) : Math.max(i - 1, 0)]?.focus();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = Array.from(
      box.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),[tabindex="0"]') ?? [],
    );
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const sourceLabel = (s: Source) => t(`compose.picker.sources.${s}${mobile ? 'Short' : ''}`);
  const searchBox = (
    <label className="relative block">
      <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t('compose.picker.search')}
        aria-label={t('compose.picker.search')}
        className="type-body h-9 w-full rounded-md bg-bg-muted pl-9 pr-3 text-text-primary placeholder:text-text-tertiary"
        data-testid="picker-search"
      />
    </label>
  );

  const checkboxCls =
    'h-4 w-4 shrink-0 cursor-pointer rounded-xs border-border-strong accent-brand-primary-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500';
  const list = (
    <div className="flex min-h-0 flex-1 flex-col">
      {rows.length > 0 ? (
        <label className="type-small flex items-center gap-3 px-2 py-2 text-text-secondary">
          <input
            type="checkbox"
            className={checkboxCls}
            checked={all === true}
            ref={(el) => {
              if (el) el.indeterminate = all === 'mixed';
            }}
            aria-checked={all === 'mixed' ? 'mixed' : all}
            onChange={() => setSelected(toggleAll(rows, selected))}
            data-testid="picker-select-all"
          />
          <span className="flex-1">{t('compose.picker.selectAll')}</span>
          <span>
            {t('compose.picker.count', { count: source === 'money' ? (money.data?.total ?? 0) : rows.length })}
          </span>
        </label>
      ) : null}
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto" data-testid="picker-list">
        {groupRows.map((g) => {
          const state = selectAllState(g.members, selected);
          return (
            <li key={`g-${g.id}`}>
              <label
                className={`flex cursor-pointer items-center gap-3 rounded-md px-2 ${mobile ? 'min-h-14' : 'min-h-12'} ${
                  state === true ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                }`}
              >
                <input
                  type="checkbox"
                  className={checkboxCls}
                  checked={state === true}
                  ref={(el) => {
                    if (el) el.indeterminate = state === 'mixed';
                  }}
                  onChange={() => toggleGroup(g.members)}
                  data-pick-row="group"
                />
                <Avatar initials={initials(g.name)} seed={g.id} size={32} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="type-label truncate text-text-primary">{g.name}</span>
                  <span className="type-caption text-text-secondary">
                    {t('compose.picker.groupMembers', { count: g.members.length })}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
        {rows.map((e) => {
          const on = selected.has(e.key);
          return (
            <li key={e.key}>
              <label
                className={`flex cursor-pointer items-center gap-3 rounded-md px-2 ${mobile ? 'min-h-14' : 'min-h-12'} ${
                  on ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                }`}
                data-testid={`picker-row-${e.key}`}
              >
                <input
                  type="checkbox"
                  className={checkboxCls}
                  checked={on}
                  onChange={() => toggle(e)}
                  data-pick-row="1"
                  aria-label={`${e.name} ${e.email}`}
                />
                <Avatar initials={initials(e.name)} seed={e.key} size={32} />
                {mobile ? (
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="type-label truncate text-text-primary">{e.name}</span>
                    <span className="type-caption truncate text-text-secondary">
                      {e.email}
                      {e.organization ? ` · ${e.organization}` : ''}
                    </span>
                  </span>
                ) : (
                  <>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="type-label truncate text-text-primary">{e.name}</span>
                      {e.organization ? (
                        <span className="type-caption truncate text-text-secondary">{e.organization}</span>
                      ) : null}
                    </span>
                    <span className="type-small truncate text-text-secondary">{e.email}</span>
                  </>
                )}
              </label>
            </li>
          );
        })}
        {!loading && rows.length === 0 && groupRows.length === 0 ? (
          <li className="type-body px-2 py-8 text-center text-text-secondary" data-testid="picker-empty">
            {source === 'money' && term.trim().length < 2
              ? t('compose.picker.moneyHint')
              : source === 'money' && money.isError
                ? t('compose.picker.moneyOffline')
                : term.trim()
                  ? t('compose.picker.noResult')
                  : t('compose.picker.empty')}
          </li>
        ) : null}
        {loading ? (
          <li className="type-small px-2 py-4 text-text-secondary" aria-busy="true">
            {t('compose.picker.loading')}
          </li>
        ) : null}
      </ul>
    </div>
  );

  if (mobile) {
    return createPortal(
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        className="fixed inset-0 z-50 flex flex-col bg-bg-canvas"
        data-testid="address-picker"
      >
        <header className="flex h-14 items-center gap-3 border-b border-border-default px-4">
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="text-text-secondary">
            <X size={22} aria-hidden="true" />
          </button>
          <h2 id={titleId} className="type-heading text-text-primary">
            {t('compose.picker.mobileTitle')}
          </h2>
        </header>
        <div className="flex flex-col gap-3 px-4 pt-3">
          {searchBox}
          <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1" role="tablist">
            {SOURCES.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={source === s}
                onClick={() => setSource(s)}
                className={`type-small h-8 shrink-0 rounded-full px-3 ${
                  source === s
                    ? 'bg-brand-primary-600 text-text-on-primary'
                    : 'border border-border-default text-text-primary'
                }`}
              >
                {sourceLabel(s)}
              </button>
            ))}
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col px-2">{list}</div>
        <footer className="flex flex-col gap-3 border-t border-border-default px-4 pb-[calc(env(safe-area-inset-bottom)+12px)] pt-3">
          <div className="flex items-center gap-2">
            <span className="type-small flex-1 text-text-secondary">{t('compose.picker.selectedTo', { count })}</span>
            {(['to', 'cc', 'bcc'] as const).map((tg) => (
              <button
                key={tg}
                type="button"
                aria-pressed={mobileTarget === tg}
                onClick={() => setMobileTarget(tg)}
                className={`type-small h-7 rounded-full px-3 ${
                  mobileTarget === tg ? 'bg-brand-primary-600 text-text-on-primary' : 'border border-border-default'
                }`}
              >
                {t(`compose.picker.targets.${tg}`)}
              </button>
            ))}
          </div>
          <Button size="lg" disabled={count === 0} onClick={() => add(mobileTarget)} data-testid="picker-add">
            {t('compose.picker.addN', { count })}
          </Button>
        </footer>
      </div>,
      document.body,
    );
  }

  const order: PickTarget[] = ['bcc', 'cc', 'to'];
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4" onClick={onClose}>
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        onClick={(e) => e.stopPropagation()}
        className="flex h-[min(624px,90vh)] w-[min(824px,100%)] flex-col overflow-hidden rounded-lg bg-bg-canvas shadow-lg"
        data-testid="address-picker"
      >
        <header className="flex items-center justify-between border-b border-border-default px-5 py-4">
          <h2 id={titleId} className="type-heading text-text-primary">
            {t('compose.picker.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="inline-flex size-8 items-center justify-center rounded-sm border border-border-default text-text-primary"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <div className="flex min-h-0 flex-1">
          <nav
            className="flex w-[220px] shrink-0 flex-col gap-1 bg-bg-subtle p-3"
            aria-label={t('compose.picker.books')}
          >
            <span className="type-micro px-2 pb-1 uppercase tracking-wide text-text-secondary">
              {t('compose.picker.books')}
            </span>
            {SOURCES.map((s) => (
              <button
                key={s}
                type="button"
                aria-current={source === s ? 'true' : undefined}
                onClick={() => setSource(s)}
                className={`type-body flex h-9 items-center justify-between rounded-sm px-2 text-left ${
                  source === s ? 'bg-brand-primary-50 text-brand-primary-700' : 'text-text-primary hover:bg-bg-muted'
                }`}
                data-testid={`picker-source-${s}`}
              >
                <span>{sourceLabel(s)}</span>
                <span className="type-caption tabular-nums text-text-secondary">
                  {summary.data ? summary.data[s].toLocaleString('sk-SK') : ''}
                </span>
              </button>
            ))}
            <span className="type-caption px-2 pt-2 text-text-secondary">{t('compose.picker.moneyReadOnly')}</span>
          </nav>
          <div className="flex min-w-0 flex-1 flex-col gap-2 p-4">
            {searchBox}
            {list}
          </div>
        </div>
        <footer className="flex items-center gap-2 border-t border-border-default px-5 py-4">
          <span className="type-label flex-1 text-text-primary" data-testid="picker-count">
            {t('compose.picker.selected', { count })}
          </span>
          <button type="button" onClick={onClose} className="type-label h-8 px-3 text-brand-primary-600">
            {t('common.cancel')}
          </button>
          {order.map((tg) => (
            <Button
              key={tg}
              variant={tg === target ? 'primary' : 'secondary'}
              disabled={count === 0}
              onClick={() => add(tg)}
              data-testid={`picker-add-${tg}`}
            >
              {t(`compose.picker.add.${tg}`)}
            </Button>
          ))}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
