import { X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from './Button';

type ShellProps = {
  title: string;
  width: number;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
  onSubmit?: () => void;
};

const FOCUSABLE = 'button:not([disabled]),input:not([disabled]),select,textarea,[href],[tabindex]:not([tabindex="-1"])';

/** G5 modal shell: overlay, title row with close, Esc closes, focus is trapped and returned to the opener. */
export function Dialog({ title, width, onClose, children, footer, onSubmit }: ShellProps) {
  return (
    <DialogShell title={title} width={width} onClose={onClose} footer={footer} onSubmit={onSubmit}>
      {children}
    </DialogShell>
  );
}

function DialogShell({ title, width, onClose, children, footer, onSubmit }: ShellProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const box = ref.current;
    (box?.querySelector<HTMLElement>('[data-autofocus]') ?? box?.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    return () => opener?.focus();
  }, []);

  function onKey(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit?.();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4">
      <form
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        onSubmit={submit}
        style={{ width }}
        className="flex max-w-full flex-col gap-4 rounded-lg bg-bg-canvas p-6 shadow-e3"
      >
        <div className="flex items-start gap-3">
          <h2 id={titleId} className="type-heading min-w-0 flex-1 break-words text-text-primary">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="shrink-0 rounded-xs text-text-secondary hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
        <div className="flex justify-end gap-2">{footer}</div>
      </form>
    </div>
  );
}

type ConfirmProps = {
  title: string;
  body: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
};

/** G5 Confirm: title = action + object, body = consequence, Zrušiť / red primary. */
export function ConfirmDialog({ title, body, confirmLabel, busy = false, onConfirm, onClose }: ConfirmProps) {
  const { t } = useTranslation();
  return (
    <DialogShell
      title={title}
      width={440}
      onClose={onClose}
      onSubmit={onConfirm}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} data-autofocus>
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            disabled={busy}
            className="bg-danger-600 hover:bg-danger-600 hover:brightness-95 disabled:bg-danger-600 disabled:opacity-60"
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="type-body text-text-secondary">{body}</p>
    </DialogShell>
  );
}

type PromptProps = {
  title: string;
  label: string;
  initial?: string;
  submitLabel: string;
  busy?: boolean;
  error?: string | null;
  onSubmit: (value: string) => void;
  onClose: () => void;
};

/** G5 Form dialog with one text field (Nový podpriečinok, Premenovať). */
export function PromptDialog({ title, label, initial = '', submitLabel, busy, error, onSubmit, onClose }: PromptProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initial);
  const inputId = useId();
  const errorId = useId();
  const clean = value.trim();
  return (
    <DialogShell
      title={title}
      width={480}
      onClose={onClose}
      onSubmit={() => {
        if (clean) onSubmit(clean);
      }}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={busy || !clean}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={inputId} className="type-label text-text-primary">
          {label}
        </label>
        <input
          id={inputId}
          data-autofocus
          value={value}
          maxLength={200}
          onChange={(event) => setValue(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className={`type-body h-9 rounded-sm border bg-bg-canvas px-3 text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-brand-primary-500 ${
            error ? 'border-danger-600' : 'border-border-strong'
          }`}
        />
        {error ? (
          <p id={errorId} className="type-small text-danger-600">
            {error}
          </p>
        ) : null}
      </div>
    </DialogShell>
  );
}
