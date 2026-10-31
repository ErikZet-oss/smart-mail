import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3f — 13a „Zápisy do Money povolené“ ⚠ and 13d Aktivity. Fictional data only.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    {
      id: '13',
      path: 'money',
      title: 'Money S4',
      subs: [
        { id: '13a', path: 'connection', title: 'Prepojenie' },
        { id: '13d', path: 'activities', title: 'Aktivity' },
      ],
    },
  ],
  paths: { money: '13' },
};
const BASE = {
  'GET /api/auth/me': { body: ADMIN },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
  'GET /api/settings/nav': { body: NAV },
  'GET /api/system/maintenance': { body: { active: false, until: null } },
};
const TYPES = [
  { id: 't1', code: 'EMAIL', name: 'E-mail odoslaný' },
  { id: 't2', code: 'UPOM', name: 'Upomienka' },
];

test('3f 13a: the writes switch asks for the password, then turns on', async ({ page }) => {
  let reauthed = false;
  let enabled = false;
  const saved: unknown[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/settings/money/status': {
      body: {
        enabled: true,
        reachable: true,
        error: null,
        backend: 'mock',
        agenda: 'TEST',
        bridge_version: '0.3.0',
        money_version: 'mock',
        latency_ms: 5,
        writes_enabled: true,
        entities: [],
      },
    },
    'GET /api/settings/money/writes': () => ({ body: { enabled, key_configured: true } }),
    'PUT /api/settings/money/writes': (payload) => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      saved.push(payload);
      enabled = (payload as { enabled: boolean }).enabled;
      return { body: { enabled, key_configured: true } };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/money/connection');
  const sw = page.getByRole('switch', { name: 'Zápisy do Money povolené ⚠' });
  await expect(page.getByTestId('settings-money-connection')).toContainText('most prijíma podpísané zápisy');
  await sw.click();
  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect.poll(() => saved).toEqual([{ enabled: true }]);
  await expect(sw).toBeChecked();
});

test('3f 13d: activity types from Money, failed writes with a manual retry', async ({ page }, info) => {
  const saved: unknown[] = [];
  const retried: string[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/settings/money/activities': {
      body: {
        enabled: true,
        type_email: null,
        type_reminder: null,
        writes_enabled: true,
        types: TYPES,
        failed: [
          {
            draft_id: 'd-1',
            at: '2026-10-31T08:00:00Z',
            error: 'money_unavailable',
            kind: 'email',
            invoices: ['FV2600042'],
          },
        ],
      },
    },
    'PUT /api/settings/money/activities': (payload) => {
      saved.push(payload);
      return {
        body: { ...(payload as object), writes_enabled: true, types: TYPES, failed: [] },
      };
    },
    'POST /api/settings/money/activities/d-1/retry': () => {
      retried.push('d-1');
      return { status: 202, body: { queued: true } };
    },
  });
  await page.goto('/settings/money/activities');
  const panel = page.getByTestId('settings-money-activities');
  await expect(panel.getByText('Vyberte oba typy aktivity.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Uložiť' })).toBeDisabled();
  await panel.getByLabel('Typ aktivity – odoslaný e-mail s faktúrou').selectOption('t1');
  await panel.getByLabel('Typ aktivity – upomienka').selectOption('t2');
  const failed = panel.getByTestId('money-activities-failed');
  await expect(failed).toContainText('FV2600042');
  await expect(failed).toContainText('Money alebo Money most neodpovedá.');
  await shot(page, `phase3f-13d-${info.project.name}`);
  await failed.getByRole('button', { name: 'Skúsiť znova' }).click();
  await expect.poll(() => retried).toEqual(['d-1']);
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => saved).toEqual([{ enabled: true, type_email: 't1', type_reminder: 't2' }]);
});
