import { api } from '../../lib/api';

export type SuggestionCheck = { id: string; level: 'ok' | 'warning' | 'blocking'; params: Record<string, unknown> };

export type Suggestion = {
  id: string;
  type: string;
  status: string;
  to: string[];
  subject: string;
  body: string;
  language: string | null;
  rationale: string | null;
  confidence: number | null;
  checks: SuggestionCheck[];
  blocked: boolean;
  /** #139 C: prefilled Prehlásenie o zhode (type `conformity_declaration`) */
  conformity?: {
    customer: string;
    document_ref: string;
    items: { nazov: string; kod?: string; norma?: string; poznamka?: string }[];
  } | null;
};

export type RejectReason = 'wrong_category' | 'wrong_data' | 'tone' | 'not_needed';
export const REJECT_REASONS: readonly RejectReason[] = ['wrong_category', 'wrong_data', 'tone', 'not_needed'];

export const suggestionsKey = (mailbox: string, messageId: string) =>
  ['mail', 'suggestions', mailbox, messageId] as const;

export const fetchSuggestions = (mailbox: string, messageId: string) =>
  api<Suggestion[]>(
    'GET',
    `/api/mail/mailboxes/${encodeURIComponent(mailbox)}/messages/${encodeURIComponent(messageId)}/suggestions`,
    undefined,
    { global: false },
  );

export const approveSuggestion = (id: string, body: string | null) =>
  api<{ suggestion_id: string; draft_id: string; edited: boolean }>('POST', `/api/suggestions/${id}/approve`, {
    body,
  });

export const rejectSuggestion = (id: string, reasons: RejectReason[], note: string | null) =>
  api<{ status: string }>('POST', `/api/suggestions/${id}/reject`, { reasons, note });
