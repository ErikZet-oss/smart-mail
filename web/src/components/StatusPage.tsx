import type { ReactNode } from 'react';

type Props = {
  icon: ReactNode;
  tone?: 'neutral' | 'danger' | 'brand';
  code?: ReactNode;
  title: ReactNode;
  text: ReactNode;
  actions?: ReactNode;
  top?: ReactNode;
  textWidth?: number;
  'data-testid'?: string;
};

const CIRCLE = {
  neutral: 'bg-bg-muted text-text-secondary',
  danger: 'bg-danger-50 text-danger-600',
  brand: 'bg-brand-primary-50 text-brand-primary-600',
};

/** Layout of the system pages W16a–c and W17: centred icon circle, code, title, text, actions (Figma W16). */
export function StatusPage({
  icon,
  tone = 'neutral',
  code,
  title,
  text,
  actions,
  top,
  textWidth = 520,
  'data-testid': testId,
}: Props) {
  return (
    <main
      className="flex min-h-full flex-col items-center justify-center gap-4 bg-bg-subtle p-6 text-center"
      data-testid={testId}
    >
      {top}
      <div aria-hidden="true" className={`flex h-24 w-24 items-center justify-center rounded-full ${CIRCLE[tone]}`}>
        {icon}
      </div>
      {code ? <p className="type-caption text-text-secondary">{code}</p> : null}
      <h1 className="type-title text-text-primary">{title}</h1>
      <p className="type-body text-text-secondary" style={{ maxWidth: textWidth }}>
        {text}
      </p>
      {actions ? <div className="flex flex-wrap items-center justify-center gap-2">{actions}</div> : null}
    </main>
  );
}
