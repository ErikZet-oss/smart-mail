import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { changeCategory, fetchEnabledCategories } from './mailApi';

type Props = { mailbox: string; messageId: string; current: string | null; onClose: () => void };

/** #143 „Zmeniť kategóriu…“: the enabled 17c categories; the person's choice wins over the AI until changed again. */
export function CategoryDialog({ mailbox, messageId, current, onClose }: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState(current ?? '');
  const list = useQuery({
    queryKey: ['mail', 'categories-all', mailbox],
    queryFn: () => fetchEnabledCategories(mailbox),
  });
  const save = useMutation({
    mutationFn: () => changeCategory(mailbox, messageId, picked),
    onSuccess: () => {
      toasts.success(t('mail.category.saved'));
      void queryClient.invalidateQueries({ queryKey: ['mail'] });
      onClose();
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });
  return (
    <Dialog
      title={t('mail.category.title')}
      width={420}
      onClose={onClose}
      onSubmit={() => picked && picked !== current && save.mutate()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('mail.category.cancel')}
          </Button>
          <Button type="submit" disabled={!picked || picked === current || save.isPending}>
            {t('mail.category.save')}
          </Button>
        </>
      }
    >
      <fieldset className="flex max-h-[50vh] flex-col gap-1 overflow-y-auto" data-testid="category-dialog">
        <legend className="type-small mb-2 text-text-secondary">{t('mail.category.help')}</legend>
        {(list.data?.categories ?? []).map((c) => (
          <label key={c.id} className="type-body inline-flex items-center gap-2 text-text-primary">
            <input
              type="radio"
              name="category"
              value={c.id}
              checked={picked === c.id}
              onChange={() => setPicked(c.id)}
            />
            {t(`ai.categories.${c.id}.label`, { defaultValue: c.label_sk })}
          </label>
        ))}
      </fieldset>
    </Dialog>
  );
}
