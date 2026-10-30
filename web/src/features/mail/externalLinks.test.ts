import { describe, expect, it, vi } from 'vitest';
import type { MouseEvent } from 'react';

import { externalHref, openExternalLinkInNewTab } from './externalLinks';

function body(html: string): HTMLElement {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

describe('mail body links (pilot: external links must not replace Smart Mail)', () => {
  it('finds the http(s) link, also from a nested element', () => {
    const div = body(
      '<a href="https://www.example.com/x"><b>klik</b></a><a href="mailto:a@b.example">m</a><a href="#top">t</a>',
    );
    expect(externalHref(div.querySelector('b'))).toBe('https://www.example.com/x');
    expect(externalHref(div.querySelector('a[href^="mailto"]'))).toBeNull();
    expect(externalHref(div.querySelector('a[href="#top"]'))).toBeNull();
    expect(externalHref(div)).toBeNull();
  });

  it('opens the link in a new tab with noopener and stops the in-app navigation', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const div = body('<a href="https://www.example.com/cennik">cenník</a>');
    const preventDefault = vi.fn();
    const event = { target: div.querySelector('a'), button: 0, defaultPrevented: false, preventDefault };
    openExternalLinkInNewTab(event as unknown as MouseEvent<HTMLElement>);
    expect(preventDefault).toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith('https://www.example.com/cennik', '_blank', 'noopener,noreferrer');
    open.mockRestore();
  });

  it('leaves mailto links and other clicks alone', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const div = body('<a href="mailto:a@b.example">m</a>');
    const preventDefault = vi.fn();
    const event = { target: div.querySelector('a'), button: 0, defaultPrevented: false, preventDefault };
    openExternalLinkInNewTab(event as unknown as MouseEvent<HTMLElement>);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });
});
