import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';

type Props = {
  value: string;
  onChange: (html: string) => void;
  label?: string;
};

/** D22: WYSIWYG + <> Zdrojový kód for identity / branch / W4e signatures. */
export function HtmlSignatureEditor({ value, onChange, label }: Props) {
  const { t } = useTranslation();
  const [source, setSource] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        {label ? <span className="type-label text-text-secondary">{label}</span> : <span />}
        <Button type="button" variant="secondary" size="md" onClick={() => setSource((v) => !v)}>
          {source ? t('settings.signature.visual') : t('settings.signature.source')}
        </Button>
      </div>
      {source ? (
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="type-mono min-h-[160px] w-full rounded-sm border border-border-default bg-bg-subtle p-3 text-text-primary"
          spellCheck={false}
          aria-label={t('settings.signature.source')}
        />
      ) : (
        <div
          className="type-body min-h-[160px] rounded-sm border border-border-default p-3 text-text-primary"
          contentEditable
          suppressContentEditableWarning
          dangerouslySetInnerHTML={{ __html: value }}
          onBlur={(event) => onChange(event.currentTarget.innerHTML)}
          aria-label={label ?? t('settings.signature.editor')}
        />
      )}
      <p className="type-caption text-text-tertiary">{t('settings.signature.hint')}</p>
    </div>
  );
}
