import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 2e — W12-17d Štýl a znalosti (admin): style guide + knowledge cards.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    { id: '01', path: 'preferences', title: 'Nastavenia', subs: [] },
    {
      id: '17',
      path: 'ai-admin',
      title: 'AI – správa',
      subs: [{ id: '17d', path: 'style', title: 'Štýl a znalosti' }],
    },
  ],
  paths: { preferences: '01', 'ai-admin': '17' },
};

type Card = {
  id: string;
  title: string;
  body: string;
  valid_until: string | null;
  tags: string[];
  enabled: boolean;
  expired: boolean;
  updated_at: string | null;
};

async function setup(page: Page) {
  let cards: Card[] = [
    {
      id: 'k1',
      title: 'Dodacie podmienky',
      body: 'Doprava zdarma nad 150 € bez DPH.',
      valid_until: null,
      tags: ['doprava'],
      enabled: true,
      expired: false,
      updated_at: null,
    },
  ];
  const calls: { guide: unknown[]; created: unknown[]; deleted: string[] } = { guide: [], created: [], deleted: [] };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/ai/style-guide': { body: { body: 'Vykáme.', updated_at: null } },
    'PUT /api/settings/ai/style-guide': (payload) => {
      calls.guide.push(payload);
      return { body: { body: (payload as { body: string }).body, updated_at: '2026-10-30T08:00:00Z' } };
    },
    'GET /api/settings/ai/knowledge': () => ({ body: cards }),
    'POST /api/settings/ai/knowledge': (payload) => {
      calls.created.push(payload);
      const card: Card = {
        ...(payload as Omit<Card, 'id' | 'expired' | 'updated_at'>),
        id: 'k2',
        expired: false,
        updated_at: null,
      };
      cards = [...cards, card];
      return { body: card };
    },
    'DELETE /api/settings/ai/knowledge/k1': () => {
      calls.deleted.push('k1');
      cards = cards.filter((c) => c.id !== 'k1');
      return { body: { status: 'deleted' } };
    },
  });
  return calls;
}

test.describe('Phase 2e W12-17d @mobile', () => {
  test('2e style guide, add and delete a knowledge card', async ({ page }, info) => {
    const calls = await setup(page);
    await page.goto('/settings/ai-admin/style');
    const panel = page.getByTestId('settings-ai-knowledge');
    await expect(panel.getByLabel('Text príručky')).toHaveValue('Vykáme.');
    await expect(panel.getByRole('cell', { name: 'Dodacie podmienky', exact: true })).toBeVisible();
    await shot(page, `phase2e-W12-17d-${info.project.name}`);
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="settings-ai-knowledge"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);

    await panel.getByLabel('Text príručky').fill('Vykáme. Nesľubujeme termíny bez overenia.');
    await panel.getByRole('button', { name: 'Uložiť', exact: true }).click();
    await expect(page.getByText('Uložené.').first()).toBeVisible();
    expect(calls.guide).toEqual([{ body: 'Vykáme. Nesľubujeme termíny bez overenia.' }]);

    await panel.getByRole('button', { name: 'Pridať kartu' }).click();
    await panel.getByLabel('Názov').fill('Otváracie hodiny');
    await panel.getByLabel('Text', { exact: true }).fill('Senica: Po–Pi 7:00–15:30.');
    await panel.getByLabel('Tagy (oddelené čiarkou)').fill('hodiny, Senica');
    await panel.getByRole('button', { name: 'Uložiť kartu' }).click();
    await expect(panel.getByRole('cell', { name: 'Otváracie hodiny', exact: true })).toBeVisible();
    expect(calls.created).toEqual([
      {
        title: 'Otváracie hodiny',
        body: 'Senica: Po–Pi 7:00–15:30.',
        valid_until: null,
        tags: ['hodiny', 'Senica'],
        enabled: true,
      },
    ]);

    await panel.getByRole('button', { name: 'Vymazať: Dodacie podmienky' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Vymazať' }).click();
    await expect(panel.getByRole('cell', { name: 'Dodacie podmienky', exact: true })).toHaveCount(0);
    expect(calls.deleted).toEqual(['k1']);
  });
});

const RULE_STRUCT = {
  match: 'all',
  conditions: [{ field: 'from_domain', op: 'equals', value: 'fixtech.example' }],
  actions: [{ type: 'set_category', value: 'supplier_document' }],
};
const RULE_TEXT = 'Ak doména odosielateľa je „fixtech.example“, tak kategória = Doklady dodávateľov.';

async function setupRules(page: Page, understood = true) {
  let rules: unknown[] = [];
  const calls: { preview: unknown[]; created: unknown[]; tested: unknown[] } = { preview: [], created: [], tested: [] };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': {
      body: {
        ...NAV,
        sections: [
          NAV.sections[0],
          {
            ...NAV.sections[1],
            subs: [...(NAV.sections[1]?.subs ?? []), { id: '17e', path: 'rules', title: 'Pravidlá' }],
          },
        ],
      },
    },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/ai/rules': () => ({ body: rules }),
    'POST /api/settings/ai/rules/preview': (payload) => {
      calls.preview.push(payload);
      return understood
        ? { body: { structured: RULE_STRUCT, description: RULE_TEXT } }
        : { status: 422, body: { detail: { code: 'rule_not_understood' } } };
    },
    'POST /api/settings/ai/rules/test': (payload) => {
      calls.tested.push(payload);
      return {
        body: {
          checked: 50,
          matches: [{ id: 'm1', subject: 'Faktura E3', from_email: 'f@fixtech.example', received_at: null }],
        },
      };
    },
    'POST /api/settings/ai/rules': (payload) => {
      calls.created.push(payload);
      rules = [
        {
          id: 'r1',
          nl_text: (payload as { nl_text: string }).nl_text,
          description: RULE_TEXT,
          enabled: true,
          last_used_at: null,
          created_by: 'Jana Testová',
        },
      ];
      return { body: rules[0] };
    },
  });
  return calls;
}

test.describe('Phase 2e W12-17e @mobile', () => {
  test('2e rule: convert, try, confirm and save', async ({ page }, info) => {
    const calls = await setupRules(page);
    await page.goto('/settings/ai-admin/rules');
    const panel = page.getByTestId('settings-ai-rules');
    await expect(panel.getByText('Zatiaľ žiadne pravidlá.')).toBeVisible();
    await panel.getByRole('button', { name: 'Nové pravidlo' }).click();
    await panel.getByLabel('Pravidlo', { exact: true }).fill('Faktúry od Fixtechu sú doklady dodávateľov');
    await panel.getByRole('button', { name: 'Previesť' }).click();
    await expect(panel.getByTestId('rule-preview').getByText(RULE_TEXT)).toBeVisible();
    expect(calls.created).toEqual([]); // nothing saved before the confirmation
    await panel.getByRole('button', { name: 'Vyskúšať na posledných 50 e-mailoch' }).click();
    await expect(panel.getByText('Zhoduje sa 1 z 50 posledných e-mailov.')).toBeVisible();
    await shot(page, `phase2e-W12-17e-${info.project.name}`);
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="settings-ai-rules"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
    await panel.getByRole('button', { name: 'Uložiť pravidlo' }).click();
    await expect(panel.getByRole('cell', { name: RULE_TEXT })).toBeVisible();
    expect(calls.created).toEqual([{ nl_text: 'Faktúry od Fixtechu sú doklady dodávateľov', structured: RULE_STRUCT }]);
    expect(calls.tested).toEqual([{ structured: RULE_STRUCT }]);
  });

  test('2e rule the AI cannot express shows a hint and saves nothing', async ({ page }) => {
    const calls = await setupRules(page, false);
    await page.goto('/settings/ai-admin/rules');
    const panel = page.getByTestId('settings-ai-rules');
    await panel.getByRole('button', { name: 'Nové pravidlo' }).click();
    await panel.getByLabel('Pravidlo', { exact: true }).fill('Faktúry pošli účtovníčke');
    await panel.getByRole('button', { name: 'Previesť' }).click();
    await expect(panel.getByRole('alert')).toContainText('Pravidlu sa nepodarilo porozumieť');
    await expect(panel.getByRole('button', { name: 'Uložiť pravidlo' })).toHaveCount(0);
    expect(calls.created).toEqual([]);
  });
});
