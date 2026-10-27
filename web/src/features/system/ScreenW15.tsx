import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Dialog } from '../../components/Dialog';
import { Button } from '../../components/Button';

/** Phase-1 shortcuts only (UX_SPEC §6 — no AI / Doklady / Asistent / Dnes). */
const GROUPS: { id: string; keys: { keys: string; actionKey: string }[] }[] = [
  {
    id: 'list',
    keys: [
      { keys: '↑ / ↓', actionKey: 'shortcuts.actions.move' },
      { keys: 'Enter', actionKey: 'shortcuts.actions.open' },
      { keys: 'Delete', actionKey: 'shortcuts.actions.delete' },
      { keys: 'Shift+Delete', actionKey: 'shortcuts.actions.purge' },
      { keys: 'Ctrl+A', actionKey: 'shortcuts.actions.selectAll' },
      { keys: 'U', actionKey: 'shortcuts.actions.unread' },
      { keys: 'E', actionKey: 'shortcuts.actions.done' },
      { keys: '!', actionKey: 'shortcuts.actions.junk' },
    ],
  },
  {
    id: 'message',
    keys: [
      { keys: 'R', actionKey: 'shortcuts.actions.reply' },
      { keys: 'Shift+R', actionKey: 'shortcuts.actions.replyAll' },
      { keys: 'F', actionKey: 'shortcuts.actions.forward' },
      { keys: '#', actionKey: 'shortcuts.actions.assign' },
      { keys: 'L', actionKey: 'shortcuts.actions.moveTo' },
    ],
  },
  {
    id: 'compose',
    keys: [
      { keys: 'C', actionKey: 'shortcuts.actions.compose' },
      { keys: 'Ctrl+Enter', actionKey: 'shortcuts.actions.send' },
    ],
  },
  {
    id: 'nav',
    keys: [
      { keys: '/', actionKey: 'shortcuts.actions.search' },
      { keys: 'Ctrl+K', actionKey: 'shortcuts.actions.palette' },
      { keys: 'Ctrl+Shift+P', actionKey: 'shortcuts.actions.switchPerson' },
      { keys: 'G I', actionKey: 'shortcuts.actions.gotoInbox' },
      { keys: '[', actionKey: 'shortcuts.actions.toggleFolders' },
      { keys: '?', actionKey: 'shortcuts.actions.help' },
    ],
  },
];

type Props = { onClose: () => void };

/** W15 Klávesové skratky — Phase-1 groups. */
export function ScreenW15({ onClose }: Props) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      GROUPS.map((g) => ({
        ...g,
        keys: g.keys.filter((row) => {
          if (!needle) return true;
          const action = t(row.actionKey).toLowerCase();
          return action.includes(needle) || row.keys.toLowerCase().includes(needle);
        }),
      })).filter((g) => g.keys.length > 0),
    [needle, t],
  );

  return (
    <Dialog
      title={t('shortcuts.title')}
      width={720}
      onClose={onClose}
      footer={
        <>
          <Link to="/settings/preferences" onClick={onClose} className="type-small text-brand-primary-700 hover:underline">
            {t('shortcuts.toSettings')}
          </Link>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.close')}
          </Button>
        </>
      }
    >
      <div data-testid="screen-w15" className="flex flex-col gap-4">
        <input
          data-autofocus
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('shortcuts.search')}
          aria-label={t('shortcuts.search')}
          className="type-body h-9 rounded-sm border border-border-default px-3"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          {filtered.map((g) => (
            <section key={g.id}>
              <h2 className="type-label mb-2 text-text-tertiary">{t(`shortcuts.groups.${g.id}`)}</h2>
              <ul className="flex flex-col gap-1.5">
                {g.keys.map((row) => (
                  <li key={row.keys} className="flex items-center justify-between gap-3">
                    <span className="type-small text-text-primary">{t(row.actionKey)}</span>
                    <kbd className="type-caption rounded-sm border border-border-default bg-bg-subtle px-1.5 py-0.5 text-text-secondary">
                      {row.keys}
                    </kbd>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
