import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';

type Props = InputHTMLAttributes<HTMLInputElement> & {
  icon: ReactNode;
  invalid?: boolean;
  /** Trailing control inside the field (show/hide password). */
  trailing?: ReactNode;
};

/** Figma `LoginField`. Desktop (W1): 40 px with a leading 40 × 40 icon box like Roundcube's login. Mobile (M-W1):
 * 36 px `Input` with an inline 16 px icon. */
export const LoginField = forwardRef<HTMLInputElement, Props>(function LoginField(
  { icon, invalid = false, trailing, disabled, className = '', ...input },
  ref,
) {
  const border = invalid
    ? 'border-danger-600'
    : 'border-border-default sm:border-border-strong focus-within:border-brand-primary-500';
  return (
    <div
      className={`flex h-9 w-full items-stretch overflow-hidden rounded-sm border bg-bg-canvas focus-within:ring-2 focus-within:ring-brand-primary-500 focus-within:ring-offset-2 focus-within:ring-offset-bg-canvas sm:h-10 ${border} ${
        disabled ? 'bg-bg-subtle opacity-60' : ''
      } ${className}`}
    >
      <span
        aria-hidden="true"
        className="flex shrink-0 items-center justify-center pl-2.5 text-text-secondary sm:w-10 sm:border-r sm:border-border-default sm:bg-bg-subtle sm:pl-0"
      >
        {icon}
      </span>
      <input
        ref={ref}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className="type-body min-w-0 flex-1 bg-transparent pl-2 pr-2.5 text-text-primary outline-none placeholder:text-text-tertiary disabled:cursor-not-allowed sm:px-3"
        {...input}
      />
      {trailing}
    </div>
  );
});
