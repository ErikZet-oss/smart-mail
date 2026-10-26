import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';

type Props = InputHTMLAttributes<HTMLInputElement> & {
  icon: ReactNode;
  invalid?: boolean;
  /** Trailing control inside the field (show/hide password). */
  trailing?: ReactNode;
};

/** Figma `LoginField`: 40 px, leading 40 × 40 icon box like Roundcube's login (SCREENS_SPEC W1). */
export const LoginField = forwardRef<HTMLInputElement, Props>(function LoginField(
  { icon, invalid = false, trailing, disabled, className = '', ...input },
  ref,
) {
  const border = invalid ? 'border-danger-600' : 'border-border-strong focus-within:border-brand-primary-500';
  return (
    <div
      className={`flex h-10 w-full items-stretch overflow-hidden rounded-sm border bg-bg-canvas focus-within:ring-2 focus-within:ring-brand-primary-500 focus-within:ring-offset-2 focus-within:ring-offset-bg-canvas ${border} ${
        disabled ? 'bg-bg-subtle opacity-60' : ''
      } ${className}`}
    >
      <span
        aria-hidden="true"
        className="flex w-10 shrink-0 items-center justify-center border-r border-border-default bg-bg-subtle text-text-secondary"
      >
        {icon}
      </span>
      <input
        ref={ref}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className="type-body min-w-0 flex-1 bg-transparent px-3 text-text-primary outline-none placeholder:text-text-tertiary disabled:cursor-not-allowed"
        {...input}
      />
      {trailing}
    </div>
  );
});
