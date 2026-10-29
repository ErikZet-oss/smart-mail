import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlarmClock,
  Archive,
  ArrowLeft,
  CircleCheck,
  Code,
  Ellipsis,
  Flame,
  Flag,
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
import { useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Menu, type MenuEntry } from '../../components/Menu';
import { SecurityBanner } from '../../components/SecurityBanner';
import { useToast } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { booksKey, createContact, fetchBooks } from '../contacts/contactsApi';
import { useTheme } from '../prefs/ThemeProvider';
import { formatMailDate } from './formatMailDate';
import { attachmentUrl, bulkMessages, fetchMessage, messageKey, patchFlags, snoozeThread } from './mailApi';

type Props = {
  mailbox: string;
  folderRef: string;
  messageId: string | null;
  threadId: string | null;
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
export function ReadingPane({ mailbox, folderRef, messageId, threadId, onCleared }: Props) {
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
  const [snoozeMenu, setSnoozeMenu] = useState<{ x: number; y: number } | null>(null);

  const detail = useQuery({
    queryKey: messageKey(mailbox, messageId ?? ''),
    queryFn: () => {
      if (!messageId) throw new Error('message missing');
      return fetchMessage(mailbox, messageId);
    },
    enabled: Boolean(messageId),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['mail', 'messages', mailbox] });
    if (messageId) void queryClient.invalidateQueries({ queryKey: messageKey(mailbox, messageId) });
  };

  const flags = useMutation({
    mutationFn: (body: { seen?: boolean; flagged?: boolean }) => {
      if (!messageId) return Promise.reject(new Error('message missing'));
      return patchFlags(mailbox, messageId, body);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(messageKey(mailbox, data.id), data);
      invalidate();
    },
    onError: (error) => {
      if (!(error instanceof ApiError) || error.detail.code !== 'mail_server_unavailable') {
        toast({ message: t('mail.errors.generic') });
      }
    },
  });

  const bulk = useMutation({
    mutationFn: (action: 'delete' | 'junk' | 'archive' | 'done') => {
      if (!messageId) return Promise.reject(new Error('message missing'));
      return bulkMessages(mailbox, { message_ids: [messageId], action });
    },
    onSuccess: (_r, action) => {
      toast({ message: t(`mail.toast.${action}`) });
      invalidate();
      if (action === 'delete' || action === 'junk' || action === 'archive') onCleared();
    },
    onError: () => toast({ message: t('mail.errors.generic') }),
  });

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
            bulk.mutate('archive');
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
            {msg?.subject || t('search.noSubject')}
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
          onClick={() => bulk.mutate('delete')}
          busy={bulk.isPending}
        />
        <ToolBtn
          icon={<Flame size={18} />}
          label={t('mail.toolbar.junk')}
          onClick={() => bulk.mutate('junk')}
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
        <ToolBtn icon={<CircleCheck size={18} />} label={t('mail.toolbar.done')} onClick={() => bulk.mutate('done')} />
        <ToolBtn
          icon={<AlarmClock size={18} />}
          label={t('mail.toolbar.snooze')}
          onClick={(event) => setSnoozeMenu(menuAt(event))}
          disabled={!threadId}
        />
      </div>

      {detail.isError ? (
        <div className="p-4">
          <Banner
            kind="danger"
            message={t('mail.loadMessageFailed')}
            action={{ label: t('system.retry'), onClick: () => void detail.refetch() }}
          />
        </div>
      ) : null}

      {detail.isLoading || !msg ? (
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
      {moreMenu ? (
        <Menu
          label={t('mail.toolbar.more')}
          entries={moreEntries}
          at={moreMenu}
          width={240}
          onClose={() => setMoreMenu(null)}
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
