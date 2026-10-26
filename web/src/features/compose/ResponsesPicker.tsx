import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { listResponses } from './composeApi';

type Props = { onClose: () => void; onPick: (html: string) => void };

/** W4d Odpovede picker. */
export function ResponsesPicker({ onClose, onPick }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const [q, setQ] = useState('');
  const list = useQuery({ queryKey: ['responses'], queryFn: listResponses });
  const rows = (list.data ?? []).filter((r) => r.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[70vh] w-[480px] max-w-full flex-col rounded-lg bg-bg-canvas shadow-e3"
      >
        <div className="flex items-center gap-2 border-b border-border-default px-4 py-3">
          <h2 id={titleId} className="type-heading flex-1 text-text-primary">
            {t('compose.responses')}
          </h2>
          <button
            type="button"
            className="type-body text-text-secondary"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            ×
          </button>
        </div>
        <div className="px-4 py-2">
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={t('compose.searchResponses')}
            className="type-small h-9 w-full rounded-sm border border-border-default px-3"
          />
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {rows.length === 0 ? (
            <li className="type-small px-3 py-4 text-text-secondary">{t('compose.noResponses')}</li>
          ) : (
            rows.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className="type-body w-full rounded-sm px-3 py-2 text-left text-text-primary hover:bg-bg-subtle"
                  onClick={() => onPick(r.body_html)}
                >
                  {r.name}
                  <span className="type-caption ml-2 text-text-tertiary">{r.language.toUpperCase()}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
