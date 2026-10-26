import { CircleX, Info, Sparkles, TriangleAlert, WifiOff, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export type BannerKind = 'offline' | 'info' | 'warning' | 'ai' | 'danger';

const STYLE: Record<BannerKind, { box: string; icon: ReactNode; text: string; action: string }> = {
  offline: {
    box: 'bg-bg-muted border-text-secondary',
    icon: <WifiOff size={18} aria-hidden="true" className="shrink-0 text-text-secondary" />,
    text: 'text-text-primary',
    action: 'text-brand-primary-600',
  },
  info: {
    box: 'bg-brand-primary-50 border-brand-primary-600',
    icon: <Info size={18} aria-hidden="true" className="shrink-0 text-brand-primary-600" />,
    text: 'text-brand-primary-700',
    action: 'text-brand-primary-600',
  },
  warning: {
    box: 'bg-warning-50 border-warning-600',
    icon: <TriangleAlert size={18} aria-hidden="true" className="shrink-0 text-warning-600" />,
    text: 'text-warning-700',
    action: 'text-warning-700',
  },
  ai: {
    box: 'bg-ai-50 border-ai-600',
    icon: <Sparkles size={18} aria-hidden="true" className="shrink-0 text-ai-600" />,
    text: 'text-text-primary',
    action: 'text-ai-600',
  },
  danger: {
    box: 'bg-danger-50 border-danger-600',
    icon: <CircleX size={18} aria-hidden="true" className="shrink-0 text-danger-600" />,
    text: 'text-text-primary',
    action: 'text-danger-600',
  },
};

type Props = {
  kind: BannerKind;
  message: string;
  action?: { label: string; onClick: () => void; disabled?: boolean };
  onClose?: () => void;
};

/** G6 Banner (top of the content area, 3 px left border). */
export function Banner({ kind, message, action, onClose }: Props) {
  const { t } = useTranslation();
  const style = STYLE[kind];
  return (
    <div
      role={kind === 'danger' || kind === 'warning' ? 'alert' : 'status'}
      className={`flex items-center gap-2.5 border-l-[3px] px-4 py-2.5 ${style.box}`}
    >
      {style.icon}
      <p className={`type-small min-w-0 flex-1 ${style.text}`}>{message}</p>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          disabled={action.disabled}
          className={`type-label shrink-0 rounded-xs hover:underline disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500 ${style.action}`}
        >
          {action.label}
        </button>
      ) : null}
      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close')}
          className="shrink-0 rounded-xs text-text-secondary hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
        >
          <X size={16} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
