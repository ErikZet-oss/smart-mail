import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';

import { formatMailDate } from './formatMailDate';
import { fetchMessage, messageKey } from './mailApi';

/** W2m Tlač — clean printable page; browser print dialog opens on load. */
export function ScreenW2m() {
  const { t } = useTranslation();
  const params = useParams();
  const [search] = useSearchParams();
  const mailbox = params.mailbox ?? 'default';
  const messageId = search.get('m') ?? params.messageId ?? '';
  const detail = useQuery({
    queryKey: messageKey(mailbox, messageId),
    queryFn: () => fetchMessage(mailbox, messageId, false),
    enabled: Boolean(messageId),
  });

  useEffect(() => {
    if (detail.data) {
      const timer = window.setTimeout(() => window.print(), 300);
      return () => window.clearTimeout(timer);
    }
  }, [detail.data]);

  const msg = detail.data;
  return (
    <main className="mx-auto max-w-3xl bg-bg-canvas p-8 text-text-primary print:p-0">
      <h1 className="type-title mb-4">{msg?.subject || t('mail.noSubject')}</h1>
      {msg ? (
        <>
          <p className="type-small text-text-secondary">
            {t('mail.from')} {msg.from_name || msg.from_email} &lt;{msg.from_email}&gt;
          </p>
          <p className="type-small text-text-secondary">
            {t('mail.to')} {msg.to.map((a) => a.email).filter(Boolean).join(', ')}
          </p>
          <p className="type-small mb-6 text-text-secondary">
            {t('mail.date')} {formatMailDate(msg.received_at || msg.sent_at)}
          </p>
          {msg.body_html_sanitized ? (
            <div dangerouslySetInnerHTML={{ __html: msg.body_html_sanitized }} />
          ) : (
            <pre className="whitespace-pre-wrap">{msg.body_text}</pre>
          )}
          {msg.attachments.length > 0 ? (
            <ul className="mt-6 type-small text-text-secondary">
              {msg.attachments.map((a) => (
                <li key={a.id}>
                  {a.filename} ({a.size} B)
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p className="type-body">{t('mail.loading')}</p>
      )}
    </main>
  );
}
