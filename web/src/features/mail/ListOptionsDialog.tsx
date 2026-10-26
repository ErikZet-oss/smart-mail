import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Switch } from '../../components/Switch';
import type { ListPrefs } from '../prefs/prefsApi';

type Props = {
  initial: ListPrefs;
  onSave: (next: ListPrefs) => void;
  onClose: () => void;
  busy?: boolean;
};

const SORTS: ListPrefs['sort'][] = ['date_received', 'date_sent', 'subject', 'from', 'size'];

/** W2o Nastavenia zoznamu — Roundcube fields + density + AI summary (SETTINGS 01b). */
export function ListOptionsDialog({ initial, onSave, onClose, busy }: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initial);
  const titleId = useId();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4">
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={(event) => {
          event.preventDefault();
          onSave(draft);
        }}
        className="flex w-[500px] max-w-full flex-col rounded-lg bg-bg-canvas shadow-e3"
      >
        <div className="flex h-14 items-center border-b border-border-default px-5">
          <h2 id={titleId} className="type-heading flex-1 text-text-primary">
            {t('mail.options.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="type-body text-text-secondary hover:text-text-primary"
          >
            ×
          </button>
        </div>
        <div className="flex flex-col gap-4 px-5 py-5">
          <Field label={t('mail.options.sort')}>
            <select
              value={draft.sort}
              onChange={(event) => setDraft({ ...draft, sort: event.target.value as ListPrefs['sort'] })}
              className="type-body h-9 w-full rounded-sm border border-border-strong bg-bg-canvas px-3"
            >
              {SORTS.map((key) => (
                <option key={key} value={key}>
                  {t(`mail.options.sorts.${key}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('mail.options.sortDir')}>
            <select
              value={draft.sort_dir}
              onChange={(event) => setDraft({ ...draft, sort_dir: event.target.value as ListPrefs['sort_dir'] })}
              className="type-body h-9 w-full rounded-sm border border-border-strong bg-bg-canvas px-3"
            >
              <option value="desc">{t('mail.options.desc')}</option>
              <option value="asc">{t('mail.options.asc')}</option>
            </select>
          </Field>
          <Field label={t('mail.options.mode')}>
            <select
              value={draft.mode}
              onChange={(event) => setDraft({ ...draft, mode: event.target.value as ListPrefs['mode'] })}
              className="type-body h-9 w-full rounded-sm border border-border-strong bg-bg-canvas px-3"
            >
              <option value="list">{t('mail.options.modeList')}</option>
              <option value="conversations">{t('mail.options.modeConversations')}</option>
            </select>
          </Field>
          <div className="h-px bg-border-default" />
          <Field label={t('mail.options.density')}>
            <div className="flex h-8 overflow-hidden rounded-sm border border-border-strong">
              {(['compact', 'comfortable'] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDraft({ ...draft, density: d })}
                  className={`type-small flex-1 px-2 ${
                    draft.density === d ? 'bg-brand-primary-600 text-text-on-primary' : 'bg-bg-canvas text-text-primary'
                  }`}
                >
                  {t(`mail.options.density_${d}`)}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t('mail.options.aiSummary')}>
            <Switch
              checked={draft.show_ai_summary}
              onChange={(checked) => setDraft({ ...draft, show_ai_summary: checked })}
              label={<span className="sr-only">{t('mail.options.aiSummary')}</span>}
            />
          </Field>
        </div>
        <div className="flex justify-end gap-2 border-t border-border-default px-5 py-3">
          <Button variant="secondary" type="button" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={busy}>
            {t('mail.options.save')}
          </Button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-6">
      <span className="type-small w-[150px] shrink-0 text-text-primary">{label}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
