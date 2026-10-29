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

/** Extra lines under the banner (#69): the SMTP server's own reply, e.g. `SMTPSenderRefused:550:Sending mail from …`,
 * plus a Slovak hint for the provider's country block. Empty for every other send_error. */
export function sendErrorServerReply(t: Translate, sendError: string | null | undefined): string[] {
  const match = /^SMTP\w+:(\d{3}):(.+)$/.exec(sendError ?? '');
  if (!match) return [];
  const [, smtpCode = '', text = ''] = match;
  const lines = [t('compose.sendErrorServerReply', { reply: `${smtpCode} ${text.trim()}` })];
  if (smtpCode === '550' && /country/i.test(text)) lines.push(t('compose.sendErrorCountryBlocked'));
  return lines;
}
