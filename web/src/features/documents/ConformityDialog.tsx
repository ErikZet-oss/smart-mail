import { useMutation, useQuery } from '@tanstack/react-query';
import { FileText, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import {
  fetchConformityBranches,
  issueConformity,
  previewConformity,
  type ConformityItem,
  type ConformityRequest,
} from './documentsApi';

const INPUT =
  'type-body w-full rounded-md border border-border-default bg-bg-surface px-2 py-1 text-text-primary focus:outline-none focus:ring-2 focus:ring-brand-primary-500';
const EMPTY: ConformityItem = { nazov: '', kod: '', norma: '', poznamka: '' };
const COLUMNS: (keyof ConformityItem)[] = ['nazov', 'kod', 'norma', 'poznamka'];

type Props = {
  messageId: string | null;
  initialCustomer?: string;
  /** #139 C: values prefilled by the AI card; the person checks them before „Vystaviť“ */
  initialDocumentRef?: string;
  initialItems?: Partial<ConformityItem>[];
  suggestionId?: string | null;
  onIssued?: () => void;
  onClose: () => void;
};

/** #139 „Vystaviť prehlásenie o zhode…“ (atest 2.1). No Figma frame — built from the Dialog component with an
 * editable table. „Vystaviť“ is always this person's click; the PDF is attached to a reply draft in Koncepty. */
export function ConformityDialog({
  messageId,
  initialCustomer = '',
  initialDocumentRef = '',
  initialItems,
  suggestionId = null,
  onIssued,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const navigate = useNavigate();
  const [customer, setCustomer] = useState(initialCustomer);
  const [documentRef, setDocumentRef] = useState(initialDocumentRef);
  const [place, setPlace] = useState('');
  const [issuedOn, setIssuedOn] = useState(new Date().toISOString().slice(0, 10));
  const [items, setItems] = useState<ConformityItem[]>(
    initialItems && initialItems.length > 0 ? initialItems.map((i) => ({ ...EMPTY, ...i })) : [{ ...EMPTY }],
  );
  const [error, setError] = useState<string | null>(null);
  // pilot 2026-10-30: a personal account (no branch) or a person covering several branches picks the branch here
  const branches = useQuery({ queryKey: ['conformity-branches'], queryFn: fetchConformityBranches });
  const [branchId, setBranchId] = useState<string>('');
  const chosenBranch = branchId || branches.data?.[0]?.id || '';

  const request = (): ConformityRequest => ({
    customer: customer.trim(),
    document_ref: documentRef.trim(),
    place: place.trim() || null,
    issued_on: issuedOn || null,
    items: items.filter((i) => i.nazov.trim() !== ''),
    message_id: messageId,
    suggestion_id: suggestionId,
    branch_id: chosenBranch || null,
  });
  const valid = customer.trim() !== '' && items.some((i) => i.nazov.trim() !== '');
  const showError = (e: unknown) => {
    if (e instanceof ApiError && e.status === 401) return; // the password dialog was cancelled
    const code = e instanceof ApiError ? e.detail.code : 'generic';
    setError(t(`conformity.errors.${code}`, { defaultValue: t('conformity.errors.generic') }));
  };

  const preview = useMutation({
    mutationFn: () => previewConformity(request()),
    onSuccess: (blob) => {
      setError(null);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
    onError: showError,
  });
  const issue = useMutation({
    mutationFn: () => issueConformity(request()),
    onSuccess: (out) => {
      toasts.success(t('conformity.issued', { number: out.number }));
      onIssued?.();
      onClose();
      if (out.draft_id) navigate(`/compose/${encodeURIComponent(out.draft_id)}`);
    },
    onError: showError,
  });
  const setItem = (index: number, key: keyof ConformityItem, value: string) =>
    setItems((all) => all.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  return (
    <Dialog
      title={t('conformity.title')}
      width={780}
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('conformity.cancel')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            icon={<FileText size={16} aria-hidden="true" />}
            disabled={!valid || preview.isPending}
            onClick={() => preview.mutate()}
          >
            {t('conformity.preview')}
          </Button>
          <Button type="button" disabled={!valid || issue.isPending} onClick={() => issue.mutate()}>
            {t('conformity.issue')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3" data-testid="conformity-dialog">
        {(branches.data?.length ?? 0) > 1 && (
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('conformity.branch')}</span>
            <select
              className={INPUT}
              data-testid="conformity-branch"
              value={chosenBranch}
              onChange={(e) => setBranchId(e.target.value)}
            >
              {branches.data?.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.ready ? b.name : `${b.name} – ${t('conformity.branchNotReady')}`}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="grid gap-3 sm:grid-cols-[1.6fr_1fr]">
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('conformity.customer')}</span>
            <textarea
              className={INPUT}
              rows={2}
              maxLength={500}
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('conformity.documentRef')}</span>
            <input
              className={INPUT}
              maxLength={120}
              value={documentRef}
              onChange={(e) => setDocumentRef(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('conformity.place')}</span>
            <input
              className={INPUT}
              maxLength={80}
              placeholder={t('conformity.placeDefault')}
              value={place}
              onChange={(e) => setPlace(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('conformity.date')}</span>
            <input className={INPUT} type="date" value={issuedOn} onChange={(e) => setIssuedOn(e.target.value)} />
          </label>
        </div>
        <div className="overflow-x-auto">
          <table className="type-small w-full border-collapse text-text-primary">
            <thead>
              <tr className="border-b border-border-default text-left">
                <th scope="col" className="w-8 py-1">
                  #
                </th>
                {COLUMNS.map((key) => (
                  <th key={key} scope="col" className="px-1 py-1 font-medium">
                    {t(`conformity.columns.${key}`)}
                  </th>
                ))}
                <th scope="col" className="sr-only">
                  {t('conformity.removeRow')}
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, index) => (
                <tr key={index} className="border-b border-border-default">
                  <td className="py-1 text-text-secondary">{index + 1}</td>
                  {COLUMNS.map((key) => (
                    <td key={key} className="px-1 py-1">
                      <input
                        className={INPUT}
                        aria-label={`${t(`conformity.columns.${key}`)} ${index + 1}`}
                        value={row[key]}
                        onChange={(e) => setItem(index, key, e.target.value)}
                      />
                    </td>
                  ))}
                  <td className="py-1">
                    <button
                      type="button"
                      className="text-text-secondary hover:text-text-primary"
                      aria-label={`${t('conformity.removeRow')} ${index + 1}`}
                      disabled={items.length === 1}
                      onClick={() => setItems((all) => all.filter((_, i) => i !== index))}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button
          type="button"
          variant="secondary"
          className="self-start"
          icon={<Plus size={16} aria-hidden="true" />}
          onClick={() => setItems((all) => [...all, { ...EMPTY }])}
        >
          {t('conformity.addRow')}
        </Button>
        <p className="type-small text-text-secondary">{messageId ? t('conformity.helpReply') : t('conformity.help')}</p>
        {error ? (
          <p role="alert" className="type-small text-danger-600">
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
