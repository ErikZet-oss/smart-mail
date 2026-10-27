import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';

type Props = {
  initialHtml: string;
  onClose: () => void;
  onSave: (html: string) => void;
  busy?: boolean;
};

/** W4e — Upraviť podpis len pre túto správu (SCREENS_SPEC; D22 source view). */
export function SignatureEditDialog({ initialHtml, onClose, onSave, busy }: Props) {
  const { t } = useTranslation();
  const [source, setSource] = useState(false);
  const [html, setHtml] = useState(initialHtml);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="w4e-title"
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-md border border-border-default bg-bg-canvas shadow-lg"
      >
        <header className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 id="w4e-title" className="type-heading text-text-primary">
            {t('compose.signatureEditTitle')}
          </h2>
          <button
            type="button"
            className="type-caption rounded-sm px-2 py-1 text-text-secondary hover:bg-bg-subtle"
            onClick={() => setSource((v) => !v)}
          >
            {source ? t('compose.signatureVisual') : t('compose.signatureSource')}
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {source ? (
            <textarea
              value={html}
              onChange={(event) => setHtml(event.target.value)}
              className="type-mono h-64 w-full rounded-sm border border-border-default bg-bg-subtle p-3 text-text-primary"
              aria-label={t('compose.signatureSource')}
              spellCheck={false}
            />
          ) : (
            <div
              className="type-body min-h-[12rem] rounded-sm border border-border-default p-3 text-text-primary"
              contentEditable
              suppressContentEditableWarning
              onBlur={(event) => setHtml(event.currentTarget.innerHTML)}
              dangerouslySetInnerHTML={{ __html: html }}
              aria-label={t('compose.signatureEditTitle')}
            />
          )}
          <p className="type-caption mt-2 text-text-tertiary">{t('compose.signatureEditHint')}</p>
        </div>
        <footer className="flex justify-end gap-2 border-t border-border-default px-4 py-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button type="button" onClick={() => onSave(html)} disabled={busy}>
            {t('compose.save')}
          </Button>
        </footer>
      </div>
    </div>
  );
}
