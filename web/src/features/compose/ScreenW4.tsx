import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EditorContent, useEditor } from '@tiptap/react';
import {
  ChevronDown,
  Clock,
  Download,
  FileText,
  Maximize2,
  MessageSquare,
  Minimize2,
  Paperclip,
  Save,
  Send,
  Signature,
  SquareArrowOutUpRight,
  X,
} from 'lucide-react';
import { useEffect, useState, type DragEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Avatar } from '../../components/Avatar';
import { Banner } from '../../components/Banner';
import { ConfirmDialog } from '../../components/Dialog';
import { Menu } from '../../components/Menu';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { fetchPicker, PICKER_KEY } from '../persons/personsApi';
import {
  createDraft,
  deleteAttachment,
  fetchDraft,
  listIdentities,
  patchDraft,
  sendDraft,
  uploadAttachment,
  type ComposeMode,
} from './composeApi';
import { ComposeToolbar } from './ComposeToolbar';
import { composeExtensions, signatureHtmlOf } from './composeExtensions';
import { sendErrorMessage } from './sendCopy';
import { watchSend } from './sendWatch';
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
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker, enabled: me.data?.kind === 'branch' });
  const [signerMenu, setSignerMenu] = useState<{ x: number; y: number } | null>(null);
  const [keptSigner, setKeptSigner] = useState<string | null>(null);
  const [overrideFor, setOverrideFor] = useState<{ id: string; name: string } | null>(null);
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
    extensions: composeExtensions,
    content: '',
    immediatelyRender: true,
    onUpdate: () => setDirty(true),
    editorProps: {
      attributes: {
        class: 'compose-editor type-body min-h-[280px] focus:outline-none text-text-primary',
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
    const html = d.include_signature
      ? d.body_html || '<p></p>'
      : (d.body_html || '<p></p>').replace(/<div data-sm-signature="1">[\s\S]*<\/div>\s*$/i, '');
    editor?.commands.setContent(html, { emitUpdate: false });
    setDirty(Boolean(seedTo && !draftTo));
  }

  useEffect(() => {
    if (!draftId && !localId && !bootstrap.isPending && !bootstrap.isSuccess) {
      bootstrap.mutate();
    }
  }, [draftId, localId, bootstrap]);

  // Fields are editable only once the draft is there (#56): typing during `POST /compose` was overwritten by
  // `applyDraft` when the new draft arrived (slow network / CI runner).
  const ready = bootstrap.isSuccess || draftQuery.data !== undefined;
  useEffect(() => {
    editor?.setEditable(ready, false); // no update event: it would mark the draft dirty
  }, [editor, ready]);

  useEffect(() => {
    // Do not clobber in-progress edits when a late GET/hydrate arrives (pilot #18 B7 e2e).
    if (draftQuery.data && !dirty) applyDraft(draftQuery.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- apply once per draft payload / when edits flush
  }, [draftQuery.data?.id, draftQuery.data?.updated_at, dirty]);

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

  // „Odpovedá: … ▾“ and the hint after a person switch (#65): the server re-renders the signature block for that person;
  // the editor gets the returned body, so typed text and the quote stay and only the signature changes.
  const changeSigner = useMutation({
    mutationFn: ({ personId, replace }: { personId: string; replace: boolean }) => {
      if (!localId) throw new Error('no draft');
      return patchDraft(localId, {
        signature_person_id: personId,
        replace_signature_override: replace,
        body_html: editor?.getHTML() ?? '',
      });
    },
    onSuccess: (d) => {
      setOverrideFor(null);
      void qc.setQueryData(['compose', localId], d);
      editor?.commands.setContent(d.body_html || '<p></p>', { emitUpdate: false });
    },
    onError: (error, vars) => {
      if (error instanceof ApiError && error.detail.code === 'signature_override_confirm') {
        const name = signers.find((p) => p.id === vars.personId)?.full_name ?? '';
        setOverrideFor({ id: vars.personId, name });
        return;
      }
      toasts.error(t('compose.signaturePersonFailed'));
    },
  });

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
        // Stay on the draft (banner). The shell tracker shows the error toast + „Otvoriť koncept“.
        watchSend(d, mailbox);
        return;
      }
      if (d.status === 'queued' || d.status === 'sending' || d.status === 'sent') {
        // Close compose; SendTracker keeps polling for up to 60 s (W4 and M4).
        watchSend(d, mailbox);
        navigate(`/mail/${encodeURIComponent(mailbox)}/inbox`);
      }
    },
    onError: (error) => {
      const openDraft = localId
        ? {
            label: t('compose.openDraft'),
            onClick: () => navigate(`/compose/${localId}?mailbox=${encodeURIComponent(mailbox)}`),
          }
        : undefined;
      if (
        error instanceof ApiError &&
        (error.detail.code === 'attachment_infected' || error.detail.code === 'attachment_missing')
      ) {
        setPreSendOpen(false);
        const name = typeof error.detail.filename === 'string' ? error.detail.filename : '';
        toasts.error(
          error.detail.code === 'attachment_infected'
            ? t('compose.attachmentInfectedSend', { name })
            : t('compose.attachmentMissingSend', { name }),
        );
        void draftQuery.refetch();
        return;
      }
      if (error instanceof ApiError && error.detail.code === 'recipient_not_allowed') {
        const meta: SendErrorMeta = {
          code: 'recipient_not_allowed',
          blocked: Array.isArray(error.detail.blocked) ? (error.detail.blocked as string[]) : [],
          allowlist: Array.isArray(error.detail.allowlist) ? (error.detail.allowlist as string[]) : [],
          show_allowlist: Boolean(error.detail.show_allowlist),
        };
        setSendFailMeta(meta);
        toasts.error(formatAllowlistFailure(t, meta), openDraft);
        return;
      }
      // ApiError: re-fetch draft for checks; blocking opens W4b
      void draftQuery.refetch().then((res) => {
        if (res.data?.checks.some((c) => c.blocking)) setPreSendOpen(true);
        else if (res.data?.status === 'failed') watchSend(res.data, mailbox);
        else toasts.error(t('compose.sendFailed'), openDraft);
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
  // One after another: each response carries the whole attachment list, so parallel uploads could hide a chip.
  const attachFiles = async (files: FileList | File[] | null | undefined) => {
    for (const file of Array.from(files ?? [])) {
      try {
        await attach.mutateAsync(file);
      } catch {
        // the mutation shows its own error state; continue with the next file
      }
    }
  };
  const [dragOver, setDragOver] = useState(false);
  const hasFiles = (event: DragEvent<HTMLDivElement>) => Array.from(event.dataTransfer?.types ?? []).includes('Files');

  const removeAtt = useMutation({
    mutationFn: async (id: string) => {
      if (!localId) throw new Error('no draft');
      return deleteAttachment(localId, id);
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
  // The chip shows whose signature the draft carries, never just the active person (#65).
  const personName = draft?.signature_person_name ?? me.data?.person?.full_name ?? '';
  const signers = picker.data?.persons ?? [];
  const personInitial = (personName.trim().charAt(0) || '?').toLocaleUpperCase('sk');
  const activePerson = me.data?.person ?? null;
  const signerId = draft?.signature_person_id ?? null;
  const showSignerHint =
    Boolean(draft && activePerson && signerId && activePerson.id !== signerId) &&
    keptSigner !== `${signerId}:${activePerson?.id ?? ''}` &&
    signers.some((p) => p.id === activePerson?.id);
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
      <div
        className={`relative flex h-full min-w-0 flex-1 flex-col bg-bg-canvas ${dragOver ? 'outline-dashed outline-2 -outline-offset-4 outline-brand-primary-500' : ''}`}
        data-testid="compose-screen"
        data-compose-dropzone=""
        // Dropping files on W4/M4 attaches them (Roundcube). Capture phase: before the editor and the global G7 zone.
        onDragOverCapture={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          if (!dragOver) setDragOver(true);
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
          setDragOver(false);
        }}
        onDropCapture={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          event.stopPropagation();
          setDragOver(false);
          void attachFiles(event.dataTransfer.files);
        }}
      >
        {dragOver ? (
          <p
            role="status"
            className="type-body-strong pointer-events-none absolute inset-x-0 top-1/2 z-10 mx-auto w-fit rounded-md bg-bg-canvas px-4 py-2 text-brand-primary-700 shadow-e2"
          >
            {t('compose.dropHere')}
          </p>
        ) : null}
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
          className={`flex h-14 shrink-0 items-center gap-1 border-border-default px-3 ${mobile ? 'order-last overflow-x-auto border-t' : 'border-b'}`}
        >
          {mobile ? null : <div className="flex-1" />}
          <button
            type="button"
            className="flex h-14 w-[72px] flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            <Save size={18} />
            <span className="type-micro">{t('compose.save')}</span>
          </button>
          <label className="flex h-14 w-[72px] cursor-pointer flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle">
            <Paperclip size={18} />
            <span className="type-micro">{t('compose.attach')}</span>
            <input
              type="file"
              className="sr-only"
              multiple
              onChange={(event) => {
                void attachFiles(event.target.files);
                event.target.value = '';
              }}
            />
          </label>
          <button
            type="button"
            className="flex h-14 w-[72px] flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => setSignatureOpen(true)}
            disabled={!localId}
          >
            <Signature size={18} />
            <span className="type-micro">{t('compose.signature')}</span>
          </button>
          <button
            type="button"
            className="flex h-14 w-[72px] flex-col items-center justify-center gap-1 rounded-sm text-text-primary hover:bg-bg-subtle"
            onClick={() => setResponsesOpen(true)}
          >
            <MessageSquare size={18} />
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
            {showSignerHint && activePerson ? (
              <div className="px-4 pt-3" data-testid="compose-signer-hint">
                <Banner
                  kind="warning"
                  message={t('compose.signaturePersonHint', {
                    draftPerson: personName,
                    active: activePerson.full_name,
                  })}
                  action={{
                    label: t('compose.signaturePersonChange'),
                    onClick: () => changeSigner.mutate({ personId: activePerson.id, replace: false }),
                    disabled: changeSigner.isPending,
                  }}
                  secondaryAction={{
                    label: t('compose.signaturePersonKeep'),
                    onClick: () => setKeptSigner(`${signerId}:${activePerson.id}`),
                  }}
                />
              </div>
            ) : null}
            {sendFailMeta ? (
              <div className="px-4 pt-3" data-testid="compose-send-error">
                <Banner kind="danger" message={formatAllowlistFailure(t, sendFailMeta)} />
              </div>
            ) : draft?.status === 'failed' ? (
              <div className="px-4 pt-3" data-testid="compose-send-error">
                <Banner kind="danger" message={sendErrorMessage(t, draft?.send_error)} />
              </div>
            ) : null}
            <div
              className={
                mobile
                  ? 'grid grid-cols-[72px_1fr] items-stretch px-4 [&>*]:flex [&>*]:min-h-11 [&>*]:items-center [&>*]:border-b [&>*]:border-border-default'
                  : 'grid grid-cols-[minmax(72px,172px)_1fr] items-center gap-y-2.5 px-6 pb-3 pt-4'
              }
            >
              <span className="type-body text-text-primary">{t('compose.from')}</span>
              <div
                className={`type-small flex min-h-9 min-w-0 flex-wrap items-center gap-x-3 text-text-primary ${
                  mobile ? 'py-1.5' : 'rounded-sm border border-border-default px-2 py-1.5'
                }`}
              >
                <span className="truncate">{identity ? `${identity.display_name} <${identity.email}>` : '…'}</span>
              </div>
              {personName ? (
                <>
                  <span className="type-body text-text-primary">{t('compose.replierLabel')}</span>
                  <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                    {personName && signers.length > 1 && !me.data?.read_only ? (
                      <button
                        type="button"
                        aria-haspopup="menu"
                        aria-label={`${t('compose.replier', { name: personName })} – ${t('compose.replierMenu')}`}
                        data-testid="compose-signer"
                        onClick={(event) => {
                          const box = event.currentTarget.getBoundingClientRect();
                          setSignerMenu({ x: box.left, y: box.bottom + 4 });
                        }}
                        className="type-label inline-flex items-center gap-1.5 rounded-full border border-brand-primary-600 bg-brand-primary-50 py-0.5 pl-1 pr-2.5 text-brand-primary-700 hover:bg-brand-primary-100"
                      >
                        <Avatar initials={personInitial} seed={signerId ?? ''} size={20} />
                        {t('compose.replier', { name: personName })}
                        <ChevronDown size={12} aria-hidden="true" />
                      </button>
                    ) : personName ? (
                      <span
                        data-testid="compose-signer"
                        className="type-caption inline-flex items-center rounded-full bg-brand-primary-50 px-2.5 py-0.5 text-brand-primary-700"
                      >
                        {t('compose.replier', { name: personName })}
                      </span>
                    ) : null}
                    {me.data?.kind === 'branch' ? (
                      <span className="type-caption text-text-secondary">{t('compose.replierBranchHint')}</span>
                    ) : null}
                  </div>
                </>
              ) : null}
              <span className="type-body text-text-primary">{t('compose.to')}</span>
              <div className="flex gap-2">
                <input
                  value={to}
                  onChange={(event) => {
                    setTo(event.target.value);
                    setDirty(true);
                  }}
                  className={
                    mobile
                      ? 'type-body h-11 min-w-0 flex-1 bg-transparent focus:outline-none'
                      : 'type-body h-9 flex-1 rounded-sm border border-border-default px-3'
                  }
                  aria-label={t('compose.to')}
                  disabled={!ready}
                />
                <button
                  type="button"
                  className="type-small h-9 shrink-0 rounded-sm border border-border-default px-3 text-text-primary hover:bg-bg-subtle"
                  onClick={() => setShowCc(true)}
                >
                  + {t('compose.cc')}
                </button>
              </div>
              {showCc ? (
                <>
                  <span className="type-body text-text-primary">{t('compose.cc')}</span>
                  <input
                    value={cc}
                    onChange={(event) => {
                      setCc(event.target.value);
                      setDirty(true);
                    }}
                    className={
                      mobile
                        ? 'type-body h-11 bg-transparent focus:outline-none'
                        : 'type-body h-9 rounded-sm border border-border-default px-3'
                    }
                    aria-label={t('compose.cc')}
                    disabled={!ready}
                  />
                </>
              ) : null}
              <span className="type-body text-text-primary">{t('compose.subject')}</span>
              <input
                value={subject}
                onChange={(event) => {
                  setSubject(event.target.value);
                  setDirty(true);
                }}
                className={
                  mobile
                    ? 'type-body h-11 bg-transparent focus:outline-none'
                    : 'type-body h-9 rounded-sm border border-border-default px-3'
                }
                aria-label={t('compose.subject')}
                disabled={!ready}
              />
            </div>

            <div
              className={`flex min-h-0 flex-1 flex-col overflow-hidden ${
                mobile ? '' : 'mx-6 mb-3 rounded-md border border-border-default'
              }`}
            >
              <ComposeToolbar
                editor={editor}
                onInlineImage={(file) => {
                  if (!localId || !editor) return;
                  const known = new Set((draftQuery.data?.attachments ?? []).map((item) => item.id));
                  void uploadAttachment(localId, file, true)
                    .then((next) => {
                      void qc.setQueryData(['compose', localId], next);
                      const added = next.attachments.find((item) => !known.has(item.id) && item.content_id);
                      if (!added?.content_id) return;
                      editor
                        .chain()
                        .focus()
                        .setImage({ src: `cid:${added.content_id}`, alt: file.name })
                        .run();
                      setDirty(true);
                    })
                    .catch((error: unknown) => {
                      if (error instanceof ApiError && error.detail.code === 'image_type') {
                        toasts.error(t('compose.inlineImageType'));
                      }
                    });
                }}
              />

              <div className="type-body-lg min-h-0 flex-1 overflow-y-auto">
                <EditorContent editor={editor} />
              </div>
            </div>

            <div
              className={`flex flex-wrap items-center gap-3 ${mobile ? 'border-t border-border-default px-4 py-2' : 'px-6 pb-3'}`}
            >
              <div className="relative flex">
                <Button
                  type="button"
                  className="rounded-r-none"
                  onClick={() => {
                    const infected = (draft?.attachments ?? []).find(
                      (item) => !item.is_inline && item.av_status === 'infected',
                    );
                    if (infected) {
                      toasts.error(t('compose.attachmentInfectedSend', { name: infected.filename }));
                      return;
                    }
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
                  className="type-label ml-auto inline-flex items-center gap-1.5 text-brand-primary-600 hover:underline"
                  onClick={openPopupWindow}
                >
                  <SquareArrowOutUpRight size={16} aria-hidden="true" />
                  {t('compose.openPopup')}
                </button>
              )}
            </div>
          </div>

          <aside
            aria-label={t('compose.options')}
            className="hidden w-[380px] shrink-0 flex-col overflow-y-auto border-l border-border-default bg-bg-canvas px-4 lg:flex"
          >
            <div className="mb-4 flex h-[var(--size-tab)] shrink-0 items-end gap-6 border-b border-border-default">
              <h2 className="type-label -mb-px border-b-2 border-brand-primary-600 pb-2 text-brand-primary-700">
                {t('compose.options')}
              </h2>
            </div>
            <label className="mb-3 flex cursor-pointer flex-col items-center gap-3 rounded-md border border-dashed border-border-strong px-4 py-5 text-center">
              <span className="type-small text-text-secondary">{t('compose.maxSize')}</span>
              <span className="type-body-strong inline-flex h-8 items-center gap-2 rounded-sm border border-border-strong bg-bg-canvas px-3 text-text-primary hover:bg-bg-muted">
                <Paperclip size={16} aria-hidden="true" />
                {t('compose.attachFile')}
              </span>
              <Download size={24} aria-hidden="true" className="text-text-tertiary" />
              <input
                type="file"
                className="sr-only"
                multiple
                onChange={(event) => {
                  void attachFiles(event.target.files);
                  event.target.value = '';
                }}
              />
            </label>
            {(draft?.attachments ?? []).some((a) => !a.is_inline) ? (
              <ul aria-label={t('compose.attachments')} className="mb-3 flex flex-col gap-1.5">
                {(draft?.attachments ?? [])
                  .filter((a) => !a.is_inline)
                  .map((a) => {
                    const pending = a.av_status === 'pending';
                    const unscanned = a.av_status === 'skipped' || a.av_status === 'error';
                    const infected = a.av_status === 'infected';
                    return (
                      <li
                        key={a.id}
                        className="type-small flex flex-col justify-center gap-0.5 rounded-sm border border-border-default px-2.5 py-1 text-text-primary"
                      >
                        <span className="flex h-8 items-center gap-2">
                          <FileText size={16} aria-hidden="true" className="shrink-0 text-danger-600" />
                          <span className="min-w-0 flex-1 truncate">{a.filename}</span>
                          {unscanned ? (
                            <span className="type-caption shrink-0 text-text-tertiary">
                              ({t('mail.attachmentUnscanned')})
                            </span>
                          ) : null}
                          {infected ? (
                            <span className="type-caption shrink-0 text-danger-600">
                              ({t('compose.attachmentInfectedChip')})
                            </span>
                          ) : null}
                          <span className="type-caption shrink-0 text-text-secondary">
                            {Math.round(a.size / 1024)} kB
                          </span>
                          <button
                            type="button"
                            className="shrink-0 rounded-xs text-text-secondary hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500"
                            aria-label={`${t('compose.removeAttachment')} ${a.filename}`}
                            onClick={() => removeAtt.mutate(a.id)}
                          >
                            <X size={14} aria-hidden="true" />
                          </button>
                        </span>
                        {pending ? (
                          <span className="type-caption pb-1 text-text-tertiary">{t('compose.attachmentPending')}</span>
                        ) : null}
                      </li>
                    );
                  })}
              </ul>
            ) : null}
            <div className="flex flex-col gap-3 border-t border-border-default pt-4">
              <div className="flex items-center justify-between gap-3">
                <span id="compose-mdn-label" className="type-small text-text-primary">
                  {t('compose.mdn')}
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={mdn}
                  aria-labelledby="compose-mdn-label"
                  onClick={() => {
                    setMdn(!mdn);
                    setDirty(true);
                  }}
                  className={`relative h-[18px] w-8 shrink-0 rounded-full transition-colors duration-[var(--motion-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500 ${
                    mdn ? 'bg-brand-primary-600' : 'bg-border-strong'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 size-3.5 rounded-full bg-bg-canvas transition-[left] duration-[var(--motion-hover)] ${
                      mdn ? 'left-4' : 'left-0.5'
                    }`}
                  />
                </button>
              </div>
              <label className="flex items-center justify-between gap-3">
                <span className="type-small text-text-primary">{t('compose.priority')}</span>
                <span className="relative w-[180px]">
                  <select
                    value={priority}
                    onChange={(event) => {
                      setPriority(event.target.value as typeof priority);
                      setDirty(true);
                    }}
                    className="type-body h-9 w-full appearance-none rounded-sm border border-border-default bg-bg-canvas pl-3 pr-8 text-text-primary"
                  >
                    <option value="low">{t('compose.priorityLow')}</option>
                    <option value="normal">{t('compose.priorityNormal')}</option>
                    <option value="high">{t('compose.priorityHigh')}</option>
                  </select>
                  <ChevronDown
                    size={16}
                    aria-hidden="true"
                    className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-secondary"
                  />
                </span>
              </label>
            </div>
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
      {signerMenu ? (
        <Menu
          label={t('compose.replierMenu')}
          at={signerMenu}
          width={240}
          onClose={() => setSignerMenu(null)}
          entries={signers.map((p) => ({
            kind: 'item' as const,
            id: p.id,
            label: p.full_name,
            hint: p.function ?? undefined,
            checked: p.id === (signerId ?? activePerson?.id),
            onSelect: () => {
              setSignerMenu(null);
              if (p.id !== signerId) changeSigner.mutate({ personId: p.id, replace: false });
            },
          }))}
        />
      ) : null}
      {overrideFor ? (
        <ConfirmDialog
          title={t('compose.signatureOverrideTitle')}
          body={t('compose.signatureOverrideBody', { name: overrideFor.name })}
          confirmLabel={t('compose.signatureOverrideConfirm')}
          busy={changeSigner.isPending}
          onConfirm={() => changeSigner.mutate({ personId: overrideFor.id, replace: true })}
          onClose={() => setOverrideFor(null)}
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
          initialHtml={draft?.signature_html_override || signatureHtmlOf(editor)}
          busy={save.isPending}
          onClose={() => setSignatureOpen(false)}
          onSave={(html) => {
            void patchDraft(localId, {
              signature_html_override: html,
              include_signature: true,
              body_html: editor?.getHTML() ?? '',
              to_addrs: parseAddrs(to),
              cc_addrs: parseAddrs(cc),
              subject,
            }).then((d) => {
              void qc.setQueryData(['compose', localId], d);
              editor?.commands.setContent(d.body_html || '<p></p>', { emitUpdate: false });
              setDirty(false);
              setSignatureOpen(false);
              toasts.success(t('compose.signatureSaved'));
            });
          }}
        />
      ) : null}
    </>,
  );
}
