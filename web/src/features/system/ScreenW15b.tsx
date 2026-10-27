import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { Logo } from '../../components/Logo';
import { fetchProvider } from '../settings/settingsApi';
import { useSystemUi } from './systemUi';

type Props = { onClose: () => void };

/** W15b O systéme — logo, version, help links, restart tour, provider admin (D20). */
export function ScreenW15b({ onClose }: Props) {
  const { t } = useTranslation();
  const { open, restartTour } = useSystemUi();
  const provider = useQuery({ queryKey: ['settings', 'provider'], queryFn: () => fetchProvider(), retry: false });
  const version = __APP_VERSION__;
  const adminUrl = provider.data?.provider_admin_url ? String(provider.data.provider_admin_url) : null;

  return (
    <Dialog
      title={t('about.title')}
      width={420}
      onClose={onClose}
      footer={
        <Button type="button" variant="secondary" onClick={onClose}>
          {t('common.close')}
        </Button>
      }
    >
      <div data-testid="screen-w15b" className="flex flex-col items-center gap-4 text-center">
        <Logo width={72} />
        <div>
          <p className="type-heading text-text-primary">{t('about.product')}</p>
          <p className="type-caption text-text-secondary">{t('about.version', { version })}</p>
        </div>
        <ul className="flex w-full flex-col gap-1 text-left">
          <li>
            <button
              type="button"
              className="type-body w-full rounded-sm px-2 py-2 text-left text-brand-primary-700 hover:bg-bg-subtle"
              onClick={() => {
                onClose();
                open('shortcuts');
              }}
            >
              {t('about.shortcuts')}
            </button>
          </li>
          <li>
            <a
              className="type-body block rounded-sm px-2 py-2 text-brand-primary-700 hover:bg-bg-subtle"
              href="https://github.com/ErikZet-oss/smart-mail/blob/main/CHANGELOG.md"
              target="_blank"
              rel="noreferrer"
            >
              {t('about.changelog')}
            </a>
          </li>
          <li>
            <button
              type="button"
              className="type-body w-full rounded-sm px-2 py-2 text-left text-brand-primary-700 hover:bg-bg-subtle"
              onClick={() => {
                onClose();
                restartTour();
              }}
            >
              {t('about.restartTour')}
            </button>
          </li>
          {adminUrl ? (
            <li>
              <a
                className="type-body block rounded-sm px-2 py-2 text-brand-primary-700 hover:bg-bg-subtle"
                href={adminUrl}
                target="_blank"
                rel="noreferrer"
              >
                {t('about.providerAdmin')}
              </a>
            </li>
          ) : (
            <li className="type-caption px-2 py-2 text-text-tertiary">{t('about.providerMissing')}</li>
          )}
        </ul>
      </div>
    </Dialog>
  );
}
