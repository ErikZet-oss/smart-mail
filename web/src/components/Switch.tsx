import type { ReactNode } from 'react';

type Props = { checked: boolean; onChange: (checked: boolean) => void; label: ReactNode; disabled?: boolean };

/** Figma `Switch` 32 × 18 with a small label. */
export function Switch({ checked, onChange, label, disabled }: Props) {
  return (
    <label className="type-small inline-flex cursor-pointer items-center gap-2.5 text-text-primary">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-[18px] w-8 shrink-0 rounded-full transition-colors duration-[var(--motion-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500 disabled:opacity-60 ${
          checked ? 'bg-brand-primary-600' : 'bg-border-strong'
        }`}
      >
        <span
          className={`absolute top-0.5 size-3.5 rounded-full bg-bg-canvas transition-[left] duration-[var(--motion-hover)] ${
            checked ? 'left-4' : 'left-0.5'
          }`}
        />
      </button>
      {label}
    </label>
  );
}
