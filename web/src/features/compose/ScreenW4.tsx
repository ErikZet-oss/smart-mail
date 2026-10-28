import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {
  Bold,
  ChevronDown,
  Clock,
  Italic,
  List,
  Maximize2,
  Minimize2,
  Paperclip,
  PenLine,
  Reply,
  Save,
  Send,
  Underline as UnderlineIcon,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import {
  createDraft,
  fetchDraft,
  listIdentities,
  patchDraft,
  sendDraft,
  undoDraft,
  uploadAttachment,
  type ComposeMode,
} from './composeApi';
import { PreSendDialog } from './PreSendDialog';
import { ResponsesPicker } from './ResponsesPicker';
import { ScheduleSendDialog } from './ScheduleSendDialog';
import { SignatureEditDialog } from './SignatureEditDialog';

const POPUP_KEY = 'sm-compose-popups';
const POPUP_MAX = 3;

function popupCount(): number {
  try {
    return JSON.parse(sessionStorage.getItem(POPUP_KEY) ?? '[]').length;
  } catch {
    return 0;
  }
}

function trackPopup(id: string, add: boolean) {
  try {
    const cur = new Set<string>(JSON.parse(sessionStorage.getItem(POPUP_KEY) ?? '[]') as string[]);
    if (add) cur.add(id);
    else cur.delete(id);
    sessionStorage.setItem(POPUP_KEY, JSON.stringify([...cur]));
  } catch {
    /* ignore */
  }
}

function parseAddrs(raw: string): { email: string; name?: string }[] {
  return raw
    .split(/[,;]+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^(.*)<([^>]+)>$/);
      if (m) return { name: m[1]?.trim() || undefined, email: (m[2] ?? '').trim() };
      return { email: part };
    });
}

function formatAddrs(addrs: { name?: string | null; email: string }[]): string {
  return addrs.map((a) => (a.name ? `${a.name} <${a.email}>` : a.email)).join(', ');
}

type SendErrorMeta = {
  code: string;
  blocked?: string[];
  allowlist?: string[];
  show_allowlist?: boolean;
};

/** Slovak copy for Send-click allowlist 422 (pilot #18 B7). */
function formatAllowlistFailure(
  t: (key: string, opts?: Record<string, string>) => string,
  meta: SendErrorMeta,
): string {
  const email = meta.blocked?.[0] ?? '';
  if (meta.show_allowlist) {
    return t('compose.sendErrorRecipientNotAllowedTest', {
      list: (meta.allowlist ?? []).join(', ') || '—',
      email,
    });
  }
  return t('compose.sendErrorRecipientNotAllowed', { email });
}

/** Map draft.send_error codes to Slovak copy (GitHub #20). */
function sendErrorMessage(t: (key: string) => string, sendError: string | null | undefined): string {
  const code = (sendError ?? '').split(':')[0] || '';
  if (code === 'auth_failed') return t('compose.sendErrorAuth');
  if (code === 'no_credentials') return t('compose.sendErrorNoCredentials');
  if (code === 'server_unavailable' || code === 'smtp_host_not_allowed') return t('compose.sendErrorServer');
  if (
    code === 'SMTPRecipientsRefused' ||
    code === 'SMTPDataError' ||
    code === 'SMTPSenderRefused' ||
    code === 'recipient_not_allowed'
  ) {
    return t('compose.sendErrorRejected');
  }
  return t('compose.sendFailed');
}

/** W4 Písanie — Roundcube-like compose (Phase 1e). AI tab deferred (no AI in Phase 1). */
export function ScreenW4() {
  const { t, i18n } = useTranslation();
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const toasts = useToasts();
  const qc = useQueryClient();
  const mailbox = search.get('mailbox') ?? 'default';
  const draftId = params.draftId;
  const mode = (search.get('mode') as ComposeMode | null) ?? 'new';
  const messageId = search.get('m') ?? undefined;
  /** Prefill To from contacts / search (never mailto: — keep send inside Smart Mail). */
  const seedTo = search.get('to')?.trim() ?? '';
  const isPopup = search.get('popup') === '1';

  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: fetchMe });
  const [localId, setLocalId] = useState<string | null>(draftId ?? null);
  const [to, setTo] = useState(seedTo);
  const [cc, setCc] = useState('');
  const [subject, setSubject] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high'>('normal');
  const [mdn, setMdn] = useState(false);
  const [showCc, setShowCc] = useState(false);
  const [preSendOpen, setPreSendOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [sendMenuOpen, setSendMenuOpen] = useState(false);
  const [responsesOpen, setResponsesOpen] = useState(false);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [minimized, setMinimized] = useState(false);
  /** Immediate Send-click failure (422) so we do not wait for a worker poll (pilot #18 B7). */
  const [sendFailMeta, setSendFailMeta] = useState<SendErrorMeta | null>(null);

  useEffect(() => {
    if (!isPopup || !localId) return;
    trackPopup(localId, true);
    return () => trackPopup(localId, false);
  }, [isPopup, localId]);

  const bootstrap = useMutation({
    mutationFn: () => createDraft(mailbox, { mode, message_id: messageId }),
    onSuccess: (draft) => {
      setLocalId(draft.id);
      const qs = new URLSearchParams({ mailbox });
      if (seedTo) qs.set('to', seedTo);
      navigate(`/compose/${draft.id}?${qs.toString()}`, { replace: true });
      applyDraft(draft);
    },
  });

  const draftQuery = useQuery({
    queryKey: ['compose', localId],
    queryFn: () => {
      if (!localId) throw new Error('no draft');
      return fetchDraft(localId);
    },
    enabled: Boolean(localId),
  });

  const identities = useQuery({
    queryKey: ['identities', mailbox],
    queryFn: () => listIdentities(mailbox),
  });

  const editor = useEditor({
    extensions: [StarterKit],
    content: '',
    onUpdate: () => setDirty(true),
    editorProps: {
      attributes: {
        class: 'type-body min-h-[280px] px-4 py-3 focus:outline-none text-text-primary',
        'aria-label': t('compose.editor'),
      },
    },
  });

  function applyDraft(d: NonNullable<typeof draftQuery.data>) {
    const draftTo = formatAddrs(d.to_addrs);
    setTo(draftTo || seedTo);
    setCc(formatAddrs(d.cc_addrs));
    if (d.cc_addrs.length) setShowCc(true);
    setSubject(d.subject);
    setPriority(d.priority);
    setMdn(d.request_mdn);
    editor?.commands.setContent(d.body_html || '<p></p>');
    setDirty(Boolean(seedTo && !draftTo));
  }

  useEffect(() => {
    if (!draftId && !localId && !bootstrap.isPending && !bootstrap.isSuccess) {
      bootstrap.mutate();
    }
  }, [draftId, localId, bootstrap]);

  useEffect(() => {
    // Do not clobber in-progress edits when a late GET/hydrate arrives (pilot #18 B7 e2e).
    if (draftQuery.data && !dirty) applyDraft(draftQuery.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- apply once per draft payload / when edits flush
  }, [draftQuery.data?.id, draftQuery.data?.updated_at, dirty]);

  // Poll while queued/sending so SMTP failures leave a Slovak banner instead of „Odosiela sa…“ (#20).
  const draftStatus = draftQuery.data?.status;
  const refetchDraft = draftQuery.refetch;
  const failedToastKey = useRef<string | null>(null);
  useEffect(() => {
    if (draftStatus !== 'queued' && draftStatus !== 'sending') return;
    const id = window.setInterval(() => {
      void refetchDraft();
    }, 1_000);
    return () => window.clearInterval(id);
  }, [draftStatus, refetchDraft]);
  useEffect(() => {
    const d = draftQuery.data;
    if (d?.status !== 'failed' || !d.send_error) return;
    const key = `${d.id}:${d.send_error}`;
    if (failedToastKey.current === key) return;
    failedToastKey.current = key;
    toasts.error(sendErrorMessage(t, d.send_error));
  }, [draftQuery.data, t, toasts]);

  const save = useMutation({
    mutationFn: async () => {
      if (!localId) return null;
      return patchDraft(localId, {
        to_addrs: parseAddrs(to),
        cc_addrs: parseAddrs(cc),
        subject,
        body_html: editor?.getHTML() ?? '',
        priority,
        request_mdn: mdn,
      });
    },
    onSuccess: (d) => {
      if (d) {
        void qc.setQueryData(['compose', localId], d);
        setDirty(false);
        toasts.success(t('compose.saved'));
      }
    },
  });

  useEffect(() => {
    if (!localId || !dirty) return;
    const timer = window.setTimeout(() => {
      void save.mutateAsync();
    }, 30_000);
    return () => window.clearTimeout(timer);
  }, [localId, dirty, to, cc, subject, priority, mdn, save]);

  const send = useMutation({
    mutationFn: async (force: boolean) => {
      if (!localId) throw new Error('no draft');
      setSendFailMeta(null);
      await patchDraft(localId, {
        to_addrs: parseAddrs(to),
        cc_addrs: parseAddrs(cc),
        subject,
        body_html: editor?.getHTML() ?? '',
        priority,
        request_mdn: mdn,
      });
      return sendDraft(localId, force);
    },
    onSuccess: (d) => {
      setPreSendOpen(false);
      void qc.setQueryData(['compose', localId], d);
      if (d.status === 'failed') {
        // Banner + effect toast from send_error; stay on the draft to edit.
        return;
      }
      if (d.status === 'queued' || d.status === 'sending') {
        toasts.success(t('compose.sendingUndo'), {
          label: t('compose.undo'),
          onClick: () => {
            void undoDraft(d.id).then(() => {
              toasts.success(t('compose.undone'));
              navigate(`/compose/${d.id}?mailbox=${encodeURIComponent(mailbox)}`);
            });
          },
        });
      }
      if (d.status === 'sent') {
        toasts.success(t('compose.sent'));
        navigate(`/mail/${encodeURIComponent(mailbox)}/inbox`);
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.detail.code === 'recipient_not_allowed') {
        const meta: SendErrorMeta = {
          code: 'recipient_not_allowed',
          blocked: Array.isArray(error.detail.blocked) ? (error.detail.blocked as string[]) : [],
          allowlist: Array.isArray(error.detail.allowlist) ? (error.detail.allowlist as string[]) : [],
          show_allowlist: Boolean(error.detail.show_allowlist),
        };
        setSendFailMeta(meta);
        toasts.error(formatAllowlistFailure(t, meta));
        return;
      }
      // ApiError: re-fetch draft for checks; blocking opens W4b
      void draftQuery.refetch().then((res) => {
        if (res.data?.checks.some((c) => c.blocking)) setPreSendOpen(true);
        else if (res.data?.status === 'failed') toasts.error(sendErrorMessage(t, res.data.send_error));
        else toasts.error(t('compose.sendFailed'));
      });
    },
  });

  const attach = useMutation({
    mutationFn: async (file: File) => {
      if (!localId) throw new Error('no draft');
      return uploadAttachment(localId, file);
    },
    onSuccess: (d) => void qc.setQueryData(['compose', localId], d),
  });

  const schedule = useMutation({
    mutationFn: async (when: Date) => {
      if (!localId) throw new Error('no draft');
      await patchDraft(localId, {
        to_addrs: parseAddrs(to),
        cc_addrs: parseAddrs(cc),
        subject,
        body_html: editor?.getHTML() ?? '',
        priority,
        request_mdn: mdn,
        scheduled_at: when.toISOString(),
      });
      return when;
    },
    onSuccess: (when) => {
      setScheduleOpen(false);
      void draftQuery.refetch();
      toasts.success(
        t('compose.scheduleDone', {
          when: when.toLocaleString(i18n.language?.startsWith('sk') ? 'sk-SK' : undefined, {
            dateStyle: 'short',
            timeStyle: 'short',
          }),
        }),
      );
    },
  });

  const cancelSchedule = useMutation({
    mutationFn: async () => {
      if (!localId) throw new Error('no draft');
      return patchDraft(localId, { scheduled_at: null });
    },
    onSuccess: (d) => void qc.setQueryData(['compose', localId], d),
  });

  const draft = draftQuery.data;
  const identity = identities.data?.find((i) => i.id === draft?.identity_id) ?? identities.data?.[0];
  const personName = me.data?.person?.full_name ?? '';
  const mobile = useMediaQuery(MOBILE_QUERY);

  function openPopupWindow() {
    if (!localId) return;
    if (popupCount() >= POPUP_MAX) {
      toasts.error(t('compose.popupLimit'));
      return;
    }
    const url = `/compose/${localId}?mailbox=${encodeURIComponent(mailbox)}&popup=1`;
    window.open(url, `sm-compose-${localId}`, 'popup=yes,width=720,height=640');
  }

  const shell = (children: ReactNode) =>
    isPopup ? (
      <div className="flex h-screen min-h-0 flex-col bg-bg-canvas" data-testid="compose-popup">
        {children}
      </div>
    ) : (
      <AppShell section="mail" mailbox={mailbox} unread={0} hideBottomNav={mobile}>
        {children}
      </AppShell>
    );

  if (isPopup && minimized) {
    return (
      <div className="fixed inset-x-0 bottom-0 z-50 flex justify-center p-2" data-testid="compose-minimized">
        <button
          type="button"
          className="flex h-12 w-[720px] max-w-full items-center gap-3 rounded-t-md border border-border-default bg-bg-canvas px-4 shadow-e3"
          onClick={() => setMinimized(false)}
        >
          <Maximize2 size={16} />
          <span className="type-body truncate text-text-primary">{subject || t('compose.title')}</span>
          <span className="type-caption text-text-secondary">{t('compose.restore')}</span>
        </button>
      </div>
    );
  }

  return shell(
    <>
      <div className="flex h-full min-w-0 flex-1 flex-col bg-bg-canvas" data-testid="compose-screen">
        {mobile ? (
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border-default px-2">
            <Link
              to={`/mail/${encodeURIComponent(mailbox)}/inbox`}
              className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
              aria-label={t('common.close')}
            >
              <X size={22} />
            </Link>
            <h1 className="type-heading min-w-0 flex-1 truncate text-text-primary">{t('compose.title')}</h1>
            <Button
              type="button"
              onClick={() => setPreSendOpen(true)}
              disabled={!localId || send.isPending}
              className="min-h-[44px]"
            >
              <Send size={16} /> {t('compose.send')}
            </Button>
          </header>
        ) : null}
        <header
          className={`flex h-14 shrink-0 items-center gap-1 border-b border-border-default px-3 ${mobile ? 'overflow-x-auto' : ''}`}
        >
          <button
            type="button"
            className="flex h-14 w-20 flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            <Save size={18} />
            <span className="type-micro">{t('compose.save')}</span>
          </button>
          <label className="flex h-14 w-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle">
            <Paperclip size={18} />
            <span className="type-micro">{t('compose.attach')}</span>
            <input
              type="file"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) attach.mutate(file);
              }}
            />
          </label>
          <button
            type="button"
            className="flex h-14 w-20 flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => setSignatureOpen(true)}
            disabled={!localId}
          >
            <PenLine size={18} />
            <span className="type-micro">{t('compose.signature')}</span>
          </button>
          <button
            type="button"
            className="flex h-14 w-20 flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => setResponsesOpen(true)}
          >
            <Reply size={18} />
            <span className="type-micro">{t('compose.responses')}</span>
          </button>
          <div className="flex-1" />
          {isPopup ? (
            <button
              type="button"
              className="rounded-sm p-2 text-text-secondary hover:bg-bg-subtle"
              aria-label={t('compose.minimize')}
              onClick={() => setMinimized(true)}
            >
              <Minimize2 size={18} />
            </button>
          ) : null}
          {mobile || isPopup ? null : (
            <Link
              to={`/mail/${encodeURIComponent(mailbox)}/inbox`}
              className="rounded-sm p-2 text-text-secondary hover:bg-bg-subtle"
              aria-label={t('common.close')}
            >
              <X size={18} />
            </Link>
          )}
          {isPopup ? (
            <button
              type="button"
              className="rounded-sm p-2 text-text-secondary hover:bg-bg-subtle"
              aria-label={t('common.close')}
              onClick={() => window.close()}
            >
              <X size={18} />
            </button>
          ) : null}
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            {sendFailMeta ? (
              <div className="px-4 pt-3" data-testid="compose-send-error">
                <Banner kind="danger" message={formatAllowlistFailure(t, sendFailMeta)} />
              </div>
            ) : draft?.status === 'failed' || draft?.send_error ? (
              <div className="px-4 pt-3" data-testid="compose-send-error">
                <Banner kind="danger" message={sendErrorMessage(t, draft?.send_error)} />
              </div>
            ) : null}
            <div className="grid grid-cols-[88px_1fr] items-center gap-y-2 border-b border-border-default px-4 py-3">
              <span className="type-small text-text-secondary">{t('compose.from')}</span>
              <div className="type-body text-text-primary">
                {identity ? `${identity.display_name} <${identity.email}>` : '…'}
                {personName ? (
                  <span className="type-small ml-3 text-text-secondary">
                    {t('compose.replier', { name: personName })}
                  </span>
                ) : null}
              </div>
              <span className="type-small text-text-secondary">{t('compose.to')}</span>
              <div className="flex gap-2">
                <input
                  value={to}
                  onChange={(event) => {
                    setTo(event.target.value);
                    setDirty(true);
                  }}
                  className="type-body h-9 flex-1 rounded-sm border border-border-default px-3"
                  aria-label={t('compose.to')}
                />
                <button type="button" className="type-caption text-brand-primary-600" onClick={() => setShowCc(true)}>
                  + {t('compose.cc')}
                </button>
              </div>
              {showCc ? (
                <>
                  <span className="type-small text-text-secondary">{t('compose.cc')}</span>
                  <input
                    value={cc}
                    onChange={(event) => {
                      setCc(event.target.value);
                      setDirty(true);
                    }}
                    className="type-body h-9 rounded-sm border border-border-default px-3"
                    aria-label={t('compose.cc')}
                  />
                </>
              ) : null}
              <span className="type-small text-text-secondary">{t('compose.subject')}</span>
              <input
                value={subject}
                onChange={(event) => {
                  setSubject(event.target.value);
                  setDirty(true);
                }}
                className="type-body h-9 rounded-sm border border-border-default px-3"
                aria-label={t('compose.subject')}
              />
            </div>

            <div className="flex items-center gap-1 border-b border-border-default px-2 py-1">
              <button
                type="button"
                className="rounded-sm p-2 hover:bg-bg-subtle"
                onClick={() => editor?.chain().focus().toggleBold().run()}
              >
                <Bold size={16} />
              </button>
              <button
                type="button"
                className="rounded-sm p-2 hover:bg-bg-subtle"
                onClick={() => editor?.chain().focus().toggleItalic().run()}
              >
                <Italic size={16} />
              </button>
              <button
                type="button"
                className="rounded-sm p-2 hover:bg-bg-subtle"
                onClick={() => editor?.chain().focus().toggleBulletList().run()}
              >
                <List size={16} />
              </button>
              <span className="type-caption ml-2 text-text-tertiary" title={t('common.comingSoon')}>
                <UnderlineIcon size={16} className="inline opacity-40" />
              </span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <EditorContent editor={editor} />
            </div>

            <div className="flex flex-wrap items-center gap-3 border-t border-border-default px-4 py-3">
              <div className="relative flex">
                <Button
                  type="button"
                  className="rounded-r-none"
                  onClick={() => {
                    const checks = draft?.checks ?? [];
                    if (checks.some((c) => c.blocking) || checks.length > 0) {
                      void save.mutateAsync().then(() => setPreSendOpen(true));
                    } else {
                      send.mutate(false);
                    }
                  }}
                  disabled={send.isPending || me.data?.read_only}
                >
                  <Send size={16} className="mr-2 inline" />
                  {t('compose.send')}
                </Button>
                <Button
                  type="button"
                  className="rounded-l-none border-l border-brand-primary-700 px-2"
                  aria-label={t('compose.sendMenu')}
                  aria-expanded={sendMenuOpen}
                  disabled={send.isPending || me.data?.read_only}
                  onClick={() => setSendMenuOpen((v) => !v)}
                >
                  <ChevronDown size={16} />
                </Button>
                {sendMenuOpen ? (
                  <div
                    role="menu"
                    className="absolute bottom-full left-0 z-10 mb-1 min-w-[200px] rounded-sm border border-border-default bg-bg-canvas py-1 shadow-e2"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className="type-body flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bg-subtle"
                      onClick={() => {
                        setSendMenuOpen(false);
                        setScheduleOpen(true);
                      }}
                    >
                      <Clock size={16} />
                      {t('compose.schedule')}
                    </button>
                  </div>
                ) : null}
              </div>
              {draft?.status === 'scheduled' && draft.scheduled_at ? (
                <span className="type-caption inline-flex items-center gap-2 rounded-full bg-bg-subtle px-3 py-1 text-text-secondary">
                  <Clock size={14} />
                  {t('compose.scheduleChip', {
                    when: new Date(draft.scheduled_at).toLocaleString(
                      i18n.language?.startsWith('sk') ? 'sk-SK' : undefined,
                      { dateStyle: 'short', timeStyle: 'short' },
                    ),
                  })}
                  <button
                    type="button"
                    className="text-brand-primary-600 underline"
                    onClick={() => cancelSchedule.mutate()}
                  >
                    {t('compose.scheduleCancel')}
                  </button>
                </span>
              ) : null}
              {me.data?.read_only ? (
                <span className="type-caption text-text-secondary">{t('compose.viewerBlocked')}</span>
              ) : null}
              {isPopup || mobile ? null : (
                <button
                  type="button"
                  className="type-caption ml-auto text-brand-primary-600 underline"
                  onClick={openPopupWindow}
                >
                  {t('compose.openPopup')}
                </button>
              )}
            </div>
          </div>

          <aside
            aria-label={t('compose.options')}
            className="hidden w-[320px] shrink-0 flex-col border-l border-border-default bg-bg-subtle p-4 lg:flex"
          >
            <h2 className="type-heading mb-3 text-text-primary">{t('compose.options')}</h2>
            <label className="mb-3 block type-small text-text-secondary">
              {t('compose.priority')}
              <select
                value={priority}
                onChange={(event) => {
                  setPriority(event.target.value as typeof priority);
                  setDirty(true);
                }}
                className="type-body mt-1 h-9 w-full rounded-sm border border-border-default bg-bg-canvas px-2"
              >
                <option value="low">{t('compose.priorityLow')}</option>
                <option value="normal">{t('compose.priorityNormal')}</option>
                <option value="high">{t('compose.priorityHigh')}</option>
              </select>
            </label>
            <label className="mb-3 flex items-center gap-2 type-small text-text-primary">
              <input
                type="checkbox"
                checked={mdn}
                onChange={(event) => {
                  setMdn(event.target.checked);
                  setDirty(true);
                }}
              />
              {t('compose.mdn')}
            </label>
            <div className="mt-4">
              <p className="type-label mb-2 text-text-secondary">{t('compose.attachments')}</p>
              <ul className="flex flex-col gap-1">
                {(draft?.attachments ?? []).map((a) => (
                  <li key={a.id} className="type-small text-text-primary">
                    {a.filename} ({Math.round(a.size / 1024)} kB)
                  </li>
                ))}
              </ul>
            </div>
            <p className="type-caption mt-auto pt-6 text-text-tertiary">{t('compose.aiLater')}</p>
          </aside>
        </div>
      </div>

      {preSendOpen && draft ? (
        <PreSendDialog
          checks={draft.checks}
          onEdit={() => setPreSendOpen(false)}
          onSendAnyway={() => send.mutate(true)}
          busy={send.isPending}
        />
      ) : null}
      {scheduleOpen ? (
        <ScheduleSendDialog
          onCancel={() => setScheduleOpen(false)}
          onSchedule={(when) => schedule.mutate(when)}
          busy={schedule.isPending}
        />
      ) : null}
      {responsesOpen ? (
        <ResponsesPicker
          onClose={() => setResponsesOpen(false)}
          onPick={(html) => {
            editor?.commands.insertContent(html);
            setDirty(true);
            setResponsesOpen(false);
          }}
        />
      ) : null}
      {signatureOpen && localId ? (
        <SignatureEditDialog
          initialHtml={
            draft?.signature_html_override ??
            editor?.getHTML().match(/<div data-sm-signature="1">([\s\S]*?)<\/div>/)?.[1] ??
            ''
          }
          busy={save.isPending}
          onClose={() => setSignatureOpen(false)}
          onSave={(html) => {
            void patchDraft(localId, { signature_html_override: html, include_signature: true }).then((d) => {
              void qc.setQueryData(['compose', localId], d);
              const without = (editor?.getHTML() ?? '').replace(/<div data-sm-signature="1">[\s\S]*?<\/div>/, '');
              editor?.commands.setContent(`${without}<div data-sm-signature="1">${html}</div>`);
              setDirty(true);
              setSignatureOpen(false);
              toasts.success(t('compose.signatureSaved'));
            });
          }}
        />
      ) : null}
    </>,
  );
}
