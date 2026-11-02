import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { uploadDocument } from './purchasingApi';

const ACCEPT = '.pdf,.xml,.isdoc,.isdocx,application/pdf,application/xml,text/xml';
const MAX_BYTES = 15 * 1024 * 1024;

/**
 * W6u „Nahrať doklad“ (Figma `46:42624`). Phase 4a: supplier documents only (PDF, XML, ISDOC); customer orders and
 * images/XLSX come with 4d / OCR. After the upload the list W6e shows the new document.
 */
export function UploadDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const tooBig = file !== null && file.size > MAX_BYTES;
  const upload = useMutation({
    mutationFn: () => uploadDocument(file as File),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['purchasing', 'documents'] });
      toasts.success(t('purchasing.upload.done'));
      onClose();
      navigate('/docs/delivery-notes');
    },
    onError: (e) => {
      const code = e instanceof ApiError ? e.detail.code : 'generic';
      toasts.error(t(`purchasing.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
    },
  });
  return (
    <Dialog
      title={t('purchasing.upload.title')}
      width={466}
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="button" disabled={!file || tooBig || upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? t('purchasing.upload.reading') : t('purchasing.upload.submit')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-testid="upload-dialog">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const dropped = e.dataTransfer.files[0];
            if (dropped) setFile(dropped);
          }}
          className={`flex flex-col items-center gap-2 rounded-md border-2 border-dashed px-4 py-6 text-center ${
            drag ? 'border-brand-primary-600 bg-brand-primary-50' : 'border-border-strong'
          }`}
        >
          <Upload size={22} aria-hidden="true" className="text-brand-primary-600" />
          <p className="type-body text-text-primary">{t('purchasing.upload.drop')}</p>
          <Button type="button" variant="secondary" onClick={() => input.current?.click()}>
            {t('purchasing.upload.pick')}
          </Button>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            aria-label={t('purchasing.upload.pick')}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p className="type-caption text-text-secondary">{t('purchasing.upload.types')}</p>
          {file ? (
            <p className="type-small break-all text-text-primary" data-testid="upload-file">
              {file.name}
            </p>
          ) : null}
          {tooBig ? <p className="type-small text-danger-600">{t('purchasing.errors.document_too_large')}</p> : null}
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="type-label mb-1 text-text-primary">{t('purchasing.upload.kind')}</legend>
          <label className="flex items-start gap-3 rounded-md border border-brand-primary-600 bg-brand-primary-50 p-3">
            <input type="radio" name="kind" checked readOnly className="mt-1" />
            <span className="flex flex-col">
              <span className="type-body text-text-primary">{t('purchasing.upload.kindSupplier')}</span>
              <span className="type-caption text-text-secondary">{t('purchasing.upload.kindSupplierHint')}</span>
            </span>
          </label>
          <label className="flex cursor-not-allowed items-start gap-3 rounded-md border border-border-default p-3 opacity-60">
            <input type="radio" name="kind" disabled className="mt-1" />
            <span className="flex flex-col">
              <span className="type-body text-text-primary">{t('purchasing.upload.kindOrder')}</span>
              <span className="type-caption text-text-secondary">{t('documents.later', { phase: '4d' })}</span>
            </span>
          </label>
        </fieldset>
      </div>
    </Dialog>
  );
}
