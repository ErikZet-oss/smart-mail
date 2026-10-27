/** Category color tokens for AI triage dots (AI_ASSISTANT §4 / Figma W2f). */

const CAT_DOT: Record<string, string> = {
  warning: 'bg-warning-400',
  success: 'bg-success-500',
  info: 'bg-info-500',
  danger: 'bg-danger-500',
  brand: 'bg-brand-primary-500',
  neutral: 'bg-text-tertiary',
};

const CAT_DOT_FALLBACK = 'bg-text-tertiary';

/** Fallback color tokens when the triage list has not loaded the category yet. */
export const CATEGORY_COLOR_TOKEN: Record<string, string> = {
  inquiry: 'warning',
  order: 'success',
  order_change: 'success',
  order_cancel: 'danger',
  invoice_request: 'info',
  supplier_document: 'danger',
  complaint: 'danger',
  shipping: 'info',
  payment: 'danger',
  document_request: 'warning',
  supplier_info: 'success',
  newsletter: 'brand',
  notification: 'info',
  spam: 'danger',
  internal: 'brand',
  other: 'neutral',
};

export function categoryDotClass(colorToken: string): string {
  return CAT_DOT[colorToken] ?? CAT_DOT_FALLBACK;
}
