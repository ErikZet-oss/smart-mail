import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

type Variant = 'primary' | 'secondary';
type Size = 'md' | 'lg';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
};

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-brand-primary-600 text-text-on-primary hover:bg-brand-primary-700 disabled:bg-brand-primary-400 disabled:hover:bg-brand-primary-400',
  secondary: 'border border-border-strong bg-bg-canvas text-text-primary hover:bg-bg-muted disabled:opacity-60',
};

const SIZE: Record<Size, string> = {
  md: 'h-8 px-3 type-label',
  lg: 'h-10 px-4 type-body-strong',
};

/** Figma `Button` (md 32 px, lg 40 px). */
export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', size = 'md', icon, className = '', children, ...button },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-sm transition-colors duration-[var(--motion-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500 disabled:cursor-not-allowed ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...button}
    >
      {icon}
      {children}
    </button>
  );
});
