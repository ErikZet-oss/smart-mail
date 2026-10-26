import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import type { ComposeCheck } from './composeApi';

type Props = {
  checks: ComposeCheck[];
  onEdit: () => void;
  onSendAnyway: () => void;
  busy?: boolean;
};

/** W4b Kontrola pred odoslaním. */
export function PreSendDialog({ checks, onEdit, onSendAnyway, busy }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const blocking = checks.some((c) => c.blocking);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-[420px] max-w-full rounded-lg bg-bg-canvas shadow-e3"
      >
        <div className="border-b border-border-default px-5 py-4">
          <h2 id={titleId} className="type-heading text-text-primary">
            {t('compose.preSendTitle')}
          </h2>
        </div>
        <ul className="flex flex-col gap-2 px-5 py-4">
          {checks.map((c) => (
            <li key={c.code} className={`type-body ${c.blocking ? 'text-danger-600' : 'text-text-primary'}`}>
              {t(`compose.checks.${c.code}`, { defaultValue: c.message })}
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-2 border-t border-border-default px-5 py-3">
          <Button type="button" variant="secondary" onClick={onEdit}>
            {t('compose.edit')}
          </Button>
          <Button type="button" onClick={onSendAnyway} disabled={blocking || busy}>
            {t('compose.sendAnyway')}
          </Button>
        </div>
      </div>
    </div>
  );
}
