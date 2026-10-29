import { ApiError } from '../../lib/api';

export const INPUT =
  'type-body h-[var(--size-input)] w-full rounded-sm border border-border-default bg-bg-canvas px-3 text-text-primary focus:border-brand-primary-500 focus:outline-none disabled:bg-bg-subtle disabled:text-text-tertiary';

/** Error code of a Settings 10/11 call → Slovak text (`settings.users.errors.*`). */
export function adminErrorText(t: (key: string, options?: Record<string, unknown>) => string, error: unknown) {
  const code = error instanceof ApiError ? error.detail.code : 'generic';
  return t(`settings.users.errors.${code}`, { defaultValue: t('settings.users.errors.generic') });
}
