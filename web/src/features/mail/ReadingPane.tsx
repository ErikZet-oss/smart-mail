import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlarmClock,
  Archive,
  ArrowLeft,
  CircleCheck,
  Code,
  Copy,
  FileCheck2,
  Sparkles,
  Tags,
  Ellipsis,
  Flame,
  Flag,
  FolderInput,
  Forward,
  Mail,
  Paperclip,
  Printer,
  Reply,
  ReplyAll,
  SquareArrowOutUpRight,
  Tag,
  Trash2,
  UserPlus,
} from 'lucide-react';
import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ConformityDialog } from '../documents/ConformityDialog';
import { CategoryDialog } from './CategoryDialog';
import { Link, useNavigate } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Menu, type MenuEntry } from '../../components/Menu';
import { SecurityBanner } from '../../components/SecurityBanner';
import { useToast } from '../../components/toastContext';
import { ApiError, formatRef } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { AiSuggestionCard } from '../ai/AiSuggestionCard';
import { fetchSuggestions, suggestionsKey } from '../ai/suggestionsApi';
import { fetchMe } from '../auth/authApi';
import { booksKey, createContact, fetchBooks } from '../contacts/contactsApi';
import { useTheme } from '../prefs/ThemeProvider';
import { AttachmentLightbox } from './AttachmentLightbox';
import { openExternalLinkInNewTab } from './externalLinks';
import { formatMailDate } from './formatMailDate';
import { FolderPicker } from './FolderPicker';
import { applyActionLocally, REMOVING_ACTIONS } from './optimistic';
import { useFolderLabel } from './useFolderLabel';
import { previewKind } from './previewKind';
import {
  applyAttachmentFlagLocally,
  attachmentUrl,
  bulkMessages,
  foldersKey,
  type Folder,
  fetchMessage,
  messageKey,
  patchFlags,
  reclassifyMessage,
  snoozeThread,
} from './mailApi';

type Props = {
  mailbox: string;
  folderRef: string;
  messageId: string | null;
  threadId: string | null;
  /** Konverzácie: opening marks the whole conversation read (Roundcube). */
  conversation?: boolean;
  onCleared: () => void;
};

function ToolBtn({
  icon,
  label,
  onClick,
  disabled,
  busy,
}: {
  icon: ReactNode;
  label: string;
  onClick?: (event: MouseEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const { t } = useTranslation();
  const off = disabled || !onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={off || busy}
      title={off ? t('common.comingSoon') : undefined}
      className={`flex h-14 min-w-[64px] flex-col items-center justify-center gap-1 rounded-sm px-1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
        off ? 'cursor-not-allowed text-text-tertiary' : 'text-text-primary hover:bg-bg-subtle'
      }`}
    >
      <span aria-hidden="true">{icon}</span>
      <span className="type-micro max-w-[72px] truncate">{label}</span>
    </button>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showRemoteImages(html: string): string {
  return html.replace(/src=(["'])about:blank#smartmail-remote\1\s+data-remote-src=(["'])([^"']+)\2/gi, 'src=$2$3$2');
}

function menuAt(event: MouseEvent<HTMLButtonElement>) {
  const r = event.currentTarget.getBoundingClientRect();
  return { x: r.left, y: r.bottom + 4 };
}

/** W2c reading pane: Roundcube toolbar order; Reply/Forward open W4 (Phase 1e). */
type PaneAction = 'delete' | 'junk' | 'archive' | 'done' | 'move' | 'copy';

export function ReadingPane({ mailbox, folderRef, messageId, threadId, onCleared, conversation = false }: Props) {
  const mobile = useMediaQuery(MOBILE_QUERY);
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { classic } = useTheme();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [showImages, setShowImages] = useState(false);
  const [plain, setPlain] = useState(false);
  const [markMenu, setMarkMenu] = useState<{ x: number; y: number } | null>(null);
  const [moreMenu, setMoreMenu] = useState<{ x: number; y: number } | null>(null);
  const [conformity, setConformity] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const readOnly = !me.data?.person || Boolean(me.data.read_only);
  // #143 „Znova zaradiť (AI)“: one classify call; a manual correction or a spent budget is explained in the toast
  const reclassify = useMutation({
    mutationFn: () => reclassifyMessage(mailbox, messageId ?? ''),
    onSuccess: (out) => {
      toast({
        message: t('mail.category.reclassified', {
          category: t(`ai.categories.${out.category ?? 'other'}.label`, { defaultValue: out.category ?? '' }),
        }),
      });
      void queryClient.invalidateQueries({ queryKey: ['mail'] });
    },
    onError: (error) => {
      const code = error instanceof ApiError ? error.detail.code : 'generic';
      toast({ message: t(`mail.category.errors.${code}`, { defaultValue: t('mail.errors.generic') }) });
    },
  });
  const labelOf = useFolderLabel();
  const [snoozeMenu, setSnoozeMenu] = useState<{ x: number; y: number } | null>(null);

  const detail = useQuery({
    queryKey: messageKey(mailbox, messageId ?? ''),
    queryFn: () => {
      if (!messageId) throw new Error('message missing');
      return fetchMessage(mailbox, messageId, true, conversation);
    },
    enabled: Boolean(messageId),
  });
  useEffect(() => {
    if (detail.data) applyAttachmentFlagLocally(queryClient, mailbox, detail.data);
  }, [detail.data, mailbox, queryClient]);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const previewable = (detail.data?.attachments ?? []).filter(
    (a) => !a.is_inline && a.av_status !== 'infected' && previewKind(a) !== null,
  );
  const loadErrorRef =
    detail.error instanceof ApiError && detail.error.detail.ref ? formatRef(String(detail.error.detail.ref)) : '';

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['mail', 'messages', mailbox] });
    if (messageId) void queryClient.invalidateQueries({ queryKey: messageKey(mailbox, messageId) });
  };

  const flags = useMutation({
    mutationFn: (body: { seen?: boolean; flagged?: boolean }) => {
      if (!messageId) return Promise.reject(new Error('message missing'));
      return patchFlags(mailbox, messageId, body);
    },
    // #89: the row icon changes at once; a failed request puts it back.
    onMutate: (body) => {
      if (!messageId) return { rollback: () => undefined };
      const action =
        body.seen === true
          ? 'mark_seen'
          : body.seen === false
            ? 'mark_unseen'
            : body.flagged === true
              ? 'flag'
              : 'unflag';
      return { rollback: applyActionLocally(queryClient, mailbox, [messageId], action) };
    },
    onSuccess: (data) => {
      queryClient.setQueryData(messageKey(mailbox, data.id), data);
    },
    onError: (error, _body, context) => {
      context?.rollback();
      if (!(error instanceof ApiError) || error.detail.code !== 'mail_server_unavailable') {
        toast({ message: t('mail.errors.generic') });
      }
    },
    onSettled: invalidate,
  });

  const bulk = useMutation({
    mutationFn: ({ action, id, dest }: { action: PaneAction; id: string; dest?: Folder }) =>
      bulkMessages(mailbox, { message_ids: [id], action, dest_folder_id: dest?.id }),
    // #89: the row disappears and the pane closes at once; a failed request brings the row back.
    onMutate: async ({ action, id }) => {
      await queryClient.cancelQueries({ queryKey: ['mail', 'messages', mailbox] });
      const rollback = applyActionLocally(queryClient, mailbox, [id], action);
      if (REMOVING_ACTIONS.has(action)) onCleared();
      return { rollback };
    },
    onSuccess: (_r, { action, dest }) =>
      toast({
        message: dest
          ? t(action === 'copy' ? 'mail.moveTo.copied' : 'mail.moveTo.moved', { folder: labelOf(dest) })
          : t(`mail.toast.${action}`),
      }),
    onError: (_e, _v, context) => {
      context?.rollback();
      toast({ message: t('mail.errors.generic') });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['mail', 'messages', mailbox] });
      void queryClient.invalidateQueries({ queryKey: foldersKey(mailbox) });
    },
  });
  const runBulk = (action: PaneAction, dest?: Folder) => {
    if (messageId) bulk.mutate({ action, id: messageId, dest });
  };
  const [picker, setPicker] = useState<{ mode: 'move' | 'copy'; at: { x: number; y: number } } | null>(null);

  const snooze = useMutation({
    mutationFn: (until: string | null) => {
      if (!threadId) return Promise.reject(new Error('thread missing'));
      return snoozeThread(mailbox, threadId, until);
    },
    onSuccess: () => {
      toast({ message: t('mail.toast.snooze') });
      invalidate();
    },
  });

  const msg = detail.data;
  const remoteOffered = Boolean(msg?.remote_images_offered);
  const hasRemote = remoteOffered && Boolean(msg?.body_html_sanitized?.includes('smartmail-remote'));
  // Server decides: "always", or "known" and the sender is a contact / internal (B6). Otherwise the bar asks.
  const imagesVisible = showImages || Boolean(msg?.remote_images_auto);
  // Roundcube "Vždy povoliť od …": the sender goes to the personal address book, so "known" shows them next time.
  const allowSender = useMutation({
    mutationFn: async () => {
      const email = msg?.from_email?.trim();
      if (!email) throw new Error('no_sender');
      const books = await queryClient.fetchQuery({ queryKey: booksKey, queryFn: fetchBooks });
      const personal = books.find((b) => b.kind === 'personal');
      if (!personal) throw new Error('no_personal_book');
      await createContact(personal.id, {
        display_name: msg?.from_name?.trim() || email,
        emails: [{ email }],
      });
      return email;
    },
    onSuccess: (email) => {
      setShowImages(true);
      toast({ message: t('mail.remoteImagesAllowed', { email }) });
      void queryClient.invalidateQueries({ queryKey: ['contacts'] });
    },
    onError: () => {
      setShowImages(true);
      toast({ message: t('mail.errors.generic') });
    },
  });
  const bodyHtml = useMemo(() => {
    if (!msg?.body_html_sanitized) return null;
    return imagesVisible ? showRemoteImages(msg.body_html_sanitized) : msg.body_html_sanitized;
  }, [msg, imagesVisible]);

  if (!messageId) {
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

  const markEntries: MenuEntry[] = msg
    ? [
        {
          kind: 'item',
          id: 'seen',
          label: msg.seen ? t('mail.mark.unseen') : t('mail.mark.seen'),
          onSelect: () => {
            setMarkMenu(null);
            flags.mutate({ seen: !msg.seen });
          },
        },
        {
          kind: 'item',
          id: 'flag',
          label: msg.flagged ? t('mail.mark.unflag') : t('mail.mark.flag'),
          icon: <Flag size={16} />,
          onSelect: () => {
            setMarkMenu(null);
            flags.mutate({ flagged: !msg.flagged });
          },
        },
      ]
    : [];

  const moreEntries: MenuEntry[] = msg
    ? [
        {
          kind: 'item',
          id: 'archive',
          label: t('mail.toolbar.archive'),
          icon: <Archive size={16} />,
          onSelect: () => {
            setMoreMenu(null);
            runBulk('archive');
          },
        },
        {
          kind: 'item',
          id: 'move',
          label: t('mail.moveTo.move'),
          icon: <FolderInput size={16} />,
          disabled: readOnly,
          onSelect: () => {
            const at = moreMenu ?? { x: 0, y: 0 };
            setMoreMenu(null);
            setPicker({ mode: 'move', at });
          },
        },
        {
          kind: 'item',
          id: 'copy',
          label: t('mail.moveTo.copy'),
          icon: <Copy size={16} />,
          disabled: readOnly,
          onSelect: () => {
            const at = moreMenu ?? { x: 0, y: 0 };
            setMoreMenu(null);
            setPicker({ mode: 'copy', at });
          },
        },
        { kind: 'divider', id: 'd-move' },
        {
          kind: 'item',
          id: 'category',
          label: t('mail.category.menu'),
          icon: <Tags size={16} />,
          // #143: sales/admin with an active person; the server checks the role again
          disabled: readOnly || !['sales', 'admin'].includes(me.data?.person?.role ?? ''),
          onSelect: () => {
            setMoreMenu(null);
            setCategoryOpen(true);
          },
        },
        {
          kind: 'item',
          id: 'reclassify',
          label: t('mail.category.reclassify'),
          icon: <Sparkles size={16} />,
          disabled: readOnly || !['sales', 'admin'].includes(me.data?.person?.role ?? ''),
          onSelect: () => {
            setMoreMenu(null);
            reclassify.mutate();
          },
        },
        {
          kind: 'item',
          id: 'conformity',
          label: t('conformity.menu'),
          icon: <FileCheck2 size={16} />,
          // #139: sales or admin with an active person; the server checks the branch, stamp and signature again
          disabled: readOnly || !['sales', 'admin'].includes(me.data?.person?.role ?? ''),
          onSelect: () => {
            setMoreMenu(null);
            setConformity(true);
          },
        },
        {
          kind: 'item',
          id: 'print',
          label: t('mail.toolbar.print'),
          icon: <Printer size={16} />,
          onSelect: () => {
            setMoreMenu(null);
            window.open(
              `/mail/${encodeURIComponent(mailbox)}/${encodeURIComponent(folderRef)}/${encodeURIComponent(msg.thread_id ?? 'x')}/print?m=${msg.id}`,
              '_blank',
            );
          },
        },
        {
          kind: 'item',
          id: 'source',
          label: t('mail.toolbar.source'),
          icon: <Code size={16} />,
          onSelect: () => {
            setMoreMenu(null);
            window.open(
              `/mail/${encodeURIComponent(mailbox)}/${encodeURIComponent(folderRef)}/${encodeURIComponent(msg.thread_id ?? 'x')}/source/${msg.id}`,
              '_blank',
            );
          },
        },
      ]
    : [];

  const snoozeEntries: MenuEntry[] = [
    {
      kind: 'item',
      id: 'today',
      label: t('mail.snooze.today'),
      onSelect: () => {
        setSnoozeMenu(null);
        const d = new Date();
        d.setHours(15, 0, 0, 0);
        if (d.getTime() < Date.now()) d.setDate(d.getDate() + 1);
        snooze.mutate(d.toISOString());
      },
    },
    {
      kind: 'item',
      id: 'tomorrow',
      label: t('mail.snooze.tomorrow'),
      onSelect: () => {
        setSnoozeMenu(null);
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(8, 0, 0, 0);
        snooze.mutate(d.toISOString());
      },
    },
    {
      kind: 'item',
      id: 'clear',
      label: t('mail.snooze.clear'),
      onSelect: () => {
        setSnoozeMenu(null);
        snooze.mutate(null);
      },
    },
  ];

  return (
    <section aria-label={t('mail.readingPane')} className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-canvas">
      {mobile ? (
        <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-1">
          <button
            type="button"
            onClick={onCleared}
            aria-label={t('system.back')}
            className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
          >
            <ArrowLeft size={22} />
          </button>
          <p className="type-heading min-w-0 flex-1 truncate text-text-primary">
            {/* no "(bez predmetu)" while the message is loading or failed to load (#41) */}
            {msg ? msg.subject || t('search.noSubject') : ''}
          </p>
        </header>
      ) : null}
      <div
        className={`flex h-14 shrink-0 items-center gap-0.5 overflow-x-auto border-border-default px-2 ${
          mobile ? 'order-last border-t' : 'border-b'
        }`}
      >
        <ToolBtn
          icon={<Reply size={18} />}
          label={t('mail.toolbar.reply')}
          onClick={() =>
            navigate(`/compose?mode=reply&mailbox=${encodeURIComponent(mailbox)}&m=${encodeURIComponent(messageId)}`)
          }
        />
        <ToolBtn
          icon={<ReplyAll size={18} />}
          label={t('mail.toolbar.replyAll')}
          onClick={() =>
            navigate(
              `/compose?mode=reply_all&mailbox=${encodeURIComponent(mailbox)}&m=${encodeURIComponent(messageId)}`,
            )
          }
        />
        <ToolBtn
          icon={<Forward size={18} />}
          label={t('mail.toolbar.forward')}
          onClick={() =>
            navigate(`/compose?mode=forward&mailbox=${encodeURIComponent(mailbox)}&m=${encodeURIComponent(messageId)}`)
          }
        />
        <ToolBtn
          icon={<Trash2 size={18} />}
          label={t('mail.toolbar.delete')}
          onClick={() => runBulk('delete')}
          busy={bulk.isPending}
        />
        <ToolBtn
          icon={<Flame size={18} />}
          label={t('mail.toolbar.junk')}
          onClick={() => runBulk('junk')}
          busy={bulk.isPending}
        />
        <ToolBtn
          icon={<Tag size={18} />}
          label={t('mail.toolbar.mark')}
          onClick={(event) => setMarkMenu(menuAt(event))}
        />
        <ToolBtn
          icon={<Ellipsis size={18} />}
          label={t('mail.toolbar.more')}
          onClick={(event) => setMoreMenu(menuAt(event))}
        />
        <span aria-hidden="true" className="mx-1 h-8 w-px bg-border-default" />
        <ToolBtn icon={<UserPlus size={18} />} label={t('mail.toolbar.assign')} disabled />
        <ToolBtn icon={<CircleCheck size={18} />} label={t('mail.toolbar.done')} onClick={() => runBulk('done')} />
        <ToolBtn
          icon={<AlarmClock size={18} />}
          label={t('mail.toolbar.snooze')}
          onClick={(event) => setSnoozeMenu(menuAt(event))}
          disabled={!threadId}
        />
      </div>

      {detail.isError && !msg ? (
        // G-state error instead of an endless skeleton (#41), with the support code of a 500.
        <div className="p-4" data-testid="message-load-error">
          <Banner
            kind="danger"
            message={
              loadErrorRef
                ? `${t('mail.loadMessageFailed')} ${t('system.error.code', { ref: loadErrorRef })}`
                : t('mail.loadMessageFailed')
            }
            action={{ label: t('system.retry'), onClick: () => void detail.refetch(), disabled: detail.isFetching }}
          />
        </div>
      ) : detail.isLoading || !msg ? (
        <div aria-busy="true" className="flex flex-1 flex-col gap-3 p-7">
          <div className="h-6 w-2/3 rounded-xs bg-bg-muted" />
          <div className="h-4 w-1/2 rounded-xs bg-bg-muted" />
          <div className="mt-6 h-40 rounded-xs bg-bg-muted" />
        </div>
      ) : (
        <div className={`min-h-0 flex-1 overflow-y-auto overscroll-contain ${mobile ? 'px-4 py-3' : 'px-7 py-4'}`}>
          <div className="mb-4 flex items-start gap-2">
            <h2 className={`${mobile ? 'type-heading' : 'type-title'} min-w-0 flex-1 break-words text-text-primary`}>
              {msg.subject || t('mail.noSubject')}
            </h2>
            <Link
              to={`/mail/${encodeURIComponent(mailbox)}/${encodeURIComponent(folderRef)}/${encodeURIComponent(msg.thread_id ?? msg.id)}`}
              className={`shrink-0 rounded-xs text-text-secondary hover:text-text-primary ${mobile ? 'hidden' : ''}`}
              title={t('mail.openFull')}
              aria-label={t('mail.openFull')}
            >
              <SquareArrowOutUpRight size={18} aria-hidden="true" />
            </Link>
          </div>
          <div className="mb-6 flex gap-3">
            <div
              aria-hidden="true"
              className="flex size-12 shrink-0 items-center justify-center rounded-full bg-brand-primary-100 type-label text-brand-primary-700"
            >
              {(msg.from_name || msg.from_email || '?').slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="type-body text-text-primary">
                <span className="text-text-secondary">{t('mail.from')}</span>{' '}
                <span className="font-semibold">{msg.from_name || msg.from_email}</span>
                {msg.from_email ? <span className="text-text-secondary"> &lt;{msg.from_email}&gt;</span> : null}
              </p>
              <p className="type-small text-text-primary">
                <span className="text-text-secondary">{t('mail.to')}</span>{' '}
                {msg.to
                  .map((a) => a.name || a.email)
                  .filter(Boolean)
                  .join(', ') || '—'}
              </p>
              <p className="type-small text-text-primary">
                <span className="text-text-secondary">{t('mail.date')}</span>{' '}
                {formatMailDate(msg.received_at || msg.sent_at)}
              </p>
              <div className="mt-1 flex gap-4">
                <button
                  type="button"
                  onClick={() => setPlain((v) => !v)}
                  className="type-caption inline-flex items-center gap-1 text-brand-primary-600 hover:underline"
                >
                  <Mail size={14} aria-hidden="true" />
                  {plain ? t('mail.showHtml') : t('mail.plainText')}
                </button>
              </div>
            </div>
          </div>

          {hasRemote && !imagesVisible ? (
            <div className="mb-4">
              <Banner
                kind="info"
                message={t('mail.remoteImages')}
                action={{ label: t('mail.showImages'), onClick: () => setShowImages(true) }}
                secondaryAction={
                  msg.from_email
                    ? {
                        label: t('mail.showImagesAlways'),
                        onClick: () => allowSender.mutate(),
                        disabled: allowSender.isPending,
                      }
                    : undefined
                }
              />
            </div>
          ) : null}

          {classic ? null : <SecurityBanner notes={msg.security_notes ?? []} />}

          {classic ? null : (
            <SuggestionCards
              mailbox={mailbox}
              messageId={msg.id}
              category={msg.ai_category ?? null}
              readOnly={readOnly}
            />
          )}

          {previewIndex !== null ? (
            <AttachmentLightbox
              mailbox={mailbox}
              attachments={previewable}
              index={previewIndex}
              onIndex={setPreviewIndex}
              onClose={() => setPreviewIndex(null)}
              formatSize={formatSize}
            />
          ) : null}

          {msg.attachments.filter((a) => !a.is_inline).length > 0 ? (
            <ul className="mb-4 flex flex-wrap gap-2">
              {msg.attachments
                .filter((a) => !a.is_inline)
                .map((a) => {
                  const unscanned = a.av_status === 'skipped' || a.av_status === 'error';
                  const infected = a.av_status === 'infected';
                  return (
                    <li key={a.id}>
                      <a
                        href={attachmentUrl(mailbox, a.id)}
                        className={`type-small inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1.5 ${
                          infected
                            ? 'cursor-not-allowed border-danger-600 text-danger-600'
                            : 'border-border-default text-text-primary hover:bg-bg-subtle'
                        }`}
                        title={
                          infected
                            ? t('mail.attachmentInfected')
                            : unscanned
                              ? t('mail.attachmentUnscanned')
                              : undefined
                        }
                        onClick={(event) => {
                          if (infected) {
                            event.preventDefault();
                            return;
                          }
                          if (unscanned && !window.confirm(t('mail.attachmentUnscannedConfirm'))) {
                            event.preventDefault();
                            return;
                          }
                          // PDF, images and XML/ISDOC open in W2l first (#46); everything else downloads
                          const at = previewable.findIndex((p) => p.id === a.id);
                          if (at >= 0) {
                            event.preventDefault();
                            setPreviewIndex(at);
                          }
                        }}
                        download={infected ? undefined : a.filename}
                      >
                        <Paperclip size={14} aria-hidden="true" />
                        {a.filename} <span className="text-text-secondary">{formatSize(a.size)}</span>
                        {unscanned ? (
                          <span className="text-text-tertiary">({t('mail.attachmentUnscanned')})</span>
                        ) : null}
                      </a>
                    </li>
                  );
                })}
            </ul>
          ) : null}

          {plain || !bodyHtml ? (
            <pre className="type-body-lg whitespace-pre-wrap break-words font-ui text-text-primary">
              {msg.body_text || ''}
            </pre>
          ) : (
            <div
              className="type-body-lg max-w-none overflow-x-auto text-text-primary [&_a]:text-brand-primary-600 [&_img]:h-auto [&_img]:max-w-full"
              // sanitized on the server (nh3); remote images stay blocked until the user opts in
              dangerouslySetInnerHTML={{ __html: bodyHtml }}
              onClick={openExternalLinkInNewTab}
            />
          )}
        </div>
      )}

      {markMenu ? (
        <Menu
          label={t('mail.toolbar.mark')}
          entries={markEntries}
          at={markMenu}
          width={220}
          onClose={() => setMarkMenu(null)}
        />
      ) : null}
      {categoryOpen && msg ? (
        <CategoryDialog
          mailbox={mailbox}
          messageId={msg.id}
          current={msg.ai_category ?? null}
          onClose={() => setCategoryOpen(false)}
        />
      ) : null}
      {conformity && msg ? (
        <ConformityDialog
          messageId={msg.id}
          initialCustomer={[msg.from_name, msg.from_email].filter(Boolean).join(', ')}
          onClose={() => setConformity(false)}
        />
      ) : null}
      {moreMenu ? (
        <Menu
          label={t('mail.toolbar.more')}
          entries={moreEntries}
          at={moreMenu}
          width={240}
          onClose={() => setMoreMenu(null)}
        />
      ) : null}
      {picker && msg ? (
        <FolderPicker
          mailbox={mailbox}
          mode={picker.mode}
          currentFolderId={msg.folder_id}
          at={picker.at}
          onPick={(folder) => {
            setPicker(null);
            runBulk(picker.mode, folder);
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
      {snoozeMenu ? (
        <Menu
          label={t('mail.toolbar.snooze')}
          entries={snoozeEntries}
          at={snoozeMenu}
          width={220}
          onClose={() => setSnoozeMenu(null)}
        />
      ) : null}
    </section>
  );
}

const VISIBLE_CARDS = 2;

/** W2c AI cards (#94): max 2 visible + „Ďalšie návrhy (n)“; shadow suggestions never reach the client. */
function SuggestionCards({
  mailbox,
  messageId,
  category,
  readOnly,
}: {
  mailbox: string;
  messageId: string;
  category: string | null;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  const cards = useQuery({
    queryKey: suggestionsKey(mailbox, messageId),
    queryFn: () => fetchSuggestions(mailbox, messageId),
    retry: false,
  });
  const list = cards.data ?? [];
  if (list.length === 0) return null;
  const shown = all ? list : list.slice(0, VISIBLE_CARDS);
  return (
    <div className="flex flex-col gap-2 py-3" data-testid="ai-suggestions">
      {shown.map((s) => (
        <AiSuggestionCard
          key={s.id}
          suggestion={s}
          mailbox={mailbox}
          messageId={messageId}
          category={category}
          readOnly={readOnly}
        />
      ))}
      {list.length > VISIBLE_CARDS && !all ? (
        <button
          type="button"
          className="type-small self-start text-brand-primary-700 hover:underline"
          onClick={() => setAll(true)}
        >
          {t('ai.card.moreCards', { count: list.length - VISIBLE_CARDS })}
        </button>
      ) : null}
    </div>
  );
}
