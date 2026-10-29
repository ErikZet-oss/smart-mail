import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { adminErrorText, INPUT } from './adminUi';
import { fetchIdentities, saveIdentity } from './settingsApi';
import { FormRow } from './UsersPanel';

type Fields = { display_name: string; email: string; reply_to: string; organization: string };
// same order as the Figma frame W12-03a
const FIELDS: (keyof Fields)[] = ['display_name', 'email', 'organization', 'reply_to'];

/**
 * Sender of a branch mailbox (#68): the login (e.g. smartsronitra@) may have to send as an alias (nitra@) that the
 * SMTP server accepts. Only an admin edits it; the signature stays the branch template.
 */
export function BranchIdentityForm({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['settings', 'identities'], queryFn: () => fetchIdentities() });
  const identity = list.data?.find((i) => i.is_default) ?? list.data?.[0];
  const [form, setForm] = useState<Fields | null>(null);
  const value: Fields = form ?? {
    display_name: String(identity?.display_name ?? ''),
    email: String(identity?.email ?? ''),
    reply_to: String(identity?.reply_to ?? ''),
    organization: String(identity?.organization ?? ''),
  };
  const save = useMutation({
    mutationFn: () => {
      if (!identity) throw new Error('no identity');
      return saveIdentity(String(identity.id), {
        ...identity,
        ...value,
        reply_to: value.reply_to || null,
        organization: value.organization || null,
        is_default: true,
        signature_html: {},
      });
    },
    onSuccess: () => {
      setForm(null);
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'identities'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'signature-context'] });
    },
  });
  if (!identity) return null;

  return (
    <div className="flex flex-col gap-4" data-testid="branch-identity">
      {save.isError ? <Banner kind="danger" message={adminErrorText(t, save.error)} /> : null}
      <h2 className="type-heading text-text-primary">{t('settings.identity.section')}</h2>
      {FIELDS.map((key) => (
        <FormRow
          key={key}
          label={t(`settings.identity.${key}`)}
          help={key === 'display_name' ? t('settings.identity.displayNameHelp') : undefined}
          htmlFor={`branch-identity-${key}`}
        >
          <input
            id={`branch-identity-${key}`}
            className={INPUT}
            type={key === 'email' || key === 'reply_to' ? 'email' : 'text'}
            value={value[key]}
            readOnly={!canEdit}
            disabled={!canEdit}
            onChange={(event) => setForm({ ...value, [key]: event.target.value })}
          />
        </FormRow>
      ))}
      {canEdit ? (
        <div>
          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending || !form}>
            <Check size={16} aria-hidden="true" />
            {t('settings.save')}
          </Button>
        </div>
      ) : (
        <p className="type-small text-text-secondary">{t('settings.identity.branchAdminOnly')}</p>
      )}
    </div>
  );
}
