import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  CircleCheck,
  Folder as FolderIcon,
  FolderInput,
  List,
  MessagesSquare,
  MousePointer2,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { ROUTES } from '../../app/routes';
import { Banner } from '../../components/Banner';
import { ConfirmDialog } from '../../components/Dialog';
import { Menu, type MenuEntry } from '../../components/Menu';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { savePrefs } from '../prefs/prefsApi';
import { registerMailShortcuts, type MailShortcutHandlers } from '../system/shortcuts';
import { useTheme } from '../prefs/ThemeProvider';
import { FolderColumn } from './FolderColumn';
import { ListOptionsDialog } from './ListOptionsDialog';
import { MobileAppBar } from './MobileAppBar';
import { MobileFolderDrawer } from './MobileFolderDrawer';
import { SwipeRow } from './SwipeRow';
import {
  aiCategoriesKey,
  bulkMessages,
  fetchAiCategories,
  fetchCategoryMessages,
  fetchFolders,
  fetchMessages,
  findFolder,
  folderRef as folderSegment,
  foldersKey,
  formatCount,
  markSeenLocally,
  messagesKey,
  refreshMailbox,
  type Folder,
  type MessageFilter,
  type MessageListItem,
  type ThreadListItem,
} from './mailApi';
import { FolderPicker } from './FolderPicker';
import { applyActionLocally, REMOVING_ACTIONS } from './optimistic';
import { CATEGORY_COLOR_TOKEN, categoryDotClass } from './categoryStyles';
import { MessageRow, type RowItem } from './MessageRow';
import { ReadingPane } from './ReadingPane';
import { firstSyncProgress } from './syncProgress';
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

/** W2 E-mail — list + reading (Phase 1d). W2f when `category` is set. Remounts per folder/view. */
type ListAction = 'mark_seen' | 'mark_unseen' | 'delete' | 'purge' | 'junk' | 'archive' | 'move' | 'done';

export function ScreenW2() {
  const params = useParams();
  const mailboxRef = params.mailbox ?? 'default';
  const category = params.category ?? null;
  const folderParam = params.folder ?? 'inbox';
  return (
    <ScreenW2Body
      key={`${mailboxRef}/${category ?? folderParam}`}
      mailboxRef={mailboxRef}
      folderParam={folderParam}
      category={category}
    />
  );
}

function ScreenW2Body({
  mailboxRef,
  folderParam,
  category,
}: {
  mailboxRef: string;
  folderParam: string;
  category: string | null;
}) {
  const { t } = useTranslation();
  const params = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const threadParam = params.threadId ?? null;
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const labelOf = useFolderLabel();
  const { classic, prefs } = useTheme();
  const aiView = Boolean(category) && !classic;

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
  const folder = view?.folders ? findFolder(view.folders, folderParam) : undefined;
  const listPrefs = prefs?.list;
  const density = listPrefs?.density ?? 'compact';
  const mode = listPrefs?.mode ?? 'list';

  const folderId = folder?.id;
  const aiOn = Boolean(view?.mailbox.ai_available ?? view?.mailbox.ai_enabled);
  const aiCats = useQuery({
    queryKey: aiCategoriesKey(mailboxRef),
    queryFn: () => fetchAiCategories(mailboxRef),
    enabled: !classic && aiOn,
    refetchInterval: FOLDERS_REFETCH_MS,
  });
  const list = useQuery({
    queryKey: aiView
      ? ['mail', 'ai-view', mailboxRef, category, page, filter, q]
      : [...messagesKey(mailboxRef, folderId ?? '', page, filter), q],
    queryFn: async () => {
      if (aiView && category) {
        const data = await fetchCategoryMessages(mailboxRef, category, {
          page,
          pageSize: listPrefs?.page_size,
          filter,
          q: q.trim() || undefined,
        });
        return {
          mode: 'list' as const,
          total: data.total,
          page: data.page,
          page_size: data.page_size,
          messages: data.messages,
          threads: [] as ThreadListItem[],
          prefs: listPrefs ?? {
            sort: 'date_received' as const,
            sort_dir: 'desc' as const,
            mode: 'list' as const,
            density: 'compact' as const,
            page_size: 50,
            show_ai_summary: true,
            mark_read: 'delay3' as const,
            after_delete: 'next' as const,
          },
          categoryMeta: data.category,
        };
      }
      if (!folderId) throw new Error('folder missing');
      return fetchMessages(mailboxRef, folderId, {
        page,
        pageSize: listPrefs?.page_size,
        filter,
        q: q.trim() || undefined,
      });
    },
    enabled: aiView ? Boolean(category) : Boolean(folderId),
    refetchInterval: FOLDERS_REFETCH_MS,
  });

  const fromUrl = useMemo(() => {
    if (!threadParam || !list.data) return { messageId: null as string | null, threadId: threadParam };
    if (list.data.mode === 'conversations') {
      const th = list.data.threads.find((row) => row.id === threadParam);
      return { messageId: th?.latest_message_id ?? null, threadId: th?.id ?? threadParam };
    }
    const msg = list.data.messages.find((row) => row.thread_id === threadParam || row.id === threadParam);
    // Opened from AI triedenie (mobile / full view): the message may not be on this folder page — `?m=` names it.
    return { messageId: msg?.id ?? search.get('m'), threadId: msg?.thread_id ?? threadParam };
  }, [threadParam, list.data, search]);

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

  const listBasePath =
    aiView && category
      ? `/mail/${encodeURIComponent(mailboxRef)}/view/${encodeURIComponent(category)}`
      : `/mail/${encodeURIComponent(mailboxRef)}/${encodeURIComponent(folderParam)}`;

  const bulk = useMutation({
    mutationFn: ({ action, ids, dest }: { action: ListAction; ids: string[]; dest?: Folder }) =>
      bulkMessages(mailboxRef, { message_ids: ids, action, dest_folder_id: dest?.id }),
    // #89: the rows go away at once; the server answer only confirms (or rolls back).
    onMutate: async ({ action, ids }) => {
      await queryClient.cancelQueries({ queryKey: ['mail', 'messages', mailboxRef] });
      const rollback = applyActionLocally(queryClient, mailboxRef, ids, action);
      setSelectedIds(new Set());
      setSelectMode(false);
      if (REMOVING_ACTIONS.has(action) && activeMessageId && ids.includes(activeMessageId)) {
        setPickedMessageId(null);
        navigate(listBasePath, { replace: true });
      }
      return { rollback };
    },
    onSuccess: (_r, { action, dest }) =>
      toasts.success(dest ? t('mail.moveTo.moved', { folder: labelOf(dest) }) : t(`mail.toast.${action}`)),
    onError: (_e, _v, context) => {
      context?.rollback();
      toasts.error(t('mail.errors.generic'));
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['mail', 'messages', mailboxRef] });
      void queryClient.invalidateQueries({ queryKey: foldersKey(mailboxRef) });
    },
  });

  const canMarkSeen = Boolean(me.data?.person && !me.data.read_only);
  const openMessage = useCallback(
    (messageId: string, threadId: string | null, full = false) => {
      setPickedMessageId(messageId);
      const tid = threadId ?? messageId;
      // Thread deep-link stays on folder route (W2c); AI view keeps selection in-pane.
      if (aiView && !full) {
        navigate(listBasePath, { replace: true });
        return;
      }
      // AI triedenie lists messages of every folder: open the message in its own folder (Sieve files e.g. invoices
      // into Faktúry), never a guessed Doručená pošta — the pilot got a blank screen on mobile.
      const sourceFolder = aiView
        ? view?.folders.find((f) => f.id === list.data?.messages.find((m) => m.id === messageId)?.folder_id)
        : undefined;
      const folderForThread = aiView ? (sourceFolder ? folderSegment(sourceFolder) : 'inbox') : folderParam;
      const query = aiView ? `?m=${encodeURIComponent(messageId)}` : '';
      const path = `/mail/${encodeURIComponent(mailboxRef)}/${encodeURIComponent(folderForThread)}/${encodeURIComponent(tid)}${query}`;
      if (full) navigate(path);
      else navigate(path, { replace: true });
    },
    [mailboxRef, folderParam, navigate, aiView, listBasePath, list.data?.messages, view?.folders],
  );

  // The reading pane GET marks the message read on the server; show it in the list now (only when we may act).
  const openAndMarkSeen = (messageId: string, threadId: string | null, full = false) => {
    if (canMarkSeen) markSeenLocally(queryClient, mailboxRef, messageId, threadId, aiView ? null : (folderId ?? null));
    openMessage(messageId, threadId, full);
  };

  const rows: RowItem[] = useMemo(() => {
    if (!list.data) return [];
    if (list.data.mode === 'conversations') {
      return list.data.threads.map((data: ThreadListItem) => ({ kind: 'thread' as const, data }));
    }
    return list.data.messages.map((data: MessageListItem) => ({ kind: 'message' as const, data }));
  }, [list.data]);

  // UX_SPEC §6 list keys (#93): the central listener in useGlobalShortcuts calls these.
  const [purgeIds, setPurgeIds] = useState<string[] | null>(null);
  // Presunúť do… for the selection / open message (#96): bulk bar button and `L`.
  const [movePicker, setMovePicker] = useState<{ ids: string[]; at: { x: number; y: number } } | null>(null);
  const shortcutHandlers = useRef<MailShortcutHandlers>({ readOnly: true });
  const rowRefs = rows.map((r) =>
    r.kind === 'message'
      ? { id: r.data.id, tid: r.data.thread_id }
      : { id: r.data.latest_message_id ?? r.data.id, tid: r.data.id },
  );
  const targets = selectedIds.size > 0 ? [...selectedIds] : activeMessageId ? [activeMessageId] : [];
  const step = (delta: number) => {
    if (rowRefs.length === 0) return;
    const at = rowRefs.findIndex((r) => r.id === activeMessageId);
    const next = at < 0 ? (delta > 0 ? 0 : rowRefs.length - 1) : Math.min(rowRefs.length - 1, Math.max(0, at + delta));
    const row = rowRefs[next];
    if (!row || next === at) return;
    openAndMarkSeen(row.id, row.tid, false);
    window.requestAnimationFrame(() =>
      document.querySelector(`[data-message-id="${CSS.escape(row.id)}"]`)?.scrollIntoView({ block: 'nearest' }),
    );
  };
  const compose = (mode: 'reply' | 'reply_all' | 'forward') => {
    if (!activeMessageId) return;
    navigate(
      `/compose?mode=${mode}&mailbox=${encodeURIComponent(mailboxRef)}&m=${encodeURIComponent(activeMessageId)}`,
    );
  };
  const act = (action: ListAction) => {
    if (targets.length > 0) bulk.mutate({ action, ids: targets });
  };
  const handlers: MailShortcutHandlers = {
    readOnly: !canMarkSeen,
    up: () => step(-1),
    down: () => step(1),
    open: () => {
      const row = rowRefs.find((r) => r.id === activeMessageId) ?? rowRefs[0];
      if (row) openAndMarkSeen(row.id, row.tid, true);
    },
    delete: () => act('delete'),
    purge: () => {
      if (targets.length > 0) setPurgeIds(targets);
    },
    moveTo: () => {
      if (targets.length > 0) setMovePicker({ ids: targets, at: { x: window.innerWidth / 2 - 130, y: 120 } });
    },
    selectAll: () => {
      setSelectMode(true);
      setSelectedIds(new Set(rowRefs.map((r) => r.id)));
    },
    unread: () => act('mark_unseen'),
    junk: () => act('junk'),
    reply: () => compose('reply'),
    replyAll: () => compose('reply_all'),
    forward: () => compose('forward'),
  };
  useEffect(() => {
    shortcutHandlers.current = handlers;
  });
  useEffect(() => registerMailShortcuts(() => shortcutHandlers.current), []);

  const colorByCategory = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of aiCats.data?.categories ?? []) map.set(c.id, c.color_token);
    return map;
  }, [aiCats.data?.categories]);

  const categoryMeta = aiCats.data?.categories.find((c) => c.id === category) ?? null;
  const showAiSummary = Boolean(listPrefs?.show_ai_summary) && !classic;

  const error = folders.error instanceof ApiError ? folders.error : null;
  if (error?.status === 404 && error.detail.code === 'mailbox_not_found') {
    return <Navigate to={ROUTES.W16b.path} replace />;
  }
  if (view && !folder && !aiView) return <Navigate to={ROUTES.W16b.path} replace />;
  if ((classic || (view && !aiOn)) && category) {
    return <Navigate to={`/mail/${encodeURIComponent(mailboxRef)}/inbox`} replace />;
  }

  // unexpected failure (exception class from the worker, #41) vs. an unreachable mail server (its own codes)
  const syncFailed = view?.sync.state === 'error' && (view.sync.error ?? '').startsWith('unexpected:');
  const serverDown =
    error?.detail.code === 'mail_server_unavailable' ||
    (refresh.error instanceof ApiError &&
      refresh.error.detail.code === 'mail_server_unavailable' &&
      refresh.submittedAt >= folders.dataUpdatedAt) ||
    view?.sync.state === 'error';
  const syncProgress = firstSyncProgress(view?.sync);
  const label = aiView
    ? (categoryMeta?.label_sk ?? t(`ai.categories.${category}.label`, { defaultValue: category ?? '' }))
    : folder
      ? labelOf(folder)
      : '';
  const total = list.data?.total ?? (aiView ? 0 : (folder?.total ?? 0));
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
          classic={classic}
          aiCategories={aiOn ? (aiCats.data?.categories ?? []) : []}
          activeCategory={aiView ? category : null}
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
          classic={classic}
          aiCategories={aiOn ? (aiCats.data?.categories ?? []) : []}
          activeCategory={aiView ? category : null}
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
              navigate(listBasePath);
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
        {classic ? (
          <p
            className="type-caption border-b border-border-default bg-bg-subtle px-3 py-1.5 text-text-secondary"
            data-testid="classic-banner"
          >
            {t('classic.banner')}
          </p>
        ) : null}
        {selectedIds.size > 0 ? (
          <div className="flex h-14 shrink-0 items-center gap-1 border-b border-border-default px-2">
            <span className="type-small mr-2 text-text-primary">
              {t('mail.bulk.selected', { count: selectedIds.size })}
            </span>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'mark_seen', ids: [...selectedIds] })}
            >
              {t('mail.bulk.markRead')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'done', ids: [...selectedIds] })}
            >
              <CircleCheck size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.toolbar.done')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'archive', ids: [...selectedIds] })}
            >
              <Archive size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.toolbar.archive')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 hover:bg-bg-subtle"
              disabled={!canMarkSeen}
              onClick={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                setMovePicker({ ids: [...selectedIds], at: { x: box.left, y: box.bottom + 4 } });
              }}
            >
              <FolderInput size={14} className="mr-1 inline" aria-hidden="true" />
              {t('mail.moveTo.bulkMove')}
            </button>
            <button
              type="button"
              className="type-caption rounded-sm px-2 py-1 text-danger-600 hover:bg-bg-subtle"
              onClick={() => bulk.mutate({ action: 'delete', ids: [...selectedIds] })}
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
          {aiView && categoryMeta ? (
            <div className="flex items-center gap-2 px-1 pt-1" data-testid="ai-category-header">
              <span
                aria-hidden="true"
                className={`size-2.5 shrink-0 rounded-full ${categoryDotClass(categoryMeta.color_token)}`}
              />
              <div className="min-w-0 flex-1">
                <p className="type-label truncate text-text-primary">{categoryMeta.label_sk}</p>
                <p className="type-caption truncate text-text-secondary">{categoryMeta.description_sk}</p>
              </div>
            </div>
          ) : null}
          <label className={mobile ? 'hidden' : 'relative block'}>
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-2.5 text-text-secondary"
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
              className="type-body h-9 w-full rounded-md border border-transparent bg-bg-muted pl-9 pr-3 text-text-primary placeholder:text-text-tertiary focus:border-brand-primary-500 focus:bg-bg-canvas focus-visible:outline-none"
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
                  aria-pressed={filter === f}
                  className={`type-small h-[26px] rounded-full border px-2 ${
                    filter === f
                      ? 'border-brand-primary-600 bg-brand-primary-600 text-text-on-primary'
                      : 'border-border-default bg-bg-canvas text-text-primary hover:bg-bg-subtle'
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
              message={syncFailed ? t('mail.syncFailed', { email: view?.mailbox.email ?? '' }) : t('mail.loadFailed')}
              action={{ label: t('system.retry'), onClick: () => refresh.mutate(), disabled: refresh.isPending }}
            />
          </div>
        ) : null}

        {syncProgress && !serverDown ? (
          <p role="status" className="px-4 pb-2 pt-2 type-small text-text-secondary" data-testid="sync-progress">
            {t('mail.syncProgress', syncProgress)}
          </p>
        ) : null}

        <div
          role={rows.length > 0 && !list.isLoading ? 'listbox' : undefined}
          aria-label={label}
          className="min-h-0 flex-1 overflow-y-auto"
          data-testid={aiView ? 'ai-category-list' : 'folder-message-list'}
        >
          {aiView && !list.isLoading && total === 0 && !q.trim() && filter === 'all' ? (
            <EmptyState
              icon={<Sparkles size={20} />}
              title={t('ai.triage.emptyTitle', { name: label })}
              text={t('ai.triage.emptyText')}
            />
          ) : !aiView && folder && folder.total === 0 ? (
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
                (!aiView &&
                  activeThreadId !== null &&
                  (item.kind === 'thread' ? item.data.id === activeThreadId : item.data.thread_id === activeThreadId));
              const catId = item.kind === 'message' ? item.data.ai_category : null;
              const row = (
                <MessageRow
                  item={item}
                  selected={selected}
                  checked={selectedIds.has(id)}
                  showCheckbox={selectMode || selectedIds.size > 0}
                  density={density}
                  classic={classic}
                  showAiSummary={showAiSummary}
                  categoryColorToken={
                    catId ? (colorByCategory.get(catId) ?? CATEGORY_COLOR_TOKEN[catId] ?? null) : null
                  }
                  onSelect={() => openAndMarkSeen(id, tid, mobile)}
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
              // Keep role="option" as a direct listbox child (no wrapper div).
              if (!mobile) return <Fragment key={key}>{row}</Fragment>;
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
          folderRef={aiView ? 'inbox' : folderParam}
          messageId={activeMessageId}
          threadId={activeThreadId}
          onCleared={() => {
            setPickedMessageId(null);
            navigate(listBasePath, { replace: true });
          }}
        />
      )}

      {mobile && !mobileThread ? <LinkFab mailbox={mailboxRef} /> : null}

      {movePicker ? (
        <FolderPicker
          mailbox={mailboxRef}
          mode="move"
          currentFolderId={aiView ? null : (folderId ?? null)}
          at={movePicker.at}
          onPick={(dest) => {
            bulk.mutate({ action: 'move', ids: movePicker.ids, dest });
            setMovePicker(null);
          }}
          onClose={() => setMovePicker(null)}
        />
      ) : null}

      {purgeIds ? (
        <ConfirmDialog
          title={t('mail.purge.title', { count: purgeIds.length })}
          body={t('mail.purge.body')}
          confirmLabel={t('mail.purge.confirm')}
          onConfirm={() => {
            bulk.mutate({ action: 'purge', ids: purgeIds });
            setPurgeIds(null);
          }}
          onClose={() => setPurgeIds(null)}
        />
      ) : null}

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
