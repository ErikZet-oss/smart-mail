import type { InputHTMLAttributes, ReactNode } from 'react';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode };

/** Figma `Checkbox` 16 px with a small label. */
export function Checkbox({ label, className = '', ...input }: Props) {
  return (
    <label className={`type-small inline-flex cursor-pointer items-center gap-2 text-text-primary ${className}`}>
      <input
        type="checkbox"
        className="h-4 w-4 cursor-pointer rounded-xs border-border-strong accent-brand-primary-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500"
        {...input}
      />
      {label}
    </label>
  );
}
