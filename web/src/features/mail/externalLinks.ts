import type { MouseEvent } from 'react';

/** The http(s) URL of the link the click landed on inside a mail body, else null (mailto:, in-page anchors, text). */
export function externalHref(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  const link = target.closest('a[href]');
  if (!link) return null;
  const href = link.getAttribute('href') ?? '';
  return /^https?:\/\//i.test(href.trim()) ? href.trim() : null;
}

/**
 * Links in a received mail open in a new tab, so Smart Mail stays open (pilot; Roundcube does the same).
 * `noopener,noreferrer`: the page can't reach back into the app and doesn't learn our URL.
 */
export function openExternalLinkInNewTab(event: MouseEvent<HTMLElement>): void {
  if (event.defaultPrevented || event.button !== 0) return;
  const href = externalHref(event.target);
  if (!href) return;
  event.preventDefault();
  window.open(href, '_blank', 'noopener,noreferrer');
}
