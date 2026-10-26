import type { SettingsField } from './schema';

type Props = {
  field: SettingsField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
};

export function SettingsFieldControl({ field, value, onChange, disabled }: Props) {
  const v = value ?? field.default ?? '';
  if (field.control === 'info') {
    return (
      <p className="type-small rounded-sm bg-bg-subtle px-3 py-2 text-text-secondary">{field.help ?? field.label}</p>
    );
  }
  if (field.control === 'switch') {
    return (
      <label className="flex items-center gap-2 type-body text-text-primary">
        <input
          type="checkbox"
          checked={Boolean(v)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {field.label}
      </label>
    );
  }
  if (field.control === 'segmented' || field.control === 'select') {
    return (
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{field.label}</span>
        <select
          className="type-body h-9 rounded-sm border border-border-default bg-bg-canvas px-2"
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
        {field.help ? <span className="type-caption text-text-tertiary">{field.help}</span> : null}
      </label>
    );
  }
  if (field.control === 'slider') {
    const min = Number(field.validation?.min ?? 0);
    const max = Number(field.validation?.max ?? 30);
    const step = Number(field.validation?.step ?? 5);
    return (
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">
          {field.label}: {String(v)} s
        </span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={Number(v)}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {field.help ? <span className="type-caption text-text-tertiary">{field.help}</span> : null}
      </label>
    );
  }
  if (field.control === 'textarea') {
    return (
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{field.label}</span>
        <textarea
          className="type-body min-h-[96px] rounded-sm border border-border-default px-3 py-2"
          value={String(v)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }
  return (
    <label className="flex flex-col gap-1">
      <span className="type-label text-text-secondary">{field.label}</span>
      <input
        type={field.control === 'email' ? 'email' : field.control === 'tel' ? 'tel' : 'text'}
        className="type-body h-9 rounded-sm border border-border-default px-3"
        value={String(v)}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      {field.help ? <span className="type-caption text-text-tertiary">{field.help}</span> : null}
    </label>
  );
}
