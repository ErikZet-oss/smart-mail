import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { fetchSourceText, sourceUrl } from './mailApi';

/** W2n Zdroj správy — monospace raw RFC822 + download .eml. */
export function ScreenW2n() {
  const { t } = useTranslation();
  const params = useParams();
  const mailbox = params.mailbox ?? 'default';
  const messageId = params.messageId ?? '';
  const source = useQuery({
    queryKey: ['mail', 'source', mailbox, messageId],
    queryFn: () => fetchSourceText(mailbox, messageId),
    enabled: Boolean(messageId),
  });

  return (
    <main className="flex h-full flex-col bg-bg-canvas">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border-default px-4">
        <h1 className="type-heading flex-1 text-text-primary">{t('mail.sourceTitle')}</h1>
        <a
          href={sourceUrl(mailbox, messageId)}
          download="message.eml"
          className="type-label rounded-sm bg-brand-primary-600 px-3 py-1.5 text-text-on-primary hover:brightness-95"
        >
          {t('mail.downloadEml')}
        </a>
      </header>
      <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-[12px] leading-5 text-text-primary">
        {source.isLoading ? t('mail.loading') : (source.data ?? t('mail.sourceUnavailable'))}
      </pre>
    </main>
  );
}
