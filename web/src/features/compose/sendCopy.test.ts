import { describe, expect, it } from 'vitest';

import { sendErrorMessage, sendErrorServerReply } from './sendCopy';

const t = (key: string, opts?: Record<string, unknown>) => (opts ? `${key}|${JSON.stringify(opts)}` : key);

describe('#69 sendErrorServerReply', () => {
  it('shows the server reply and the country hint for a 550 geo block', () => {
    const value = 'SMTPSenderRefused:550:Sending mail from your country (de) is not allowed';
    expect(sendErrorMessage(t, value)).toBe('compose.sendErrorRejected');
    expect(sendErrorServerReply(t, value)).toEqual([
      'compose.sendErrorServerReply|{"reply":"550 Sending mail from your country (de) is not allowed"}',
      'compose.sendErrorCountryBlocked',
    ]);
  });

  it('shows only the reply for other codes and nothing for internal reasons', () => {
    expect(sendErrorServerReply(t, 'SMTPDataError:554:Message rejected')).toHaveLength(1);
    expect(sendErrorServerReply(t, 'SMTPSenderRefused')).toEqual([]);
    expect(sendErrorServerReply(t, 'recipient_not_allowed:a@b.sk')).toEqual([]);
    expect(sendErrorServerReply(t, null)).toEqual([]);
  });
});
