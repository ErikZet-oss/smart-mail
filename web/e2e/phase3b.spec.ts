import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3b — W12-13a Prepojenie and W12-13e Synchronizácia (admin, FEATURE_MONEY). Fictional data only.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    {
      id: '13',
      path: 'money',
      title: 'Money S4',
      subs: [
        { id: '13a', path: 'connection', title: 'Prepojenie' },
        { id: '13e', path: 'sync', title: 'Synchronizácia' },
      ],
    },
  ],
  paths: { money: '13' },
};
const ENTITIES = [
  { entity: 'companies', last_run_at: '2026-10-30T20:00:00Z', last_full_at: null, status: 'ok', error: null, rows: 20 },
  { entity: 'persons', last_run_at: '2026-10-30T20:00:00Z', last_full_at: null, status: 'ok', error: null, rows: 41 },
  { entity: 'codebooks', last_run_at: null, last_full_at: null, status: null, error: null, rows: 0 },
];
const BASE = {
  'GET /api/auth/me': { body: ADMIN },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
  'GET /api/settings/nav': { body: NAV },
  'GET /api/system/maintenance': { body: { active: false, until: null } },
};

test('3b 13a shows the mock agenda, read-only writes, and the bridge-down state', async ({ page }, info) => {
  let up = true;
  await mockApi(page, {
    ...BASE,
    'GET /api/settings/money/writes': { body: { enabled: false, key_configured: true } },
    'GET /api/settings/money/status': () => ({
      body: {
        enabled: true,
        reachable: up,
        error: up ? null : 'money_unavailable',
        backend: 'mock',
        agenda: 'TEST',
        bridge_version: '0.2.0',
        money_version: up ? 'mock' : null,
        latency_ms: up ? 12 : null,
        writes_enabled: false,
        entities: ENTITIES,
      },
    }),
  });
  await page.goto('/settings/money/connection');
  const panel = page.getByTestId('settings-money-connection');
  await expect(panel.getByTestId('money-reachable')).toHaveText('Money Bridge pripojený');
  await expect(panel.getByTestId('money-agenda')).toHaveText('TEST agenda · simulované Money (vymyslené údaje)');
  await expect(panel).toContainText('most zápisy neprijíma');
  await expect(panel.getByRole('switch', { name: 'Zápisy do Money povolené ⚠' })).not.toBeChecked();
  await expect(panel.getByRole('table')).toContainText('Firmy');
  await shot(page, `phase3b-13a-${info.project.name}`);
  up = false;
  await panel.getByRole('button', { name: 'Otestovať' }).click();
  await expect(panel.getByTestId('money-reachable')).toHaveText('Money S4 je nedostupné');
  await expect(page.getByRole('alert')).toContainText('Pošta funguje ďalej');
});

test('3b 13e interval, sync now and history', async ({ page }, info) => {
  const saved: unknown[] = [];
  let running = false;
  const history = [
    {
      entity: 'companies',
      at: '2026-10-30T20:00:00Z',
      full: true,
      status: 'ok',
      changed: 20,
      deactivated: 0,
      error: null,
      duration_ms: 1200,
    },
    {
      entity: 'persons',
      at: '2026-10-30T19:45:00Z',
      full: true,
      status: 'error',
      changed: 0,
      deactivated: 0,
      error: 'money_unavailable',
      duration_ms: 300,
    },
  ];
  let interval = 15;
  await mockApi(page, {
    ...BASE,
    'GET /api/settings/money/sync': () => ({ body: { interval_min: interval, running, history } }),
    'PUT /api/settings/money/sync': (payload) => {
      saved.push(payload);
      interval = (payload as { interval_min: number }).interval_min;
      return { body: { interval_min: interval, running, history } };
    },
    'POST /api/settings/money/sync-now': () => {
      running = true;
      return { status: 202, body: { queued: true } };
    },
  });
  await page.goto('/settings/money/sync');
  const panel = page.getByTestId('settings-money-sync');
  const table = panel.getByTestId('money-sync-history');
  await expect(table).toContainText('Firmy · celá');
  await expect(table).toContainText('money_unavailable'); // error code chip (Figma W12-13e)
  await shot(page, `phase3b-13e-${info.project.name}`);
  await panel.getByLabel('Interval synchronizácie').selectOption('30');
  await expect.poll(() => saved.at(-1)).toEqual({ interval_min: 30 });
  await panel.getByRole('button', { name: 'Synchronizovať teraz' }).click();
  await expect(panel.getByTestId('money-sync-progress')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Synchronizovať teraz' })).toBeDisabled();
});
