import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #212 — 13a on the PRODUCTION agenda: read-only label, locked writes switch, agenda switch and problems. Fictional.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    { id: '13', path: 'money', title: 'Money S4', subs: [{ id: '13a', path: 'connection', title: 'Prepojenie' }] },
  ],
  paths: { money: '13' },
};

test('#212 13a: Ostrá agenda – len čítanie, writes locked, switch banner and branch problems', async ({
  page,
}, info) => {
  let puts = 0;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/money/status': {
      body: {
        enabled: true,
        reachable: true,
        error: null,
        backend: 'api',
        agenda: 'PROD',
        bridge_version: '0.3.0',
        money_version: '1.15.11',
        latency_ms: 40,
        writes_enabled: false,
        entities: [],
        read_only: true,
        cache_agenda: 'PROD',
        agenda_changed_at: '2026-11-10T08:00:00Z',
        agenda_previous: 'TEST',
        resync_pending: true,
        problems: [
          { kind: 'branch', branch: 'Pobočka Fiktívna', field: 'money_centre_id' },
          { kind: 'email_links', count: 3 },
        ],
      },
    },
    'GET /api/settings/money/writes': { body: { enabled: false, key_configured: true, read_only: true } },
    'PUT /api/settings/money/writes': () => {
      puts += 1;
      return { status: 409, body: { detail: { code: 'prod_read_only' } } };
    },
  });
  await page.goto('/settings/money/connection');
  const panel = page.getByTestId('settings-money-connection');
  await expect(page.getByTestId('money-read-only')).toHaveText('Ostrá agenda – len čítanie');
  await expect(panel).toContainText('Agenda Money sa zmenila – údaje sa načítavajú znova');
  const problems = page.getByTestId('money-agenda-problems');
  await expect(problems).toContainText('Nastavenie pobočky odkazuje na položku, ktorá v Money neexistuje');
  await expect(problems).toContainText('Pobočka Fiktívna: stredisko');
  await expect(problems).toContainText('3 potvrdené priradenia e-mailov');
  await expect(page.getByRole('switch', { name: 'Zápisy do Money povolené ⚠' })).toBeDisabled();
  await expect(page.getByTestId('money-writes-locked')).toBeVisible();
  expect(puts).toBe(0);
  await shot(page, `issue212-13a-${info.project.name}`);
});
