import { api, apiForm } from '../../lib/api';

/** Phase 4a supplier documents (W6u, W6e). Read-only: nothing is written to Money. */
export type SupplierDocument = {
  id: string;
  source: 'mail' | 'upload';
  kind: 'invoice' | 'delivery_note' | 'unknown';
  status: 'extracting' | 'needs_review' | 'missing_data' | 'duplicate' | 'unreadable' | 'failed' | 'ignored';
  filename: string;
  branch_id: string | null;
  branch_name: string | null;
  centre_code: string | null;
  warehouse_code: string | null;
  supplier_name: string | null;
  supplier_ico: string | null;
  supplier_money_id: string | null;
  doc_number: string | null;
  doc_date: string | null;
  currency: string | null;
  total: string | null;
  lines: number;
  blocking: number;
  warnings: number;
  error: string | null;
  created_at: string;
};

export type DocumentPage = { items: SupplierDocument[]; total: number };
export type DocumentFilter = 'open' | 'all' | 'duplicate' | 'ignored';

export const documentsKey = (status: DocumentFilter, q: string, page: number) =>
  ['purchasing', 'documents', status, q, page] as const;

export const fetchDocuments = (status: DocumentFilter, q: string, page: number) => {
  const params = new URLSearchParams({ status, page: String(page) });
  if (q.trim()) params.set('q', q.trim());
  return api<DocumentPage>('GET', `/api/purchasing/documents?${params.toString()}`);
};

export const uploadDocument = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return apiForm<SupplierDocument>('POST', '/api/purchasing/documents', form, { global: false });
};
