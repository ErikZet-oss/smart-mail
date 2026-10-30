import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { adminErrorText } from './adminUi';
import { removePrivateImage, uploadPrivateImage } from './settingsApi';

const MAX_BYTES = 1024 * 1024;

type Props = {
  /** admin-only endpoint: GET = preview, POST = upload, DELETE = remove */
  url: string;
  present: boolean;
  kind: 'stamp' | 'signature';
  queryKey: readonly unknown[];
};

/** #139 „Pečiatka“ / „Podpis“ for the Prehlásenie o zhode. ⚠ admin + re-auth (the password dialog retries the
 * request). The image is shown only here, to admins — it is never a public URL or an e-mail signature variable. */
export function PrivateImageField({ url, present, kind, queryKey }: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [version, setVersion] = useState(0);
  const [has, setHas] = useState(present);
  const [confirm, setConfirm] = useState(false);
  const done = (value: boolean) => {
    setHas(value);
    setVersion((v) => v + 1);
    void qc.invalidateQueries({ queryKey });
  };
  const upload = useMutation({
    mutationFn: (file: File) => uploadPrivateImage(url, file),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      done(true);
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const remove = useMutation({
    mutationFn: () => removePrivateImage(url),
    onSuccess: () => {
      setConfirm(false);
      done(false);
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const label = t(`settings.branches.${kind}`);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`private-image-${kind}`}>
      <span
        className="flex h-16 w-[140px] items-center justify-center rounded-sm border border-dashed border-border-default bg-bg-canvas p-1"
        aria-hidden={!has}
      >
        {has ? (
          <img src={`${url}?v=${version}`} alt={label} className="max-h-full max-w-full object-contain" />
        ) : (
          <span className="type-caption text-text-secondary">{t('settings.branches.imageNone')}</span>
        )}
      </span>
      <Button type="button" variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
        {has ? t('settings.branches.imageChange') : t('settings.branches.imageUpload')} ⚠
      </Button>
      {has ? (
        <Button type="button" variant="secondary" onClick={() => setConfirm(true)} disabled={remove.isPending}>
          {t('settings.branches.imageRemove')}
        </Button>
      ) : null}
      <input
        ref={input}
        type="file"
        hidden
        accept="image/png"
        aria-label={label}
        data-testid={`private-image-${kind}-input`}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (!file) return;
          if (file.size > MAX_BYTES) {
            toasts.error(t('settings.users.errors.image_too_large'));
            return;
          }
          upload.mutate(file);
        }}
      />
      {confirm ? (
        <ConfirmDialog
          title={t('settings.branches.imageRemoveTitle', { what: label })}
          body={t(`settings.branches.${kind}RemoveBody`)}
          confirmLabel={t('settings.branches.imageRemove')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirm(false)}
        />
      ) : null}
    </div>
  );
}
