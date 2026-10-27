import { CircleAlert, Landmark, MailWarning, ShieldAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** Note codes from classify / phishing_signals (AI_ASSISTANT §9 / UX_SPEC SecurityBanner). */
export type SecurityNoteCode =
  | 'security_dmarc_fail'
  | 'security_spf_fail'
  | 'security_display_spoof'
  | 'security_iban_change'
  | 'attachment_unscanned';

const ORDER: SecurityNoteCode[] = [
  'security_iban_change',
  'security_display_spoof',
  'security_dmarc_fail',
  'security_spf_fail',
  'attachment_unscanned',
];

const META: Record<SecurityNoteCode, { icon: typeof ShieldAlert; kind: 'danger' | 'warning' }> = {
  security_iban_change: { icon: Landmark, kind: 'danger' },
  security_display_spoof: { icon: ShieldAlert, kind: 'danger' },
  security_dmarc_fail: { icon: MailWarning, kind: 'danger' },
  security_spf_fail: { icon: MailWarning, kind: 'warning' },
  attachment_unscanned: { icon: CircleAlert, kind: 'warning' },
};

type Props = {
  notes: string[];
};

/** Molecules › SecurityBanner — phishing / IBAN / DMARC (no reply cards in 2b). */
export function SecurityBanner({ notes }: Props) {
  const { t } = useTranslation();
  const codes = ORDER.filter((code) => notes.includes(code));
  if (codes.length === 0) return null;
  return (
    <div className="mb-4 flex flex-col gap-2" data-testid="security-banners">
      {codes.map((code) => {
        const meta = META[code];
        const Icon = meta.icon;
        const danger = meta.kind === 'danger';
        return (
          <div
            key={code}
            role="alert"
            data-testid={`security-${code}`}
            className={`flex items-start gap-2.5 border-l-[3px] px-4 py-2.5 ${
              danger
                ? 'border-danger-600 bg-danger-50 text-text-primary'
                : 'border-warning-600 bg-warning-50 text-warning-700'
            }`}
          >
            <Icon
              size={18}
              aria-hidden="true"
              className={`mt-0.5 shrink-0 ${danger ? 'text-danger-600' : 'text-warning-600'}`}
            />
            <p className="type-small min-w-0 flex-1">{t(`ai.security.${code}`)}</p>
          </div>
        );
      })}
    </div>
  );
}
