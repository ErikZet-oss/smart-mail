import { ChevronRight, Lock, Search, X } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import type { NavSection } from './settingsApi';
import { buildNavItems, isItemActive, type SettingsNavItem } from './settingsNavModel';

type SearchHit = { key: string; title: string; path: string; to: string };

const fold = (value: string) => value.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/** Client-side search over section and subsection titles (Figma „W12 Hľadanie v nastaveniach“, 77:76671). */
function searchHits(sections: NavSection[], items: SettingsNavItem[], query: string): SearchHit[] {
  const q = fold(query.trim());
  if (!q) return [];
  const hits: SearchHit[] = [];
  for (const item of items) {
    if (fold(item.title).includes(q)) hits.push({ key: item.key, title: item.title, path: '', to: item.to });
  }
  for (const s of sections) {
    if (s.path === 'identity') continue; // identity subs are already top-level rows
    const parent = items.find((i) => i.section === s.path)?.title ?? s.title;
    for (const sub of s.subs) {
      if (fold(sub.title).includes(q)) {
        hits.push({
          key: `${s.path}/${sub.path}`,
          title: sub.title,
          path: parent,
          to: `/settings/${s.path}/${sub.path}`,
        });
      }
    }
  }
  return hits.slice(0, 8);
}

type Props = { sections: NavSection[]; activeSection: string; sub?: string };

/** W12 left settings column: title, „Hľadať v nastaveniach“, rows with icons, „SPRÁVA 🔒“ group. */
export function SettingsNav({ sections, activeSection, sub }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const items = useMemo(() => buildNavItems(sections), [sections]);
  const [query, setQuery] = useState('');
  const hits = useMemo(() => searchHits(sections, items, query), [sections, items, query]);
  const [highlight, setHighlight] = useState(0);
  const searching = query.trim().length > 0;
  const personal = items.filter((i) => !i.admin);
  const admin = items.filter((i) => i.admin);

  const go = (to: string) => {
    setQuery('');
    navigate(to);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') setQuery('');
    else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlight((h) => Math.min(h + 1, Math.max(hits.length - 1, 0)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (event.key === 'Enter' && hits[highlight]) {
      event.preventDefault();
      go(hits[highlight].to);
    }
  };

  const row = (item: SettingsNavItem) => {
    const active = isItemActive(item, activeSection, sub);
    const Icon = item.icon;
    return (
      <li key={item.key}>
        <Link
          to={item.to}
          aria-current={active ? 'page' : undefined}
          className={`type-small mx-2 flex h-8 items-center gap-2.5 rounded-sm px-2.5 ${
            active ? 'bg-brand-primary-50 font-semibold text-brand-primary-700' : 'text-text-primary hover:bg-bg-muted'
          }`}
        >
          <Icon size={16} aria-hidden className={active ? 'text-brand-primary-700' : 'text-text-secondary'} />
          <span className="min-w-0 flex-1 truncate">{item.title}</span>
        </Link>
      </li>
    );
  };

  return (
    <nav
      aria-label={t('settings.nav')}
      className="relative z-10 flex w-[var(--layout-settings-nav)] shrink-0 flex-col border-r border-border-default bg-bg-subtle"
    >
      <h2 className="type-body-strong flex h-14 shrink-0 items-center justify-center text-text-primary">
        {t('settings.title')}
      </h2>
      <div className="relative shrink-0 px-3 pb-2">
        <Search size={16} aria-hidden className="pointer-events-none absolute left-6 top-2.5 text-text-secondary" />
        <input
          type="search"
          role="combobox"
          aria-expanded={searching}
          aria-controls="settings-search-results"
          aria-label={t('settings.search')}
          placeholder={t('settings.search')}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setHighlight(0);
          }}
          onKeyDown={onKeyDown}
          className={`type-body h-[var(--size-input)] w-full rounded-sm border pl-9 pr-8 text-text-primary placeholder:text-text-tertiary focus:outline-none [&::-webkit-search-cancel-button]:hidden ${
            searching ? 'border-brand-primary-500 bg-bg-canvas' : 'border-transparent bg-bg-muted'
          }`}
        />
        {searching ? (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label={t('settings.searchClear')}
            className="absolute right-5 top-2 flex size-5 items-center justify-center rounded-xs text-text-secondary hover:bg-bg-muted"
          >
            <X size={14} aria-hidden />
          </button>
        ) : null}
        {searching ? (
          <ul
            id="settings-search-results"
            role="listbox"
            aria-label={t('settings.searchResults')}
            className="absolute left-3 top-full z-20 mt-1 w-[420px] max-w-[calc(100vw-96px)] overflow-hidden rounded-md border border-border-default bg-bg-canvas py-1 shadow-e2"
          >
            {hits.length === 0 ? (
              <li className="type-small px-3 py-2 text-text-secondary">{t('settings.searchEmpty')}</li>
            ) : (
              hits.map((hit, i) => (
                <li key={hit.key} role="option" aria-selected={i === highlight}>
                  <button
                    type="button"
                    onMouseEnter={() => setHighlight(i)}
                    onClick={() => go(hit.to)}
                    className={`flex w-full flex-col items-start px-3 py-2 text-left ${
                      i === highlight ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                    }`}
                  >
                    <span className={`type-small ${i === highlight ? 'text-brand-primary-700' : 'text-text-primary'}`}>
                      {hit.title}
                    </span>
                    {hit.path ? <span className="type-caption text-text-secondary">{hit.path}</span> : null}
                  </button>
                </li>
              ))
            )}
          </ul>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ul className="flex flex-col pb-3">{personal.map(row)}</ul>
        {admin.length > 0 ? (
          <>
            <p className="type-micro mx-2 flex items-center gap-1.5 px-2.5 pb-1.5 pt-3 uppercase text-text-tertiary">
              {t('settings.adminGroup')}
              <Lock size={12} aria-hidden />
            </p>
            <ul className="flex flex-col pb-3">{admin.map(row)}</ul>
          </>
        ) : null}
      </div>
    </nav>
  );
}

/** Middle column (Figma `MiddleList`, 280 px) with the subsections of the active section. */
export function SettingsSubList({ section, sub }: { section: NavSection; sub?: string }) {
  const current = sub ?? section.subs[0]?.path;
  return (
    <ul
      aria-label={section.title}
      className="w-[var(--layout-settings-list)] shrink-0 overflow-y-auto border-r border-border-default bg-bg-canvas"
    >
      {section.subs.map((s) => {
        const active = s.path === current;
        return (
          <li key={s.id} className="border-b border-border-default">
            <Link
              to={`/settings/${section.path}/${s.path}`}
              aria-current={active ? 'page' : undefined}
              className={`type-small block px-3.5 py-2.5 ${
                active
                  ? 'bg-brand-primary-50 font-semibold text-brand-primary-700'
                  : 'text-text-primary hover:bg-bg-subtle'
              }`}
            >
              {s.title}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Tabs for sections whose subsections are tabs in Figma (W12-11 Pobočky a osoby). */
export function SettingsSubTabs({ section, sub }: { section: NavSection; sub?: string }) {
  const current = sub ?? section.subs[0]?.path;
  return (
    <div role="tablist" aria-label={section.title} className="flex gap-6 border-b border-border-default">
      {section.subs.map((s) => {
        const active = s.path === current;
        return (
          <Link
            key={s.id}
            role="tab"
            aria-selected={active}
            to={`/settings/${section.path}/${s.path}`}
            className={`type-small -mb-px flex h-[var(--size-tab)] items-center border-b-2 ${
              active
                ? 'border-brand-primary-600 font-semibold text-brand-primary-700'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            {s.title}
          </Link>
        );
      })}
    </div>
  );
}

/** Breadcrumb in the content header: „Nastavenia › Nastavenia › Používateľské rozhranie“ (Figma `RightHeader`). */
export function SettingsBreadcrumb({ parts }: { parts: string[] }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t('settings.breadcrumb')} className="min-w-0">
      <ol className="type-small flex min-w-0 items-center gap-1.5 text-text-secondary">
        {parts.map((part, i) => (
          <li key={`${part}-${i}`} className="flex min-w-0 items-center gap-1.5">
            {i > 0 ? <ChevronRight size={12} aria-hidden className="shrink-0" /> : null}
            <span className={`truncate ${i === parts.length - 1 ? 'text-text-primary' : ''}`}>{part}</span>
          </li>
        ))}
      </ol>
    </nav>
  );
}
