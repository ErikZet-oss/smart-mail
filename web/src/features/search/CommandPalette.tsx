import { useQuery } from '@tanstack/react-query';
import { Building2, FileText, FolderOpen, Mail, Settings, SquarePen, UserRound, Users } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { money as formatMoney, moneySearch } from '../money/moneyApi';
import { useFeatures } from '../system/features';

type Item = {
  id: string;
  group: 'commands' | 'mail' | 'contacts' | 'companies' | 'documents';
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => void;
};

type Props = { onClose: () => void };

/**
 * W11 Paleta príkazov (Ctrl+K): Príkazy, E-maily, Kontakty; with FEATURE_MONEY also Firmy (read cache) and Doklady
 * (invoice number, live — Phase 3g). Asistent comes in Phase 5.
 */
export function CommandPalette({ onClose }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const items: Item[] = useMemo(
    () => [
      {
        id: 'compose',
        group: 'commands',
        label: t('palette.compose'),
        hint: 'C',
        icon: <SquarePen size={16} />,
        run: () => navigate('/compose'),
      },
      {
        id: 'folder',
        group: 'commands',
        label: t('palette.goFolder'),
        hint: 'G I',
        icon: <FolderOpen size={16} />,
        run: () => navigate('/mail/default/inbox'),
      },
      {
        id: 'person',
        group: 'commands',
        label: t('palette.switchPerson'),
        hint: 'Ctrl+Shift+P',
        icon: <UserRound size={16} />,
        run: () => navigate('/who'),
      },
      {
        id: 'settings',
        group: 'commands',
        label: t('palette.settings'),
        icon: <Settings size={16} />,
        run: () => navigate('/settings/general'),
      },
      {
        id: 'inbox',
        group: 'mail',
        label: t('palette.inbox'),
        icon: <Mail size={16} />,
        run: () => navigate('/mail/default/inbox'),
      },
      {
        id: 'search-mail',
        group: 'mail',
        label: t('palette.searchMail'),
        icon: <Mail size={16} />,
        run: () => navigate('/search'),
      },
      {
        id: 'contacts',
        group: 'contacts',
        label: t('palette.contacts'),
        icon: <Users size={16} />,
        run: () => navigate('/contacts/personal'),
      },
    ],
    [navigate, t],
  );

  const features = useFeatures();
  const term = q.trim();
  const money = useQuery({
    queryKey: ['money', 'palette', term],
    queryFn: () => moneySearch(term),
    enabled: features.money && term.length >= 2,
    staleTime: 30_000,
    retry: false,
  });
  const moneyItems: Item[] = useMemo(
    () => [
      ...(money.data?.companies ?? []).map((c) => ({
        id: `company-${c.money_id}`,
        group: 'companies' as const,
        label: c.name,
        hint: c.ico ?? undefined,
        icon: <Building2 size={16} />,
        run: () => navigate(`/contacts/company/${c.money_id}`),
      })),
      ...(money.data?.invoices ?? []).map((i) => ({
        id: `invoice-${i.id}`,
        group: 'documents' as const,
        label: i.number,
        hint: formatMoney(i.remaining),
        icon: <FileText size={16} />,
        run: () => {
          if (i.company_id) navigate(`/contacts/company/${i.company_id}?tab=documents`);
        },
      })),
    ],
    [money.data, navigate],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return [...items.filter((it) => it.label.toLowerCase().includes(needle)), ...moneyItems];
  }, [items, moneyItems, q]);

  const safeActive = Math.min(active, Math.max(0, filtered.length - 1));

  useEffect(() => {
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  function run(item: Item) {
    onClose();
    item.run();
  }

  const groups: { id: Item['group']; label: string }[] = [
    { id: 'commands', label: t('palette.groups.commands') },
    { id: 'mail', label: t('palette.groups.mail') },
    { id: 'contacts', label: t('palette.groups.contacts') },
    { id: 'companies', label: t('palette.groups.companies') },
    { id: 'documents', label: t('palette.groups.documents') },
  ];

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-bg-overlay p-4 pt-[15vh]"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('palette.title')}
        data-testid="command-palette"
        className="flex w-full max-w-[640px] flex-col overflow-hidden rounded-lg bg-bg-canvas shadow-e3"
      >
        <input
          ref={inputRef}
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              onClose();
              return;
            }
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setActive((i) => Math.min(i + 1, Math.max(0, filtered.length - 1)));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setActive((i) => Math.max(i - 1, 0));
            } else if (e.key === 'Enter') {
              e.preventDefault();
              const item = filtered[safeActive];
              if (item) run(item);
            }
          }}
          placeholder={t('palette.placeholder')}
          className="type-body h-12 w-full border-b border-border-default bg-transparent px-4 text-text-primary placeholder:text-text-tertiary focus-visible:outline-none"
        />
        <div className="max-h-[50vh] overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <p className="type-small px-4 py-6 text-text-tertiary">{t('palette.empty')}</p>
          ) : (
            groups.map((g) => {
              const rows = filtered.filter((it) => it.group === g.id);
              if (!rows.length) return null;
              return (
                <div key={g.id} className="mb-2">
                  <p className="type-caption px-4 py-1 text-text-tertiary">{g.label}</p>
                  <ul>
                    {rows.map((it) => {
                      const index = filtered.indexOf(it);
                      const isActive = index === safeActive;
                      return (
                        <li key={it.id}>
                          <button
                            type="button"
                            onMouseEnter={() => setActive(index)}
                            onClick={() => run(it)}
                            className={`flex w-full items-center gap-3 px-4 py-2 text-left ${
                              isActive ? 'bg-brand-primary-50 text-brand-primary-900' : 'text-text-primary'
                            }`}
                          >
                            <span aria-hidden="true" className="text-text-secondary">
                              {it.icon}
                            </span>
                            <span className="type-small min-w-0 flex-1 truncate">{it.label}</span>
                            {it.hint ? (
                              <kbd className="type-caption rounded-sm bg-bg-muted px-1.5 py-0.5 text-text-tertiary">
                                {it.hint}
                              </kbd>
                            ) : null}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

/** Global Ctrl/Cmd+K listener mounting the Phase-1 command palette. */
export function CommandPaletteHost() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return open ? <CommandPalette key="palette" onClose={() => setOpen(false)} /> : null;
}
