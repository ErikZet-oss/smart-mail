import { api, apiBlob } from '../../lib/api';

/** #139 Prehlásenie o zhode (atest 2.1). */
export type ConformityItem = { nazov: string; kod: string; norma: string; poznamka: string };
export type ConformityRequest = {
  customer: string;
  document_ref: string;
  place: string | null;
  issued_on: string | null;
  items: ConformityItem[];
  message_id: string | null;
  suggestion_id?: string | null;
  branch_id?: string | null;
};
export type ConformityBranch = { id: string; name: string; ready: boolean };
export const fetchConformityBranches = () => api<ConformityBranch[]>('GET', '/api/documents/conformity/branches');
export type ConformityIssued = {
  id: string;
  number: string;
  issued_on: string;
  branch_id: string;
  signer: string;
  items: number;
  sha256: string;
  draft_id: string | null;
};
export const previewConformity = (body: ConformityRequest) =>
  apiBlob('POST', '/api/documents/conformity/preview', body, { global: false });
export const issueConformity = (body: ConformityRequest) =>
  api<ConformityIssued>('POST', '/api/documents/conformity', body, { global: false });
