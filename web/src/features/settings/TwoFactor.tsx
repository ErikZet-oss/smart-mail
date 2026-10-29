import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Download, ShieldCheck } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { INPUT } from './adminUi';
import { confirmTwoFactor, disableTwoFactor, fetchTwoFactor, startTwoFactor } from './settingsApi';

const KEY = ['settings', 'security', '2fa'];

/** W12-09 „Dvojstupňové overenie“ row (Figma `67:58683`): state chip + Zapnúť / Vypnúť. Personal accounts only. */
export function TwoFactorRow() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: fetchTwoFactor });
  const [enabling, setEnabling] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const off = useMutation({
    mutationFn: disableTwoFactor,
    onSuccess: () => {
      setDisabling(false);
      toasts.success(t('settings.twoFactor.disabled'));
      void qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (error) => {
      setDisabling(false);
      const code = error instanceof ApiError ? error.detail.code : '';
      if (code !== 'reauth_required')
        toasts.error(t(`settings.twoFactor.errors.${code}`, t('settings.twoFactor.errors.generic')));
    },
  });
  const data = status.data;
  if (!data) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2" data-testid="two-factor">
      <div className="min-w-[300px]">
        <p className="type-small text-text-primary">{t('settings.twoFactor.title')}</p>
        <p className="type-caption text-text-secondary">{t('settings.twoFactor.help')}</p>
      </div>
      <span
        className={`type-caption rounded-full px-2 py-0.5 ${
          data.enabled ? 'bg-success-50 text-success-700' : 'bg-bg-muted text-text-secondary'
        }`}
      >
        {data.enabled ? t('settings.twoFactor.on') : t('settings.twoFactor.off')}
      </span>
      {data.available ? (
        data.enabled ? (
          <Button type="button" variant="secondary" onClick={() => setDisabling(true)} disabled={data.required}>
            {t('settings.twoFactor.disable')}
          </Button>
        ) : (
          <Button type="button" variant="secondary" onClick={() => setEnabling(true)}>
            <ShieldCheck size={16} aria-hidden="true" />
            {t('settings.twoFactor.enable')}
          </Button>
        )
      ) : null}
      {data.enabled && data.required ? (
        <p className="type-caption w-full text-text-secondary">{t('settings.twoFactor.requiredHint')}</p>
      ) : null}
      {enabling ? <EnableTwoFactorDialog onClose={() => setEnabling(false)} /> : null}
      {disabling ? (
        <ConfirmDialog
          title={t('settings.twoFactor.disableTitle')}
          body={t('settings.twoFactor.disableBody')}
          confirmLabel={t('settings.twoFactor.disable')}
          busy={off.isPending}
          onConfirm={() => off.mutate()}
          onClose={() => setDisabling(false)}
        />
      ) : null}
    </div>
  );
}

const groups = (secret: string) => secret.match(/.{1,4}/g)?.join(' ') ?? secret;

/** Figma `67:58896`: 1. QR (or the key by hand), 2. the code from the app, 3. backup codes (each once) + download. */
export function EnableTwoFactorDialog({ onClose, onEnabled }: { onClose: () => void; onEnabled?: () => void }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: startTwoFactor,
    onError: (e) => {
      // „Potvrďte heslom“ was cancelled: nothing was started, close quietly
      if (e instanceof ApiError && e.detail.code === 'reauth_required') onClose();
      else setError(t('settings.twoFactor.errors.generic'));
    },
  });
  const confirm = useMutation({
    mutationFn: () => confirmTwoFactor(code.replace(/\s/g, '')),
    onSuccess: () => {
      toasts.success(t('settings.twoFactor.enabled'));
      void qc.invalidateQueries({ queryKey: KEY });
      if (onEnabled) onEnabled();
      else onClose();
    },
    onError: (e) => {
      const errorCode = e instanceof ApiError ? e.detail.code : 'generic';
      setError(t(`settings.twoFactor.errors.${errorCode}`, t('settings.twoFactor.errors.generic')));
      if (errorCode === 'totp_setup_expired') start.mutate();
    },
  });
  const { mutate } = start;
  const started = useRef(false);
  useEffect(() => {
    // exactly one setup per dialog (a second `start` would replace the secret shown here)
    if (started.current) return;
    started.current = true;
    mutate();
  }, [mutate]);
  const setup = start.data;

  function download() {
    if (!setup) return;
    const text = `${t('settings.twoFactor.fileTitle')}\n\n${setup.backup_codes.join('\n')}\n`;
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'smart-mail-zalozne-kody.txt';
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Dialog
      title={t('settings.twoFactor.dialogTitle')}
      width={560}
      onClose={onClose}
      onSubmit={() => code.replace(/\s/g, '').length === 6 && confirm.mutate()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!setup || confirm.isPending || code.replace(/\s/g, '').length !== 6}>
            {t('settings.twoFactor.enable')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-testid="two-factor-dialog">
        {error ? <Banner kind="danger" message={error} /> : null}
        <p className="type-body text-text-primary">{t('settings.twoFactor.step1')}</p>
        {setup ? (
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-md border border-border-default bg-bg-canvas p-3">
              <QRCodeSVG value={setup.otpauth_uri} size={124} aria-label={t('settings.twoFactor.qr')} role="img" />
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="type-small text-text-secondary">{t('settings.twoFactor.manual')}</span>
              <code className="type-body font-mono text-text-primary" data-testid="two-factor-secret">
                {groups(setup.secret)}
              </code>
              <button
                type="button"
                onClick={() => void navigator.clipboard?.writeText(setup.secret)}
                className="type-label inline-flex items-center gap-1.5 self-start text-brand-primary-700 hover:underline"
              >
                <Copy size={16} aria-hidden="true" />
                {t('settings.twoFactor.copy')}
              </button>
            </div>
          </div>
        ) : null}
        <label className="flex flex-col gap-1">
          <span className="type-small text-text-primary">{t('settings.twoFactor.step2')}</span>
          <input
            className={`${INPUT} max-w-[200px]`}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder={t('settings.twoFactor.codePlaceholder')}
            maxLength={7}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            data-autofocus
          />
        </label>
        {setup ? (
          <div className="flex flex-col gap-2 rounded-md bg-bg-subtle p-3">
            <span className="type-small font-semibold text-text-primary">{t('settings.twoFactor.step3')}</span>
            <ul className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono sm:grid-cols-5" data-testid="backup-codes">
              {setup.backup_codes.map((c) => (
                <li key={c} className="type-small text-text-primary">
                  {c.toUpperCase()}
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={download}
              className="type-label inline-flex items-center gap-1.5 self-start text-brand-primary-700 hover:underline"
            >
              <Download size={16} aria-hidden="true" />
              {t('settings.twoFactor.download')}
            </button>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
