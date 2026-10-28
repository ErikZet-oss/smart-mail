import AxeBuilder from '@axe-core/playwright';
import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Phase 1 visual parity with Figma (docs/FIGMA_MAP.md W12): settings navigation, search, admin group. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const SIGNED_IN_ADMIN = { 'GET /api/auth/me': { body: ADMIN }, 'GET /api/auth/persons': { body: ME_PICKER } };

/** Same shape and order as GET /api/settings/nav for an admin (settings_schema.json, Phase 1 sections). */
const NAV_ADMIN = {
  sections: [
    {
      id: '01',
      path: 'preferences',
      title: 'Nastavenia',
      subs: [
        { id: '01a', path: 'ui', title: 'Používateľské rozhranie' },
        { id: '01b', path: 'mailbox-view', title: 'Zobrazenie schránky' },
        { id: '01c', path: 'reading', title: 'Zobrazovanie správ' },
        { id: '01d', path: 'composing', title: 'Vytváranie správ' },
        { id: '01e', path: 'shortcuts', title: 'Klávesové skratky' },
      ],
    },
    { id: '02', path: 'folders', title: 'Priečinky', subs: [] },
    {
      id: '03',
      path: 'identity',
      title: 'Identity a Môj profil',
      subs: [
        { id: '03a', path: 'list', title: 'Identity' },
        { id: '03b', path: 'profile', title: 'Môj profil' },
      ],
    },
    { id: '04', path: 'responses', title: 'Odpovede', subs: [] },
    { id: '05', path: 'filters', title: 'Filtre', subs: [] },
    { id: '06', path: 'vacation', title: 'Mimo kancelárie', subs: [] },
    { id: '07', path: 'ai', title: 'AI asistent', subs: [] },
    { id: '09', path: 'security', title: 'Bezpečnosť', subs: [] },
    { id: '09b', path: 'provider', title: 'Nastavenia e-mail schránky', subs: [] },
    { id: '10', path: 'users', title: 'Používatelia a role', subs: [] },
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [
        { id: '11a', path: 'details', title: 'Údaje' },
        { id: '11b', path: 'people', title: 'Osoby' },
        { id: '11c', path: 'signature', title: 'Podpis' },
        { id: '11d', path: 'login', title: 'Prihlasovanie' },
        { id: '11e', path: 'money', title: 'Money' },
      ],
    },
    { id: '12', path: 'mailboxes', title: 'Schránky', subs: [] },
  ],
};

const PREFS = {
  ui: { theme: 'system', classic: false },
  list: { density: 'compact', mode: 'list', page_size: 50, show_ai_summary: true },
  reading: {},
  composing: { undo_send_seconds: 10 },
  shortcuts: {},
};

/** Fictional branch (no real people, phones or addresses). */
const BRANCHES = [
  {
    id: 'br-1',
    name: 'Pobočka Testov',
    address: 'Skúšobná 1, 000 00 Testov',
    phone: '+421 900 000 000',
    hours: 'Po–Pi 7:00–15:30',
    mailbox_id: 'mb-1',
    signature_template_html: { sk: '<p>{{meno}}</p>' },
    people: [{ id: 'p1', first_name: 'Jana', last_name: 'Testová', role: 'sales', active: true }],
  },
];

test.describe('Phase 1 visual — W12 settings navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN_ADMIN,
      'GET /api/settings/nav': { body: NAV_ADMIN },
      'GET /api/settings/preferences': { body: PREFS },
      'GET /api/settings/admin/branches': { body: BRANCHES },
    });
  });

  test('W12-01a nav with icons, SPRÁVA group, sub list and breadcrumb', async ({ page }) => {
    await page.goto('/settings/preferences/ui');
    const nav = page.getByRole('navigation', { name: 'Sekcie nastavení' });
    await expect(nav.getByRole('link', { name: 'Môj profil' })).toBeVisible();
    await expect(nav.getByText('Správa', { exact: true })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Nastavenia', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('link', { name: 'Zobrazenie schránky' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1, name: 'Používateľské rozhranie' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Podľa systému' })).toHaveAttribute('aria-checked', 'true');
    await shot(page, 'visual-W12-01a-ui');
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    const serious = axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
    await page.getByRole('link', { name: 'Zobrazenie schránky' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Zobrazenie schránky' })).toBeVisible();
    await shot(page, 'visual-W12-01b-mailbox-view');
  });

  test('W12 Hľadanie v nastaveniach filters sections on the client', async ({ page }) => {
    await page.goto('/settings/preferences/ui');
    const search = page.getByRole('combobox', { name: 'Hľadať v nastaveniach' });
    await search.fill('podpis');
    const results = page.getByRole('listbox', { name: 'Výsledky hľadania v nastaveniach' });
    await expect(results.getByRole('option', { name: /Podpis.*Pobočky a osoby/ })).toBeVisible();
    await shot(page, 'visual-W12-search');
    await search.press('Enter');
    await expect(page).toHaveURL(/\/settings\/branches\/signature$/);
    await expect(page.getByRole('tab', { name: 'Podpis' })).toHaveAttribute('aria-selected', 'true');
  });

  test('W12-11a Pobočky a osoby: SPRÁVA breadcrumb and tabs', async ({ page }) => {
    await page.goto('/settings/branches/details');
    await expect(page.getByRole('tab', { name: 'Údaje' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('navigation', { name: 'Umiestnenie v nastaveniach' })).toContainText('Správa');
    await shot(page, 'visual-W12-11a-branch');
  });
});
