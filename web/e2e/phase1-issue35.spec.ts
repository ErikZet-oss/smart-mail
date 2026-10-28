import { expect, mockApi, test } from './fixtures';

/** Fictional branch login. Admin and sales see different settings navs from the API. */
const erik = {
  id: 'p-erik',
  first_name: 'Erik',
  last_name: 'Testový',
  full_name: 'Erik Testový',
  role: 'admin',
  function: 'správca',
  is_manager: true,
};
const jan = {
  id: 'p-jan',
  first_name: 'Ján',
  last_name: 'Testový',
  full_name: 'Ján Testový',
  role: 'sales',
  function: 'obchod',
  is_manager: false,
};
type Person = typeof erik;

const personalSections = [
  {
    id: '01',
    path: 'preferences',
    title: 'Nastavenia',
    subs: [{ id: '01a', path: 'ui', title: 'Používateľské rozhranie' }],
  },
  {
    id: '03',
    path: 'identity',
    title: 'Identity',
    subs: [{ id: '03b', path: 'profile', title: 'Môj profil' }],
  },
];
const adminSections = [
  {
    id: '11',
    path: 'branches',
    title: 'Pobočky a osoby',
    subs: [{ id: '11a', path: 'details', title: 'Údaje' }],
  },
];
const navFor = (admin: boolean) => ({ sections: admin ? [...personalSections, ...adminSections] : personalSections });
const me = (person: Person) => ({
  account_id: 'a-fa',
  email: 'fa@smartmail.test',
  kind: 'branch',
  branch: 'Testov',
  person,
  needs_person: false,
  read_only: false,
});
const picker = (current: Person) => ({
  branch: 'Testov',
  email: 'fa@smartmail.test',
  persons: [erik, jan],
  current_person_id: current.id,
  last_person_id: current.id,
  idle_ask_minutes: null,
});
const profile = (person: Person) => ({
  id: person.id,
  first_name: person.first_name,
  last_name: person.last_name,
  function: person.function,
  phone: null,
  mobile: null,
  personal_email: null,
  languages: ['sk'],
  style_guide: null,
  role: person.role,
  signature_preview_html: `<p>${person.first_name}</p>`,
});
const PREFS = {
  ui: { theme: 'system', classic: false },
  list: { density: 'compact', mode: 'list', page_size: 50, show_ai_summary: true },
  reading: {},
  composing: { undo_send_seconds: 10 },
  shortcuts: {},
};

test.describe('Pilot #35 person cache', () => {
  test('test_switch_person_refreshes_settings_nav', async ({ page }) => {
    let current = erik;
    await mockApi(page, {
      'GET /api/auth/me': () => ({ body: me(current) }),
      'GET /api/auth/persons': () => ({ body: picker(current) }),
      'POST /api/auth/person': (body: unknown) => {
        const id = (body as { person_id?: string }).person_id;
        current = id === jan.id ? jan : erik;
        return { body: me(current) };
      },
      'GET /api/settings/nav': () => ({ body: navFor(current.role === 'admin') }),
      'GET /api/settings/preferences': { body: PREFS },
    });
    await page.goto('/settings');
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toBeVisible();
    await expect(page.getByText('Správa', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Pracuje: Erik Testový' }).click();
    await page.getByRole('menuitemradio', { name: /Ján Testový/ }).click();
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toHaveCount(0);
    await expect(page.getByText('Správa', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Pracuje: Ján Testový' })).toBeVisible();

    await page.getByRole('button', { name: 'Pracuje: Ján Testový' }).click();
    await page.getByRole('menuitemradio', { name: /Erik Testový/ }).click();
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toBeVisible();
    await expect(page.getByText('Správa', { exact: true })).toBeVisible();
  });

  test('test_login_after_session_revoke_clears_cache', async ({ page }) => {
    let phase: 'admin' | 'revoked' | 'sales' = 'admin';
    let releaseNav = () => {};
    let navHold: Promise<void> = Promise.resolve();
    await mockApi(page, {
      'GET /api/auth/me': () => ({ body: me(phase === 'sales' ? jan : erik) }),
      'GET /api/auth/persons': () => ({ body: picker(phase === 'sales' ? jan : erik) }),
      'GET /api/settings/preferences': { body: PREFS },
      'GET /api/settings/nav': async () => {
        if (phase === 'sales') await navHold;
        return { body: navFor(phase !== 'sales') };
      },
      'GET /api/settings/profile': () => {
        if (phase === 'revoked') {
          return { status: 401, body: { detail: { code: 'unauthenticated', reason: 'expired' } } };
        }
        return { body: profile(phase === 'sales' ? jan : erik) };
      },
      'POST /api/auth/login': () => ({ body: { next: 'app', me: me(jan) } }),
    });
    await page.goto('/settings');
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toBeVisible();

    phase = 'revoked';
    await page.getByRole('link', { name: 'Môj profil' }).click();
    await expect(page).toHaveURL(/\/login/);

    navHold = new Promise<void>((resolve) => {
      releaseNav = () => resolve();
    });
    phase = 'sales';
    await page.getByLabel('E-mail').fill('fa@smartmail.test');
    await page.getByLabel('Heslo', { exact: true }).fill('heslo-fiktivne');
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();

    await expect(page.getByRole('heading', { name: 'Môj profil' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toHaveCount(0);
    await expect(page.getByText('Správa', { exact: true })).toHaveCount(0);

    releaseNav();
    await expect(page.getByRole('link', { name: 'Môj profil' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Pobočky a osoby' })).toHaveCount(0);
    await expect(page.getByText('Správa', { exact: true })).toHaveCount(0);
  });
});
