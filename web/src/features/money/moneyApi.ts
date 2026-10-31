import { api } from '../../lib/api';

/** Phase 3c Zákazník panel (W3b / M10). Money amounts arrive as strings (Decimal, never a float). */
export type CompanyBrief = {
  money_id: string;
  name: string;
  code: string | null;
  ico: string | null;
  dic: string | null;
  icdph: string | null;
  email: string | null;
  discount_pct: string | null;
  due_days: number | null;
};
export type MatchMethod = 'confirmed' | 'person' | 'company_email' | 'ico' | 'domain';
export type CustomerMatch = {
  email: string | null;
  method: MatchMethod | null;
  confidence: number;
  needs_confirmation: boolean;
  company: CompanyBrief | null;
  candidates: CompanyBrief[];
};
export type Invoice = {
  id: string;
  kind: 'invoice' | 'proforma';
  number: string;
  due_on: string | null;
  issued_on: string | null;
  total: string;
  remaining: string;
};
export type Order = { id: string; number: string; issued_on: string | null; reference: string | null; total: string };
export type Delivery = {
  id: string;
  number: string;
  issued_on: string | null;
  transport: string | null;
  reference: string | null;
  total: string;
};
export type Activity = { id: string; description: string | null; started_at: string | null };
export type Part<T> = { error: string | null; items: T[] };
export type CompanyCard = {
  company: CompanyBrief;
  receivables: {
    error: string | null;
    open_count: number;
    open_total: string;
    overdue_count: number;
    overdue_total: string;
    oldest_overdue_days: number | null;
    mixed_currency: boolean;
    items: Invoice[];
  };
  orders: Part<Order>;
  deliveries: Part<Delivery>;
  activities: Part<Activity>;
  persons: {
    money_id: string;
    name: string | null;
    function: string | null;
    email: string | null;
    phone: string | null;
  }[];
};

export const customerKey = (messageId: string) => ['money', 'customer', messageId] as const;
export const cardKey = (moneyId: string) => ['money', 'card', moneyId] as const;
export const fetchCustomer = (messageId: string) =>
  api<CustomerMatch>('GET', `/api/money/messages/${encodeURIComponent(messageId)}/customer`);
export const fetchCard = (moneyId: string) =>
  api<CompanyCard>('GET', `/api/money/companies/${encodeURIComponent(moneyId)}/card`);
export const searchCompanies = (q: string) =>
  api<CompanyBrief[]>('GET', `/api/money/companies/search?q=${encodeURIComponent(q)}`);
export const linkEmail = (email: string, companyMoneyId: string) =>
  api<CustomerMatch>('POST', '/api/money/links', { email, company_money_id: companyMoneyId });
export const createInvoiceDraft = (messageId: string, number: string) =>
  api<{ draft_id: string }>('POST', `/api/money/messages/${encodeURIComponent(messageId)}/invoice-draft`, { number });
export type ReminderTone = 'polite' | 'firm';
export type Debtor = {
  company: CompanyBrief;
  contact: string | null;
  overdue_total: string;
  invoice_count: number;
  oldest_days: number;
  last_reminder_at: string | null;
  invoices: Invoice[];
};
export type ReminderResult = {
  company_money_id: string;
  draft_id: string | null;
  error: string | null;
  number?: string | null;
};
export type ReminderHistoryRow = {
  at: string;
  company_money_id: string;
  company_name: string | null;
  draft_id: string | null;
  draft_status: string | null;
  tone: string | null;
  invoices: string[];
};
export const debtorsKey = ['money', 'reminders'] as const;
export const reminderHistoryKey = ['money', 'reminders', 'history'] as const;
export const fetchDebtors = () => api<Debtor[]>('GET', '/api/money/reminders');
export const fetchReminderHistory = () => api<ReminderHistoryRow[]>('GET', '/api/money/reminders/history');
export const prepareReminders = (companyMoneyIds: string[], tone: ReminderTone) =>
  api<ReminderResult[]>('POST', '/api/money/reminders/drafts', { company_money_ids: companyMoneyIds, tone });
export const unlinkEmail = (email: string) =>
  api<{ deleted: boolean }>('DELETE', `/api/money/links?email=${encodeURIComponent(email)}`);

/** „1 234,50 €“ from a Decimal string (sk-SK); currency of the agenda (EUR). */
export function money(value: string): string {
  const [whole = '0', frac = ''] = value.replace('-', '').split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
  const cents = (frac + '00').slice(0, 2);
  return `${value.startsWith('-') ? '−' : ''}${grouped},${cents}\u00a0€`;
}

export function day(value: string | null): string {
  if (!value) return '–';
  const [y, m, d] = value.slice(0, 10).split('-');
  return `${Number(d)}. ${Number(m)}. ${y}`;
}
