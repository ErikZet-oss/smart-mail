/** Slovak copy for draft.send_error (GitHub #20 / #23). Strings live in sk.json. */

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function sendErrorMessage(t: Translate, sendError: string | null | undefined): string {
  const [code = '', ...rest] = (sendError ?? '').split(':');
  const name = rest.join(':');
  if (code === 'attachment_infected') return t('compose.attachmentInfectedSend', { name });
  if (code === 'attachment_missing') return t('compose.attachmentMissingSend', { name });
  if (code === 'append_failed') return t('compose.sentNotStored');
  if (code === 'auth_failed') return t('compose.sendErrorAuth');
  if (code === 'no_credentials') return t('compose.sendErrorNoCredentials');
  if (code === 'server_unavailable' || code === 'smtp_host_not_allowed') return t('compose.sendErrorServer');
  if (
    code === 'SMTPRecipientsRefused' ||
    code === 'SMTPDataError' ||
    code === 'SMTPSenderRefused' ||
    code === 'recipient_not_allowed'
  ) {
    return t('compose.sendErrorRejected');
  }
  return t('compose.sendFailed');
}
