import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  CircleCheck,
  Folder as FolderIcon,
  List,
  MessagesSquare,
  MousePointer2,
  RefreshCw,
  Search,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { ROUTES } from '../../app/routes';
import { Banner } from '../../components/Banner';
import { Menu, type MenuEntry } from '../../components/Menu';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { savePrefs } from '../prefs/prefsApi';
import { useTheme } from '../prefs/ThemeProvider';
import { FolderColumn } from './FolderColumn';
import { ListOptionsDialog } from './ListOptionsDialog';
import { MobileAppBar } from './MobileAppBar';
import { MobileFolderDrawer } from './MobileFolderDrawer';
import { SwipeRow } from './SwipeRow';
import {
  bulkMessages,
  fetchFolders,
  fetchMessages,
  findFolder,
  foldersKey,
  formatCount,
  messagesKey,
  refreshMailbox,
  type MessageFilter,
  type MessageListItem,
  type ThreadListItem,
} from './mailApi';
import { MessageRow, type RowItem } from './MessageRow';
import { ReadingPane } from './ReadingPane';
import { useFolderLabel } from './useFolderLabel';

export const FOLDERS_REFETCH_MS = 30_000;

function ToolbarButton({
  icon,
  label,
  onClick,
  busy,
  active,
}: {
  icon: ReactNode;
  label: string;
  onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  busy?: boolean;
  active?: boolean;
}) {
  const { t } = useTranslation();
  const disabled = !onClick || busy;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      title={onClick ? undefined : t('common.comingSoon')}
      className={`flex h-14 w-20 flex-col items-center justify-center gap-1 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
        onClick ? 'text-text-primary hover:bg-bg-subtle disabled:opacity-60' : 'cursor-not-allowed text-text-tertiary'
      } ${active ? 'bg-brand-primary-50 text-brand-primary-700' : ''}`}
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

const FILTERS: MessageFilter[] = ['all', 'unread', 'flagged', 'attachments'];

/** W2 E-mail — list + reading (Phase 1d). Remounts per folder so list UI state resets cleanly. */
export function ScreenW2() {
  const params = useParams();
  const mailboxRef = params.mailbox ?? 'default';
  const folderParam = params.folder ?? 'inbox';
  return <ScreenW2Body key={`${mailboxRef}/${folderParam}`} mailboxRef={mailboxRef} folderParam={folderParam} />;
}

function ScreenW2Body({ mailboxRef, folderParam }: { mailboxRef: string; folderParam: string }) {
  const { t } = useTranslation();
  const params = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const threadParam = params.threadId ?? null;
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const labelOf = useFolderLabel();
  const { classic, prefs } = useTheme();

  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<MessageFilter>('all');
  const [q, setQ] = useState('');
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pickedMessageId, setPickedMessageId] = useState<string | null>(null);
  const [selectMenu, setSelectMenu] = useState<{ x: number; y: number } | null>(null);
  const [folderDrawer, setFolderDrawer] = useState(false);
  const showOptions = search.get('dialog') === 'list-options';
  const mobile = useMediaQuery(MOBILE_QUERY);

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

  const view = folders.data;
  const folder = view ? findFolder(view.folders, folderParam) : undefined;
  const listPrefs = prefs?.list;
  const density = listPrefs?.density ?? 'compact';
  const mode = listPrefs?.mode ?? 'list';

  const folderId = folder?.id;
  const list = useQuery({
    queryKey: [...messagesKey(mailboxRef, folderId ?? '', page, filter), q],
    queryFn: () => {
      if (!folderId) throw new Error('folder missing');
      return fetchMessages(mailboxRef, folderId, {
        page,
        pageSize: listPrefs?.page_size,
        filter,
        q: q.trim() || undefined,
      });
    },
    enabled: Boolean(folderId),
    refetchInterval: FOLDERS_REFETCH_MS,
  });

  const fromUrl = useMemo(() => {
    if (!threadParam || !list.data) return { messageId: null as string | null, threadId: threadParam };
    if (list.data.mode === 'conversations') {
      const th = list.data.threads.find((row) => row.id === threadParam);
      return { messageId: th?.latest_message_id ?? null, threadId: th?.id ?? threadParam };
    }
    const msg = list.data.messages.find((row) => row.thread_id === threadParam || row.id === threadParam);
    return { messageId: msg?.id ?? null, threadId: msg?.thread_id ?? threadParam };
  }, [threadParam, list.data]);

  const activeMessageId = pickedMessageId ?? fromUrl.messageId;
  const activeThreadId = fromUrl.threadId;

  const saveList = useMutation({
    mutationFn: savePrefs,
    onSuccess: (data) => {
      queryClient.setQueryData(['mail', 'prefs'], data);
      setSearch({}, { replace: true });
      void list.refetch();
    },
  });

  const toggleConversations = useMutation({
    mutationFn: () =>
      savePrefs({
        list: {
          ...(listPrefs ?? {
            sort: 'date_received',
            sort_dir: 'desc',
            mode: 'list',
            density: 'compact',
            page_size: 50,
            show_ai_summary: true,
            mark_read: 'delay3',
            after_delete: 'next',
          }),
          mode: mode === 'conversations' ? 'list' : 'conversations',
        },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['mail', 'prefs'], data);
      void list.refetch();
    },
  });

  const bulk = useMutation({
    mutationFn: ({ action, ids }: { action: 'mark_seen' | 'delete' | 'archive' | 'done'; ids?: string[] }) =>
      bulkMessages(mailboxRef, { message_ids: ids ?? [...selectedIds], action }),
    onSuccess: (_r, { action }) => {
      toasts.success(t(`mail.toast.${action}`));
      setSelectedIds(new Set());
      setSelectMode(false);
      void list.refetch();
      void folders.refetch();
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });

  const openMessage = useCallback(
    (messageId: string, threadId: string | null, full = false) => {
      setPickedMessageId(messageId);
      const tid = threadId ?? messageId;
      const path = `/mail/${encodeURIComponent(mailboxRef)}/${encodeURIComponent(folderParam)}/${encodeURIComponent(tid)}`;
      if (full) navigate(path);
      else navigate(path, { replace: true });
    },
    [mailboxRef, folderParam, navigate],
  );

  const rows: RowItem[] = useMemo(() => {
    if (!list.data) return [];
    if (list.data.mode === 'conversations') {
      return list.data.threads.map((data: ThreadListItem) => ({ kind: 'thread' as const, data }));
    }
    return list.data.messages.map((data: MessageListItem) => ({ kind: 'message' as const, data }));
  }, [list.data]);

  const error = folders.error instanceof ApiError ? folders.error : null;
  if (error?.status === 404 && error.detail.code === 'mailbox_not_found') {
    return <Navigate to={ROUTES.W16b.path} replace />;
  }
  if (view && !folder) return <Navigate to={ROUTES.W16b.path} replace />;

  const serverDown =
    error?.detail.code === 'mail_server_unavailable' ||
    (refresh.error instanceof ApiError &&
      refresh.error.detail.code === 'mail_server_unavailable' &&
      refresh.submittedAt >= folders.dataUpdatedAt) ||
    view?.sync.state === 'error';
  const label = folder ? labelOf(folder) : '';
  const total = list.data?.total ?? folder?.total ?? 0;
  const pageSize = list.data?.page_size ?? listPrefs?.page_size ?? 50;
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  const selectMenuEntries: MenuEntry[] = [
    {
      kind: 'item',
      id: 'page',
      label: t('mail.select.page'),
      onSelect: () => {
        setSelectMode(true);
        const ids = rows
          .map((r) => (r.kind === 'message' ? r.data.id : r.data.latest_message_id))
          .filter((id): id is string => Boolean(id));
        setSelectedIds(new Set(ids));
        setSelectMenu(null);
      },
    },
    {
      kind: 'item',
      id: 'unread',
      label: t('mail.select.unread'),
      onSelect: () => {
        setSelectMode(true);
        const ids = rows
          .filter((r) => (r.kind === 'message' ? !r.data.seen : r.data.unread_count > 0))
          .map((r) => (r.kind === 'message' ? r.data.id : r.data.latest_message_id))
          .filter((id): id is string => Boolean(id));
        setSelectedIds(new Set(ids));
        setSelectMenu(null);
      },
    },
    {
      kind: 'item',
      id: 'none',
      label: t('mail.select.none'),
      onSelect: () => {
        setSelectedIds(new Set());
        setSelectMode(false);
        setSelectMenu(null);
      },
    },
  ];

  const mobileThread = mobile && Boolean(threadParam);

  return (
    <AppShell section="mail" mailbox={mailboxRef} unread={view?.mailbox.unread ?? 0} hideBottomNav={mobileThread}>
      <h1 className="sr-only">{label || t('rail.mail')}</h1>
      {mobile ? null : view ? (
        <FolderColumn
          mailboxRef={mailboxRef}
          view={view}
          activeRef={folder ? (folder.special_use ?? folder.id) : folderParam}
          readOnly={me.data?.read_only ?? true}
        />
      ) : (
        <FolderSkeleton />
      )}

      {mobile && view ? (
        <MobileFolderDrawer
          open={folderDrawer}
          onClose={() => setFolderDrawer(false)}
          mailboxRef={mailboxRef}
          view={view}
          activeRef={folder ? (folder.special_use ?? folder.id) : folderParam}
          readOnly={me.data?.read_only ?? true}
        />
      ) : null}

      {mobileThread ? (
        <div className="flex min-h-0 flex-1 flex-col" data-testid="mobile-thread">
          <ReadingPane
            mailbox={mailboxRef}
            folderRef={folderParam}
            messageId={activeMessageId}
            threadId={activeThreadId}
            onCleared={() => {
              setPickedMessageId(null);
              navigate(`/mail/${encodeURIComponent(mailboxRef)}/${encodeURIComponent(folderParam)}`);
              void list.refetch();
            }}
          />
        </div>
      ) : null}

      <section
        aria-label={label}
        className={`flex h-full w-full shrink-0 flex-col border-r border-border-default bg-bg-canvas sm:w-[360px] ${
          mobileThread ? 'hidden' : ''
        }`}
      >
        {mobile ? (
          <MobileAppBar
            title={label || t('rail.mail')}
            onOpenFolders={() => setFolderDrawer(true)}
            onSearch={() => navigate('/search')}
          />
        ) : null}
        {selectedIds.size > 0 ? (
          <div className="flex h-14 shrink-0 items-center gap-1 border-b border-border-default px-2">
            <span className="type-small mr-2 text-text-primary">
              {t('mail.bulk.selected', { count: selectedIds.size })}
            </span>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'mark_seen' })}
            >
              {t('mail.bulk.markRead')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'done' })}
            >
              <CircleCheck size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.toolbar.done')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'archive' })}
            >
              <Archive size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.toolbar.archive')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 text-danger-600 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'delete' })}
            >
              <Trash2 size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.toolbar.delete')}
            </button>
            <button
              type="button"
              className="ml-auto rounded-sm p-1 text-text-secondary hover:bg-bg-subtle"
              aria-label={t('mail.bulk.clear')}
              onClick={() => {
                setSelectedIds(new Set());
                setSelectMode(false);
              }}
            >
              <X size={16} />
            </button>
            <span className="sr-only">{t('mail.bulk.assignSoon')}</span>
            <UserPlus size={14} className="text-text-tertiary" aria-hidden="true" />
          </div>
        ) : mobile ? null : (
          <div className="flex h-14 shrink-0 items-center justify-center gap-1 px-2">
            <ToolbarButton
              icon={<MousePointer2 size={18} />}
              label={t('mail.toolbar.select')}
              onClick={(event) => {
                const r = event.currentTarget.getBoundingClientRect();
                setSelectMenu({ x: r.left, y: r.bottom + 4 });
              }}
            />
            <ToolbarButton
              icon={<MessagesSquare size={18} />}
              label={t('mail.toolbar.threads')}
              active={mode === 'conversations'}
              onClick={() => toggleConversations.mutate()}
              busy={toggleConversations.isPending}
            />
            <ToolbarButton
              icon={<List size={18} />}
              label={t('mail.toolbar.options')}
              onClick={() => setSearch({ dialog: 'list-options' })}
            />
            <ToolbarButton
              icon={<RefreshCw size={18} />}
              label={t('mail.toolbar.refresh')}
              onClick={() => refresh.mutate()}
              busy={refresh.isPending}
            />
          </div>
        )}

        <div className="flex shrink-0 flex-col gap-2 border-b border-border-default px-2 pb-2">
          <label className="relative block">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-2.5 text-text-tertiary"
              aria-hidden="true"
            />
            <input
              type="search"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  const needle = q.trim();
                  if (needle) {
                    const qs = new URLSearchParams({
                      q: needle,
                      scope: 'current',
                      field: 'full',
                      mailbox: mailboxRef,
                    });
                    if (folder?.id) qs.set('folder_id', folder.id);
                    navigate(`/search?${qs.toString()}`);
                    return;
                  }
                  setPage(1);
                  void list.refetch();
                }
              }}
              placeholder={t('mail.searchPlaceholder')}
              className="type-small h-9 w-full rounded-sm border border-border-default bg-bg-canvas pl-8 pr-3 text-text-primary placeholder:text-text-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-brand-primary-500"
            />
          </label>
          {classic ? null : (
            <div className="flex flex-wrap gap-1.5 px-1">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => {
                    setFilter(f);
                    setPage(1);
                  }}
                  className={`type-caption rounded-full px-2.5 py-1 ${
                    filter === f
                      ? 'bg-brand-primary-600 text-text-on-primary'
                      : 'bg-bg-muted text-text-secondary hover:bg-bg-subtle'
                  }`}
                >
                  {t(`mail.filter.${f}`)}
                </button>
              ))}
            </div>
          )}
        </div>

        {serverDown && !refresh.isPending ? (
          <div className="px-2 pb-2 pt-2">
            <Banner
              kind="danger"
              message={t('mail.loadFailed')}
              action={{ label: t('system.retry'), onClick: () => refresh.mutate(), disabled: refresh.isPending }}
            />
          </div>
        ) : null}

        <div role="listbox" aria-label={label} className="min-h-0 flex-1 overflow-y-auto">
          {folder && folder.total === 0 ? (
            folder.special_use === 'inbox' ? (
              <EmptyState icon={<CircleCheck size={20} />} title={t('mail.allDone')} text={t('mail.allDoneText')} />
            ) : (
              <EmptyState
                icon={<FolderIcon size={20} />}
                title={t('mail.empty')}
                text={t('mail.emptyText', { name: label })}
              />
            )
          ) : list.isLoading ? (
            <div aria-busy="true" className="flex flex-col gap-0">
              {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
                <div key={i} className="h-[52px] border-b border-border-default px-3 py-2">
                  <div className="mb-2 h-3 w-2/3 rounded-xs bg-bg-muted" />
                  <div className="h-3 w-1/2 rounded-xs bg-bg-muted" />
                </div>
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState icon={<FolderIcon size={20} />} title={t('mail.empty')} text={t('mail.emptyFilter')} />
          ) : (
            rows.map((item) => {
              const id = item.kind === 'message' ? item.data.id : (item.data.latest_message_id ?? item.data.id);
              const tid = item.kind === 'message' ? item.data.thread_id : item.data.id;
              const selected =
                activeMessageId === id ||
                (activeThreadId !== null &&
                  (item.kind === 'thread' ? item.data.id === activeThreadId : item.data.thread_id === activeThreadId));
              const row = (
                <MessageRow
                  item={item}
                  selected={selected}
                  checked={selectedIds.has(id)}
                  showCheckbox={selectMode || selectedIds.size > 0}
                  density={density}
                  classic={classic}
                  onSelect={() => openMessage(id, tid, mobile)}
                  onCheck={(checked) => {
                    setSelectMode(true);
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      if (checked) next.add(id);
                      else next.delete(id);
                      return next;
                    });
                  }}
                  onLongPress={
                    mobile
                      ? () => {
                          setSelectMode(true);
                          setSelectedIds((prev) => new Set(prev).add(id));
                        }
                      : undefined
                  }
                />
              );
              const key = item.kind === 'message' ? item.data.id : item.data.id;
              if (!mobile) return <div key={key}>{row}</div>;
              return (
                <SwipeRow key={key} onDone={() => bulk.mutate({ action: 'done', ids: [id] })}>
                  {row}
                </SwipeRow>
              );
            })
          )}
        </div>

        <div className="type-caption flex h-10 shrink-0 items-center justify-center gap-2 border-t border-border-default text-text-secondary">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-1 disabled:opacity-40"
            aria-label={t('mail.pager.prev')}
          >
            ‹
          </button>
          <span>
            {t('mail.pager.range', { from: formatCount(from), to: formatCount(to), total: formatCount(total) })}
          </span>
          <input
            type="number"
            min={1}
            max={pages}
            value={page}
            onChange={(event) => setPage(Math.min(pages, Math.max(1, Number(event.target.value) || 1)))}
            className="h-6 w-10 rounded-xs border border-border-default bg-bg-canvas text-center"
            aria-label={t('mail.pager.page')}
          />
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            className="px-1 disabled:opacity-40"
            aria-label={t('mail.pager.next')}
          >
            ›
          </button>
        </div>
      </section>

      {mobile || mobileThread ? null : (
        <ReadingPane
          mailbox={mailboxRef}
          folderRef={folderParam}
          messageId={activeMessageId}
          threadId={activeThreadId}
          onCleared={() => {
            setPickedMessageId(null);
            navigate(`/mail/${encodeURIComponent(mailboxRef)}/${encodeURIComponent(folderParam)}`, { replace: true });
            void list.refetch();
          }}
        />
      )}

      {mobile && !mobileThread ? <LinkFab mailbox={mailboxRef} /> : null}

      {selectMenu ? (
        <Menu
          label={t('mail.toolbar.select')}
          entries={selectMenuEntries}
          at={selectMenu}
          width={220}
          onClose={() => setSelectMenu(null)}
        />
      ) : null}

      {showOptions && listPrefs ? (
        <ListOptionsDialog
          initial={listPrefs}
          busy={saveList.isPending}
          onClose={() => setSearch({}, { replace: true })}
          onSave={(next) => saveList.mutate({ list: next })}
        />
      ) : null}
    </AppShell>
  );
}

function FolderSkeleton() {
  return (
    <div
      aria-busy="true"
      className="flex h-full w-full shrink-0 flex-col gap-2 border-r border-border-default bg-bg-subtle px-4 pt-5 sm:w-[232px]"
    >
      <div className="mb-4 h-4 w-36 rounded-xs bg-bg-muted" />
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="h-5 rounded-xs bg-bg-muted" style={{ width: `${70 - (i % 3) * 12}%` }} />
      ))}
    </div>
  );
}

function LinkFab({ mailbox }: { mailbox: string }) {
  const { t } = useTranslation();
  return (
    <a
      href={`/compose?mailbox=${encodeURIComponent(mailbox)}`}
      data-testid="compose-fab"
      aria-label={t('rail.compose')}
      className="fixed bottom-20 right-4 z-30 flex h-12 items-center gap-2 rounded-md bg-brand-primary-600 px-4 text-text-on-primary shadow-e3 sm:hidden"
      style={{ marginBottom: 'env(safe-area-inset-bottom)' }}
    >
      <SquarePenIcon />
      <span className="type-label">{t('mobile.create')}</span>
    </a>
  );
}

function SquarePenIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}
