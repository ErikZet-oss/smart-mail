import type { Locator, Page } from '@playwright/test';

/** #192: the value of a colour token (e.g. `--ai-600`) as the browser computes it, `rgb(r, g, b)`. */
export async function tokenRgb(page: Page, token: string): Promise<string> {
  return page.evaluate((name) => {
    const probe = document.createElement('span');
    probe.style.color = `var(${name})`;
    document.body.appendChild(probe);
    const rgb = getComputedStyle(probe).color;
    probe.remove();
    return rgb;
  }, token);
}

export async function cssOf(el: Locator, prop: 'color' | 'border-top-color' | 'background-color'): Promise<string> {
  return el.evaluate((node, p) => getComputedStyle(node).getPropertyValue(p), prop);
}
