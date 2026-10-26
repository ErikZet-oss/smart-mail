import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleCheck, Folder as FolderIcon, List, MessagesSquare, MousePointer2, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useParams } from 'react-router-dom';

import { ROUTES } from '../../app/routes';
import { Banner } from '../../components/Banner';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { fetchMe } from '../auth/authApi';
import { FolderColumn } from './FolderColumn';
import { useFolderLabel } from './useFolderLabel';
import { fetchFolders, findFolder, foldersKey, formatCount, refreshMailbox, type Folder } from './mailApi';

/** The column re-reads the local DB this often; the worker keeps it in sync with IMAP (IDLE + 2-min poll). */
export const FOLDERS_REFETCH_MS = 30_000;

function ToolbarButton({
  icon,
  label,
  onClick,
  busy,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  busy?: boolean;
}) {
  const { t } = useTranslation();
  const disabled = !onClick || busy;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={onClick ? undefined : t('common.comingSoon')}
      className={`flex h-14 w-20 flex-col items-center justify-center gap-1 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
        onClick ? 'text-text-primary hover:bg-bg-subtle disabled:opacity-60' : 'cursor-not-allowed text-text-tertiary'
      }`}
    >
      <span aria-hidden="true" className={busy ? 'animate-spin' : ''}>
        {icon}
      </span>
      <span className="type-micro w-[76px] truncate">{label}</span>
    </button>
  );
}

function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 pt-16 text-center">
      <span
        aria-hidden="true"
        className="flex size-10 items-center justify-center rounded-full bg-bg-muted text-text-secondary"
      >
        {icon}
      </span>
      <p className="type-heading text-text-primary">{title}</p>
      <p className="type-small text-text-secondary">{text}</p>
    </div>
  );
}

function ListColumn({
  folder,
  label,
  failed,
  onRefresh,
  refreshing,
}: {
  folder: Folder | undefined;
  label: string;
  failed: boolean;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const { t } = useTranslation();
  let body: ReactNode = null;
  if (folder && folder.total === 0) {
    body =
      folder.special_use === 'inbox' ? (
        <EmptyState icon={<CircleCheck size={20} />} title={t('mail.allDone')} text={t('mail.allDoneText')} />
      ) : (
        <EmptyState
          icon={<FolderIcon size={20} />}
          title={t('mail.empty')}
          text={t('mail.emptyText', { name: label })}
        />
      );
  } else if (folder) {
    body = (
      <p className="type-small px-6 pt-16 text-center text-text-secondary">
        {t('mail.listLater', { count: folder.total, total: formatCount(folder.total) })}
      </p>
    );
  }
  return (
    <section
      aria-label={label}
      className="hidden h-full w-[360px] shrink-0 flex-col border-r border-border-default bg-bg-canvas sm:flex"
    >
      <div className="flex h-14 shrink-0 items-center justify-center gap-1 px-2">
        <ToolbarButton icon={<MousePointer2 size={18} />} label={t('mail.toolbar.select')} />
        <ToolbarButton icon={<MessagesSquare size={18} />} label={t('mail.toolbar.threads')} />
        <ToolbarButton icon={<List size={18} />} label={t('mail.toolbar.options')} />
        <ToolbarButton
          icon={<RefreshCw size={18} />}
          label={t('mail.toolbar.refresh')}
          onClick={onRefresh}
          busy={refreshing}
        />
      </div>
      {failed ? (
        <div className="px-2 pb-2">
          <Banner
            kind="danger"
            message={t('mail.loadFailed')}
            action={{ label: t('system.retry'), onClick: onRefresh, disabled: refreshing }}
          />
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto">{body}</div>
      <div className="type-caption flex h-10 shrink-0 items-center justify-center border-t border-border-default text-text-secondary">
        {t('mail.count', { total: formatCount(folder?.total ?? 0) })}
      </div>
    </section>
  );
}

function ReadingPane() {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t('mail.readingPane')}
      className="hidden min-w-0 flex-1 flex-col items-center justify-center gap-4 bg-bg-canvas lg:flex"
    >
      <img src="/logo-smart.svg" alt="" width={196} className="h-auto opacity-20 grayscale" />
      <p className="type-heading text-text-secondary">{t('mail.selectMessage')}</p>
    </section>
  );
}

function FolderSkeleton() {
  return (
    <div
      aria-busy="true"
      className="flex h-full w-full shrink-0 flex-col gap-2 border-r sm:w-[232px] border-border-default bg-bg-subtle px-4 pt-5"
    >
      <div className="mb-4 h-4 w-36 rounded-xs bg-bg-muted" />
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="h-5 rounded-xs bg-bg-muted" style={{ width: `${70 - (i % 3) * 12}%` }} />
      ))}
    </div>
  );
}

/** W2 E-mail — `/mail/:mailbox/:folder` (1c: shell, folder column, list header; list + reading come in 1d). */
export function ScreenW2() {
  const { t } = useTranslation();
  const params = useParams();
  const mailboxRef = params.mailbox ?? 'default';
  const folderParam = params.folder ?? 'inbox';
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const labelOf = useFolderLabel();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const folders = useQuery({
    queryKey: foldersKey(mailboxRef),
    queryFn: () => fetchFolders(mailboxRef),
    refetchInterval: FOLDERS_REFETCH_MS,
  });
  const refresh = useMutation({
    mutationFn: () => refreshMailbox(mailboxRef),
    onSuccess: (view) => queryClient.setQueryData(foldersKey(mailboxRef), view),
    onError: (error) => {
      if (!(error instanceof ApiError) || error.detail.code !== 'mail_server_unavailable') {
        toasts.error(t('folders.errors.generic'));
      }
    },
  });

  const error = folders.error instanceof ApiError ? folders.error : null;
  // only a real "mailbox missing" 404 opens W16b — a concurrent 401/503 on /me must win the redirect (W1c / W17)
  if (error?.status === 404 && error.detail.code === 'mailbox_not_found') {
    return <Navigate to={ROUTES.W16b.path} replace />;
  }

  const view = folders.data;
  const folder = view ? findFolder(view.folders, folderParam) : undefined;
  if (view && !folder) return <Navigate to={ROUTES.W16b.path} replace />;

  const serverDown =
    error?.detail.code === 'mail_server_unavailable' ||
    (refresh.error instanceof ApiError &&
      refresh.error.detail.code === 'mail_server_unavailable' &&
      refresh.submittedAt >= folders.dataUpdatedAt) ||
    view?.sync.state === 'error';
  const label = folder ? labelOf(folder) : '';

  return (
    <AppShell section="mail" mailbox={mailboxRef} unread={view?.mailbox.unread ?? 0}>
      <h1 className="sr-only">{label || t('rail.mail')}</h1>
      {view ? (
        <FolderColumn
          mailboxRef={mailboxRef}
          view={view}
          activeRef={folder ? (folder.special_use ?? folder.id) : folderParam}
          readOnly={me.data?.read_only ?? true}
        />
      ) : (
        <FolderSkeleton />
      )}
      <ListColumn
        folder={folder}
        label={label}
        failed={serverDown && !refresh.isPending}
        onRefresh={() => refresh.mutate()}
        refreshing={refresh.isPending}
      />
      <ReadingPane />
    </AppShell>
  );
}
