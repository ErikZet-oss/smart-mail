import { api } from '../../lib/api';

export type ComposeMode = 'new' | 'reply' | 'reply_all' | 'forward';

export type Addr = { name?: string | null; email: string };

export type ComposeAttachment = {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  av_status: string;
  is_inline?: boolean;
  content_id?: string | null;
};

export type ComposeCheck = { code: string; blocking: boolean; message: string };

export type ComposeDraft = {
  id: string;
  mailbox_id: string;
  mode: ComposeMode;
  identity_id: string | null;
  to_addrs: Addr[];
  cc_addrs: Addr[];
  bcc_addrs: Addr[];
  subject: string;
  body_html: string;
  body_text: string;
  include_signature: boolean;
  signature_html_override: string | null;
  signature_person_id: string | null;
  priority: 'low' | 'normal' | 'high';
  request_mdn: boolean;
  request_dsn: boolean;
  save_sent: boolean;
  status: string;
  scheduled_at: string | null;
  undo_until: string | null;
  send_error: string | null;
  /** Structured send failure (pilot #18 B7) — prefer over parsing send_error. */
  send_error_meta?: {
    code: string;
    blocked?: string[];
    allowlist?: string[];
    show_allowlist?: boolean;
  } | null;
  attachments: ComposeAttachment[];
  checks: ComposeCheck[];
  updated_at: string;
  /** Present after SMTP once the Sent folder sync stored the message (issue #23). */
  sent_message_id?: string | null;
  sent_thread_id?: string | null;
  sent_folder_ref?: string | null;
};

export type Identity = {
  id: string;
  display_name: string;
  email: string;
  organization: string | null;
  is_default: boolean;
};

export type CannedResponse = {
  id: string;
  name: string;
  language: string;
  body_html: string;
  shared: boolean;
  shortcut: string | null;
};

const base = (mailbox: string) => `/api/mail/mailboxes/${encodeURIComponent(mailbox)}`;

export const createDraft = (mailbox: string, body: { mode: ComposeMode; message_id?: string }) =>
  api<ComposeDraft>('POST', `${base(mailbox)}/compose`, body);

export const fetchDraft = (draftId: string) => api<ComposeDraft>('GET', `/api/mail/compose/${draftId}`);

export const patchDraft = (
  draftId: string,
  body: Partial<{
    identity_id: string;
    to_addrs: Addr[];
    cc_addrs: Addr[];
    bcc_addrs: Addr[];
    subject: string;
    body_html: string;
    include_signature: boolean;
    signature_html_override: string | null;
    priority: ComposeDraft['priority'];
    request_mdn: boolean;
    request_dsn: boolean;
    save_sent: boolean;
    scheduled_at: string | null;
  }>,
) => api<ComposeDraft>('PATCH', `/api/mail/compose/${draftId}`, body);

export const sendDraft = (draftId: string, force = false) =>
  api<ComposeDraft>('POST', `/api/mail/compose/${draftId}/send`, { force });

export const undoDraft = (draftId: string) => api<ComposeDraft>('POST', `/api/mail/compose/${draftId}/undo`);

export const deleteDraft = (draftId: string) => api<{ ok: boolean }>('DELETE', `/api/mail/compose/${draftId}`);

export const listIdentities = (mailbox: string) => api<Identity[]>('GET', `${base(mailbox)}/identities`);

export const listResponses = () => api<CannedResponse[]>('GET', '/api/mail/responses');

export async function uploadAttachment(draftId: string, file: File, inline = false): Promise<ComposeDraft> {
  const form = new FormData();
  form.append('file', file);
  if (inline) form.append('inline', 'true');
  const csrf = document.cookie
    .split('; ')
    .find((c) => c.startsWith('sm_csrf='))
    ?.split('=')[1];
  const response = await fetch(`/api/mail/compose/${draftId}/attachments`, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
    headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : undefined,
  });
  if (!response.ok) throw new Error(`upload ${response.status}`);
  return (await response.json()) as ComposeDraft;
}
