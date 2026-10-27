import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bell, RefreshCw, UserPlus, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import {
  dismissNotifications,
  fetchNotifications,
  NOTIFS_KEY,
  type NotificationItem,
} from './notificationsApi';

type Tab = 'all' | 'open';

function dayGroup(iso: string, t: (k: string) => string): string {
  const d = new Date(iso);
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startYday = new Date(startToday);
  startYday.setDate(startYday.getDate() - 1);
  if (d >= startToday) return t('notifs.group.today');
  if (d >= startYday) return t('notifs.group.yesterday');
  return t('notifs.group.older');
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('sk-SK', { hour: '2-digit', minute: '2-digit' });
}

function KindIcon({ kind }: { kind: NotificationItem['kind'] }) {
  if (kind === 'sync_failed') return <RefreshCw size={18} className="text-danger-600" aria-hidden="true" />;
  return <UserPlus size={18} className="text-brand-primary-600" aria-hidden="true" />;
}

type Props = { onClose: () => void };

/** W14 desktop panel / M16 full-screen — Phase-1 kinds only (sync + assignment). */
export function NotificationsPanel({ onClose }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('all');
  const list = useQuery({ queryKey: NOTIFS_KEY, queryFn: fetchNotifications });
  const dismiss = useMutation({
    mutationFn: dismissNotifications,
    onSuccess: () => void qc.invalidateQueries({ queryKey: NOTIFS_KEY }),
  });

  const items = useMemo(() => {
    const all = list.data?.items ?? [];
    return tab === 'open' ? all.filter((i) => i.unread) : all;
  }, [list.data, tab]);

  const groups = useMemo(() => {
    const map = new Map<string, NotificationItem[]>();
    for (const item of items) {
      const g = dayGroup(item.created_at, t);
      const arr = map.get(g) ?? [];
      arr.push(item);
      map.set(g, arr);
    }
    return [...map.entries()];
  }, [items, t]);

  const body = (
    <>
      <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-2">
        {mobile ? (
          <button
            type="button"
            onClick={onClose}
            aria-label={t('system.back')}
            className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
          >
            <ArrowLeft size={22} />
          </button>
        ) : (
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="flex size-9 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-subtle"
          >
            <X size={18} />
          </button>
        )}
        <h1 className="type-heading min-w-0 flex-1 truncate text-text-primary">{t('notifs.title')}</h1>
        <button
          type="button"
          className="type-caption shrink-0 px-2 py-1 text-brand-primary-700 hover:underline disabled:opacity-50"
          disabled={!list.data?.unread_count || dismiss.isPending}
          onClick={() => dismiss.mutate({ all: true })}
        >
          {t('notifs.markAll')}
        </button>
      </header>
      <div className="flex gap-2 border-b border-border-default px-3 py-2">
        {(['all', 'open'] as const).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`type-caption rounded-full px-2.5 py-1 ${
              tab === id ? 'bg-brand-primary-600 text-text-on-primary' : 'bg-bg-muted text-text-secondary'
            }`}
          >
            {t(`notifs.tab.${id}`)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {list.isLoading ? (
          <p className="type-body p-6 text-text-tertiary" aria-busy="true">
            …
          </p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-16 text-center" data-testid="notifs-empty">
            <Bell size={28} className="text-text-tertiary" aria-hidden="true" />
            <p className="type-heading text-text-primary">{t('notifs.emptyTitle')}</p>
            <p className="type-small text-text-secondary">{t('notifs.emptyHint')}</p>
          </div>
        ) : (
          groups.map(([label, rows]) => (
            <section key={label}>
              <h2 className="type-caption bg-bg-subtle px-4 py-1.5 text-text-tertiary">{label}</h2>
              <ul>
                {rows.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className="flex w-full items-start gap-3 border-b border-border-subtle px-4 py-3 text-left hover:bg-bg-subtle"
                      onClick={() => {
                        if (item.unread) dismiss.mutate({ ids: [item.id] });
                        onClose();
                        if (item.href) navigate(item.href);
                      }}
                    >
                      <KindIcon kind={item.kind} />
                      <span className="min-w-0 flex-1">
                        <span className="type-small flex items-center gap-2 font-medium text-text-primary">
                          {item.title}
                          {item.unread ? (
                            <span className="size-2 shrink-0 rounded-full bg-brand-primary-600" aria-hidden="true" />
                          ) : null}
                        </span>
                        <span className="type-caption line-clamp-2 text-text-secondary">{item.body}</span>
                      </span>
                      <span className="type-caption shrink-0 text-text-tertiary">{timeLabel(item.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
      <footer className="border-t border-border-default px-4 py-2">
        <p className="type-caption text-text-tertiary">{t('notifs.settingsLater')}</p>
        <Link to="/settings" onClick={onClose} className="type-caption text-brand-primary-700 hover:underline">
          {t('notifs.toSettings')}
        </Link>
      </footer>
    </>
  );

  if (mobile) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="screen-m16">
        {body}
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/20"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t('notifs.title')}
        data-testid="screen-w14"
        className="flex h-full w-[380px] max-w-full flex-col border-l border-border-default bg-bg-canvas shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {body}
      </aside>
    </div>
  );
}
