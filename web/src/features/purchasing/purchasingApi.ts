import { api, apiForm } from '../../lib/api';

/** Phase 4a supplier documents (W6u, W6e). Read-only: nothing is written to Money. */
export type SupplierDocument = {
  id: string;
  source: 'mail' | 'upload';
  kind: 'invoice' | 'delivery_note' | 'order_confirmation' | 'other' | 'unknown';
  status:
    | 'extracting'
    | 'needs_review'
    | 'missing_data'
    | 'duplicate'
    | 'unreadable'
    | 'failed'
    | 'ignored'
    // 4c (#247, D33): the received delivery note written to Money as a koncept
    | 'creating'
    | 'created'
    | 'write_failed'
    | 'unknown';
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
  /** 4c: number of the koncept in Money (W6e „Koncept“ chip). */
  money_number?: string | null;
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

/** Phase 4b — W6h detail with item matching (read-only; „Vytvoriť v Money“ comes with 4c). */
export type Check = { id: string; level: 'blocking' | 'warning' | 'info'; params: Record<string, unknown> };
/** #233: `main` = a main card with variants (never receivable), `variant` = shown in italics under its main card. */
export type ArticleKind = 'article' | 'main' | 'variant';
export type ArticleSnap = {
  code: string | null;
  catalog: string | null;
  name: string;
  ean: string | null;
  unit: string | null;
  kind?: ArticleKind;
};
export type Candidate = {
  article_id: string;
  code: string | null;
  catalog: string | null;
  name: string;
  unit: string | null;
  kind?: ArticleKind;
};
export type DocLine = {
  line_no: number;
  supplier_code: string | null;
  ean: string | null;
  name: string;
  qty: string | null;
  unit: string | null;
  unit_price: string | null;
  vat_rate: string | null;
  line_total: string | null;
  is_fee: boolean;
  line_status: 'matched' | 'unmatched' | 'non_stock' | 'needs_review';
  article_id: string | null;
  match_method: string | null;
  unit_factor: string | null;
  warehouse_id: string | null;
  warehouse_code: string | null;
  candidates: Candidate[];
  article: ArticleSnap | null;
  qty_our: string | null;
  price_our: string | null;
  /** D32 (#239): an unfinished „Založiť artikel v Money“ (partial = main card created, variant not). */
  new_article?: NewArticleState | null;
};
export type CreatedCard = { id: string; katalog: string; nazev: string; parent_id: string | null; unit: string | null };
export type NewArticleState = {
  status: 'partial' | 'failed' | 'in_progress';
  main: CreatedCard | null;
  error: string | null;
};
export type Warehouse = { id: string; code: string; name: string };
export type DocumentDetail = SupplierDocument & {
  branch_options?: { id: string; name: string }[];
  delivery_note_number: string | null;
  order_reference: string | null;
  vat_recap: { rate: string; base: string; vat: string | null }[];
  fees: { name: string; amount: string | null }[];
  extract_method: string | null;
  checks: Check[];
  message_id: string | null;
  version: number;
  money_available: boolean;
  supplier: { name: string; ico: string | null; dic: string | null; icdph: string | null } | null;
  series: string | null;
  template: Record<string, unknown>;
  warehouses: Warehouse[];
  /** D32: Settings 14 switch on + role warehouse / accounting / admin. */
  can_create_article?: boolean;
  /** D33 (#247): Settings 14 „Zápis dodacích listov do Money (koncept)“ on + role warehouse / accounting / admin. */
  can_write?: boolean;
  write?: WriteState | null;
  items: DocLine[];
};
export type Article = ArticleSnap & { id: string; inactive: boolean };
/** 4c state of the Money write (D33): the note is a koncept that a person finishes in Money. */
export type Mismatch = { field: string; line?: number; expected?: string; got?: string };
export type WriteState = {
  state: 'creating' | 'created' | 'write_failed' | 'unknown';
  number: string | null;
  money_id: string | null;
  mismatches: Mismatch[];
  reconciled: boolean;
  error: string | null;
  written_at: string | null;
};

/** „Vytvoriť v Money“ after the confirm dialog — the click is the approval; nothing is retried automatically. */
export const createInMoney = (id: string, version: number) =>
  api<DocumentDetail>('POST', `/api/purchasing/documents/${id}/create`, { version }, { global: false });

/** Pilot 2026-11-24: the koncept was deleted in Money — the backend checks it is gone, then the document is back
 * in review with a new SMID. */
export const reopenAfterMoneyDelete = (id: string, version: number) =>
  api<DocumentDetail>('POST', `/api/purchasing/documents/${id}/reopen`, { version }, { global: false });

export const documentKey = (id: string) => ['purchasing', 'document', id] as const;
export const fetchDocument = (id: string) => api<DocumentDetail>('GET', `/api/purchasing/documents/${id}`);
/** UX_SPEC BranchChip ▾ (pilot 2026-11-23): assign the document to a branch the person may act for. */
export const setDocumentBranch = (id: string, branchId: string, version: number) =>
  api<DocumentDetail>('PUT', `/api/purchasing/documents/${id}/branch`, { branch_id: branchId, version });
export const rematch = (id: string) =>
  api<DocumentDetail>('POST', `/api/purchasing/documents/${id}/match`, {}, { global: false });
export const confirmLine = (
  id: string,
  lineNo: number,
  body: { article_id: string; unit_factor: string; learn: boolean; warehouse_id: string | null; version: number },
) => api<DocumentDetail>('POST', `/api/purchasing/documents/${id}/lines/${lineNo}/article`, body, { global: false });
export const nonStockLine = (id: string, lineNo: number, version: number) =>
  api<DocumentDetail>(
    'POST',
    `/api/purchasing/documents/${id}/lines/${lineNo}/non-stock`,
    { version },
    { global: false },
  );
/** D32 (#239) „Založiť artikel v Money“ — the click is the approval; nothing is retried automatically. */
export type NewArticleMode = 'main' | 'variant' | 'main_and_variant';
export type NewArticleBody = {
  mode: NewArticleMode;
  main?: { katalog: string; nazev: string };
  parent_id?: string;
  variant?: { katalog: string; nazev: string };
  version: number;
};
export type NewArticleResult = {
  status: 'done' | 'partial';
  main: CreatedCard | null;
  variant: CreatedCard | null;
  error: string | null;
  article_id: string | null;
  document: DocumentDetail;
};
export type CatalogFree = { free: boolean; article: { katalog: string; nazev: string } | null };
export type CatalogProposal = { katalog: string | null; size: number | null; main_catalog: string | null };

export const createArticle = (id: string, lineNo: number, body: NewArticleBody) =>
  api<NewArticleResult>('POST', `/api/purchasing/documents/${id}/lines/${lineNo}/new-article`, body, {
    global: false,
  });
export const catalogFree = (katalog: string) =>
  api<CatalogFree>('GET', `/api/purchasing/articles/catalog-free?katalog=${encodeURIComponent(katalog)}`, undefined, {
    global: false,
  });
export const catalogProposal = (p: { parentId?: string; mainCatalog?: string; size: string }) => {
  const q = new URLSearchParams({ size: p.size });
  if (p.parentId) q.set('parent_id', p.parentId);
  if (p.mainCatalog) q.set('main_catalog', p.mainCatalog);
  return api<CatalogProposal>('GET', `/api/purchasing/catalog-proposal?${q.toString()}`, undefined, {
    global: false,
  });
};

/** W6h Katalóg (Figma 264:91756): stock of one article in one warehouse — information only (D18). */
export type StockRow = {
  warehouse_id: string;
  code: string | null;
  name: string | null;
  qty: string;
  reserved: string;
  ordered: string;
  expected: string;
  available: string;
  unit_price: string | null;
};
export type CatalogRow = Article & {
  parent_id: string | null;
  plu: string | null;
  last_price: string | null;
  eshop: boolean;
  stocks: StockRow[];
};
export const fetchCatalog = (q: string) =>
  api<CatalogRow[]>('GET', `/api/purchasing/catalog?q=${encodeURIComponent(q)}`, undefined, { global: false });

export const searchArticles = (q: string) =>
  api<Article[]>('GET', `/api/purchasing/articles?q=${encodeURIComponent(q)}`, undefined, { global: false });

/** Money number formats (DOCUMENTS_SPEC §2.4): `5 000,0000`, `0,0612`, thousands with a space. */
export function moneyNum(value: string | null, decimals: number): string {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value)) return '–';
  const neg = value.startsWith('-');
  const [whole0 = '0', frac0 = ''] = value.replace('-', '').split('.');
  // half-up on the decimal string — never through a float
  let digits = (whole0 + (frac0 + '0'.repeat(decimals + 1)).slice(0, decimals + 1)).split('').map(Number);
  const up = (digits.pop() ?? 0) >= 5;
  if (up) {
    let i = digits.length - 1;
    while (i >= 0) {
      if (digits[i] === 9) {
        digits[i] = 0;
        i -= 1;
      } else {
        digits[i] = (digits[i] ?? 0) + 1;
        break;
      }
    }
    if (i < 0) digits = [1, ...digits];
  }
  const all = digits.join('');
  const whole = all.slice(0, all.length - decimals).replace(/^0+(?=\d)/, '') || '0';
  const frac = decimals ? all.slice(all.length - decimals) : '';
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
  const zero = /^0*$/.test(all);
  return `${neg && !zero ? '−' : ''}${grouped}${decimals ? `,${frac}` : ''}`;
}

/** Exact decimal addition of two decimal strings (no floats in money, CLAUDE.md §0.1). */
export function addDec(a: string, b: string): string {
  const scale = (s: string) => (s.split('.')[1] ?? '').length;
  const n = Math.max(scale(a), scale(b));
  const big = (s: string) => {
    const neg = s.startsWith('-');
    const [w = '0', f = ''] = s.replace('-', '').split('.');
    const v = BigInt(w + f.padEnd(n, '0'));
    return neg ? -v : v;
  };
  const sum = big(a) + big(b);
  const neg = sum < 0n;
  const digits = (neg ? -sum : sum).toString().padStart(n + 1, '0');
  const out = n ? `${digits.slice(0, -n)}.${digits.slice(-n)}` : digits;
  return neg ? `-${out}` : out;
}
