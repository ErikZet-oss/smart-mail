import { ChevronDown } from 'lucide-react';
import { useId, type ReactNode } from 'react';

import type { SettingsField } from './schema';

type Props = {
  field: SettingsField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
};

const INPUT =
  'type-body h-[var(--size-input)] w-full rounded-sm border border-border-default bg-bg-canvas px-3 text-text-primary focus:border-brand-primary-500 focus:outline-none disabled:bg-bg-subtle disabled:text-text-tertiary';

/**
 * Figma settings `Field` row (W12-01a, node 62:51295): label column 300 px (+ help text) and a 440 px control column.
 * On phones (M9) the label stays left and the control right, as in the M9 frames.
 */
function Row({
  labelId,
  label,
  help,
  htmlFor,
  align = 'center',
  children,
}: {
  labelId: string;
  label: ReactNode;
  help?: string | null;
  htmlFor?: string;
  align?: 'center' | 'stack';
  children: ReactNode;
}) {
  const Label = htmlFor ? 'label' : 'span';
  return (
    <div
      className={`flex gap-x-6 gap-y-2 sm:grid sm:grid-cols-[300px_minmax(0,440px)] sm:items-center ${
        align === 'stack' ? 'flex-col' : 'items-center justify-between'
      }`}
    >
      <div className="min-w-0">
        <Label id={labelId} htmlFor={htmlFor} className="type-small block text-text-primary">
          {label}
        </Label>
        {help ? <p className="type-caption mt-0.5 font-normal text-text-secondary">{help}</p> : null}
      </div>
      <div className={align === 'stack' ? 'w-full' : 'flex min-w-0 justify-end sm:justify-start'}>{children}</div>
    </div>
  );
}

export function SettingsFieldControl({ field, value, onChange, disabled }: Props) {
  const id = useId();
  const labelId = `${id}-label`;
  const v = value ?? field.default ?? '';
  if (field.control === 'info') {
    return (
      <p className="type-small rounded-sm bg-bg-subtle px-3 py-2 text-text-secondary">{field.help ?? field.label}</p>
    );
  }
  if (field.control === 'switch') {
    const checked = Boolean(v);
    return (
      <Row labelId={labelId} label={field.label} help={field.help}>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          aria-labelledby={labelId}
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
      </Row>
    );
  }
  if (field.control === 'segmented') {
    return (
      <Row labelId={labelId} label={field.label} help={field.help}>
        <div
          role="radiogroup"
          aria-labelledby={labelId}
          className="inline-flex h-8 shrink-0 items-center rounded-sm bg-bg-muted p-0.5"
        >
          {(field.options ?? []).map((opt) => {
            const selected = String(v) === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => onChange(opt.value)}
                className={`type-small h-7 whitespace-nowrap rounded-xs px-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500 disabled:opacity-60 ${
                  selected
                    ? 'border border-border-default bg-bg-canvas font-semibold text-text-primary shadow-e1'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </Row>
    );
  }
  if (field.control === 'select') {
    return (
      <Row labelId={labelId} label={field.label} help={field.help} htmlFor={id}>
        <div className="relative w-full max-w-[440px]">
          <select
            id={id}
            className={`${INPUT} appearance-none pr-9`}
            value={String(v)}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          >
            {(field.options ?? []).map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown
            size={16}
            aria-hidden
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary"
          />
        </div>
      </Row>
    );
  }
  if (field.control === 'slider') {
    const min = Number(field.validation?.min ?? 0);
    const max = Number(field.validation?.max ?? 30);
    const step = Number(field.validation?.step ?? 5);
    return (
      <Row labelId={labelId} label={field.label} help={field.help} htmlFor={id}>
        <div className="flex w-full max-w-[440px] items-center gap-3">
          <input
            id={id}
            type="range"
            min={min}
            max={max}
            step={step}
            value={Number(v)}
            disabled={disabled}
            onChange={(event) => onChange(Number(event.target.value))}
            className="min-w-0 flex-1 accent-brand-primary-600"
          />
          <span className="type-small w-10 shrink-0 text-right tabular-nums text-text-primary">{String(v)} s</span>
        </div>
      </Row>
    );
  }
  if (field.control === 'textarea') {
    return (
      <Row labelId={labelId} label={field.label} help={field.help} htmlFor={id} align="stack">
        <textarea
          id={id}
          className={`${INPUT} h-auto min-h-[96px] py-2`}
          value={String(v)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      </Row>
    );
  }
  return (
    <Row labelId={labelId} label={field.label} help={field.help} htmlFor={id} align="stack">
      <input
        id={id}
        type={field.control === 'email' ? 'email' : field.control === 'tel' ? 'tel' : 'text'}
        className={INPUT}
        value={String(v)}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </Row>
  );
}
