import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #116 — W12-07 Samostatnosť per login (D8) with the hard rule, and the read-only 17b overview.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    { id: '07', path: 'ai', title: 'AI asistent', subs: [] },
    {
      id: '17',
      path: 'ai-admin',
      title: 'AI – správa',
      subs: [
        { id: '17b', path: 'autonomy', title: 'Samostatnosť AI' },
        { id: '17d', path: 'style', title: 'Štýl a znalosti' },
      ],
    },
  ],
  paths: { ai: '07', 'ai-admin': '17' },
};
const ACTIONS = [
  { id: 'classify', level: 4, default: 4, max: 4, hard: false },
  { id: 'assign', level: 2, default: 2, max: 3, hard: false },
  { id: 'reply', level: 2, default: 2, max: 2, hard: true },
];

test('#116 autonomy matrix: send locked at 2, change needs the password', async ({ page }, info) => {
  let reauthed = false;
  const saved: unknown[] = [];
  let actions = ACTIONS;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/preferences': {
      body: { ui: { classic: false }, list: { show_ai_summary: true }, reading: {}, composing: {}, shortcuts: {} },
    },
    'GET /api/settings/ai/autonomy': () => ({ body: { actions } }),
    'PUT /api/settings/ai/autonomy': (payload) => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      saved.push(payload);
      const levels = (payload as { levels: Record<string, number> }).levels;
      actions = actions.map((a) => ({ ...a, level: levels[a.id] ?? a.level }));
      return { body: { actions } };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/ai');
  const matrix = page.getByTestId('ai-autonomy');
  await expect(matrix.getByLabel('Návrh odpovede: Urobiť a oznámiť')).toBeDisabled();
  await expect(matrix.getByLabel('Návrh odpovede: Urobiť potichu')).toBeDisabled();
  await expect(matrix.getByLabel('Návrh odpovede: Pripraviť na schválenie')).toBeChecked();
  await expect(matrix).toContainText('Odoslanie mimo firmy a zápis do Money vždy schvaľuje človek.');
  await shot(page, `issue116-autonomy-${info.project.name}`);

  await matrix.getByLabel('Pridelenie konverzácie kolegovi: Urobiť a oznámiť').click();
  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => saved.at(-1)).toEqual({ levels: { assign: 3 } });
  await expect(matrix.getByLabel('Pridelenie konverzácie kolegovi: Urobiť a oznámiť')).toBeChecked();
});

test('#116 17b overview is read-only', async ({ page }) => {
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/ai/autonomy': { body: { actions: ACTIONS } },
    'GET /api/settings/ai/autonomy/overview': {
      body: [
        {
          account_id: 'a1',
          email: 'nitra@smartsro.sk',
          kind: 'mailbox',
          levels: { classify: 4, assign: 2, reply: 1 },
          customized: true,
        },
      ],
    },
  });
  await page.goto('/settings/ai-admin/autonomy');
  const overview = page.getByTestId('settings-ai-autonomy-overview');
  await expect(overview).toContainText('nitra@smartsro.sk');
  await expect(overview.getByRole('row', { name: /Návrh odpovede/ })).toContainText('Len navrhnúť');
  await expect(overview.getByRole('radio')).toHaveCount(0);
});

test('#116 17a budget: env source until saved, save needs the password', async ({ page }, info) => {
  let reauthed = false;
  const saved: unknown[] = [];
  let limits = {
    provider: 'anthropic',
    region: null,
    models: [{ purpose: 'classify', model: 'claude-haiku-4-5' }],
    daily_budget_usd: '5.00',
    budget_source: 'env',
    env_budget_usd: '5.00',
    alert_pct: 80,
    on_exhausted: 'rules_only',
    retention_days: 90,
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': {
      body: {
        ...NAV,
        sections: [
          NAV.sections[0],
          { ...NAV.sections[1], subs: [{ id: '17a', path: 'limits', title: 'Poskytovateľ a rozpočet' }] },
        ],
      },
    },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/ai/limits': () => ({ body: limits }),
    'PUT /api/settings/ai/limits': (payload) => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      saved.push(payload);
      const p = payload as { daily_budget_usd: string };
      limits = { ...limits, daily_budget_usd: '12.00', budget_source: 'app' };
      expect(p.daily_budget_usd).toBe('12');
      return { body: limits };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/ai-admin/limits');
  const panel = page.getByTestId('settings-ai-limits');
  await expect(panel.getByTestId('budget-source')).toContainText('z nastavenia servera');
  await expect(panel).toContainText('claude-haiku-4-5');
  await shot(page, `issue116-limits-${info.project.name}`);
  await panel.getByLabel('Denný rozpočet (USD) ⚠').fill('12');
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => saved.length).toBe(1);
  await expect(page.getByTestId('budget-source')).toContainText('nastavené v aplikácii');
});

test('#116 17c categories: switch off, edit description, add custom, re-auth', async ({ page }, info) => {
  let reauthed = false;
  const saved: { categories: { id: string | null; label: string | null; enabled: boolean }[] }[] = [];
  const row = (id: string, label: string, extra: object = {}) => ({
    id,
    label,
    description: `popis ${label}`,
    default_description: `popis ${label}`,
    color: 'info',
    enabled: true,
    builtin: true,
    locked: id === 'other',
    count_30d: 3,
    ...extra,
  });
  let rows = [row('inquiry', 'Dopyty'), row('order', 'Objednávky'), row('other', 'Iné')];
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': {
      body: {
        ...NAV,
        sections: [
          NAV.sections[0],
          { ...NAV.sections[1], subs: [{ id: '17c', path: 'categories', title: 'Kategórie' }] },
        ],
      },
    },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/ai/categories': () => ({ body: rows }),
    'PUT /api/settings/ai/categories': (payload) => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      saved.push(payload as (typeof saved)[number]);
      rows = [...rows, row('x_kurier', 'Kuriér', { builtin: false, count_30d: 0 })];
      return { body: rows };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/ai-admin/categories');
  const panel = page.getByTestId('settings-ai-categories');
  await expect(panel.getByRole('switch', { name: 'Zapnutá: Iné' })).toBeDisabled();
  await panel.getByRole('switch', { name: 'Zapnutá: Objednávky' }).uncheck();
  await panel.getByLabel('Popis pre AI: Dopyty').fill('dopyty na skrutky');
  await panel.getByRole('button', { name: /Pridať kategóriu/ }).click();
  await panel.getByLabel('Názov', { exact: true }).fill('Kuriér');
  await shot(page, `issue116-categories-${info.project.name}`);
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => saved.length).toBe(1);
  const sent = saved[0]?.categories ?? [];
  expect(sent.find((c) => c.id === 'order')?.enabled).toBe(false);
  expect(sent.find((c) => c.id === null)?.label).toBe('Kuriér');
  await expect(panel.getByTestId('category-x_kurier')).toBeVisible();
});
