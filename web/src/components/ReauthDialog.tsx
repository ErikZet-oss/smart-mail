import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, ApiError, onReauthRequired } from '../lib/api';
import { Banner } from './Banner';
import { Button } from './Button';
import { Dialog } from './Dialog';

const INPUT =
  'type-body h-[var(--size-input)] w-full rounded-sm border border-border-default bg-bg-canvas px-3 text-text-primary focus:border-brand-primary-500 focus:outline-none';

/** G re-auth dialog (#54, SETTINGS_SPEC §39): a ⚠ admin change answered 401 `reauth_required`, so ask for the mailbox
 * password once and let the original request repeat. Several waiting requests share one prompt. A wrong password
 * keeps the dialog open; it never signs out. */
export function ReauthDialogHost() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ promise: Promise<boolean>; resolve: (ok: boolean) => void } | null>(null);

  useEffect(() => {
    onReauthRequired(() => {
      if (!pending.current) {
        let resolve: (ok: boolean) => void = () => undefined;
        const promise = new Promise<boolean>((r) => {
          resolve = r;
        });
        pending.current = { promise, resolve };
        setPassword('');
        setError(null);
        setOpen(true);
      }
      return pending.current.promise;
    });
    return () => onReauthRequired(undefined);
  }, []);

  function finish(ok: boolean) {
    pending.current?.resolve(ok);
    pending.current = null;
    setOpen(false);
    setPassword('');
  }

  async function submit() {
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api('POST', '/api/auth/reauth', { password }, { global: false });
      finish(true);
    } catch (e) {
      const code = e instanceof ApiError ? e.detail.code : '';
      setError(
        code === 'reauth_failed'
          ? t('reauth.wrong')
          : code === 'rate_limited'
            ? t('reauth.rateLimited')
            : t('reauth.failed'),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <Dialog
      title={t('reauth.title')}
      width={420}
      onClose={() => finish(false)}
      onSubmit={() => void submit()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={() => finish(false)}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={busy || !password}>
            {t('reauth.confirm')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3" data-testid="reauth-dialog">
        <p className="type-body text-text-secondary">{t('reauth.body')}</p>
        {error ? <Banner kind="danger" message={error} /> : null}
        <label className="flex flex-col gap-1">
          <span className="type-small text-text-primary">{t('reauth.password')}</span>
          <input
            className={INPUT}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-autofocus
          />
        </label>
      </div>
    </Dialog>
  );
}
