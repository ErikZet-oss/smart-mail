import { api } from '../../lib/api';

export type SuggestionCheck = {
  id: string;
  /** requires_ack (#215): a person must tick a confirmation before the primary action is allowed */
  level: 'ok' | 'warning' | 'requires_ack' | 'blocking';
  params: Record<string, unknown>;
};

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
  /** Phase 3d: invoice_attach — Money invoices whose original PDF goes with the draft */
  invoices?:
    | {
        id: string;
        kind: 'invoice' | 'proforma' | 'delivery_note';
        number: string;
        due_on: string | null;
        total: string;
        remaining: string;
        /** #217 pick mode */
        issued_on?: string | null;
        order?: string | null;
        own?: boolean;
        exact?: boolean;
        selected?: boolean;
        owner_money_id?: string | null;
        owner_name?: string | null;
        /** #222 delivery notes: the branch of the note and whether it has the print report */
        branch?: string | null;
        report_ok?: boolean;
      }[]
    | null;
  company_name?: string | null;
  /** #217: the person picks which invoices (up to 5, found by the order number) go with the draft */
  pick?: boolean;
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

export const approveSuggestion = (
  id: string,
  body: string | null,
  acknowledged: string[] = [],
  selected: string[] | null = null,
) =>
  api<{ suggestion_id: string; draft_id: string; edited: boolean }>('POST', `/api/suggestions/${id}/approve`, {
    body,
    ...(acknowledged.length ? { acknowledged_checks: acknowledged } : {}),
    ...(selected ? { selected } : {}),
  });

export const rejectSuggestion = (id: string, reasons: RejectReason[], note: string | null) =>
  api<{ status: string }>('POST', `/api/suggestions/${id}/reject`, { reasons, note });
