import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { HtmlSignatureEditor } from '../settings/HtmlSignatureEditor';

type Props = {
  initialHtml: string;
  onClose: () => void;
  onSave: (html: string) => void;
  busy?: boolean;
};

/** W4e — Upraviť podpis len pre túto správu. Same TipTap editor as SETTINGS 03a (D22). */
export function SignatureEditDialog({ initialHtml, onClose, onSave, busy }: Props) {
  const { t } = useTranslation();
  const [html, setHtml] = useState(initialHtml);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="w4e-title"
        className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-md border border-border-default bg-bg-canvas shadow-lg"
      >
        <header className="border-b border-border-default px-4 py-3">
          <h2 id="w4e-title" className="type-heading text-text-primary">
            {t('compose.signatureEditTitle')}
          </h2>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <HtmlSignatureEditor value={html} onChange={setHtml} />
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
