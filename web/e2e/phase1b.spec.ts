import { expect, mockApi, shot, test } from './fixtures';

// Fictional people of the Figma frames (W1b 27:25825, M0 82:138, W2b 24:12246).
const person = (id: string, first: string, last: string, fn: string, manager = false) => ({
  id,
  first_name: first,
  last_name: last,
  full_name: `${first} ${last}`,
  role: 'sales',
  function: fn,
  is_manager: manager,
});
const PEOPLE = [
  person('p-peter', 'Peter', 'Hudák', 'vedúci pobočky', true),
  person('p-jana', 'Jana', 'Nováková', 'obchod'),
  person('p-marek', 'Marek', 'Kováč', 'sklad'),
];
type P = (typeof PEOPLE)[number];

/** A branch login "senica@smartsro.sk" with server state: active person of the session + device memory. */
function branchServer(lastPersonId: string | null) {
  const state = { current: null as P | null, last: lastPersonId };
  const me = () => ({
    account_id: 'a-senica',
    email: 'senica@smartsro.sk',
    kind: 'branch',
    branch: 'Senica',
    person: state.current,
    needs_person: state.current === null,
    read_only: state.current === null,
  });
  return {
    state,
    replies: {
      'POST /api/auth/login': () => ({ body: { next: 'who', me: me() } }),
      'GET /api/auth/me': () => ({ body: me() }),
      'GET /api/auth/persons': () => ({
        body: {
          branch: 'Senica',
          email: 'senica@smartsro.sk',
          persons: PEOPLE,
          current_person_id: state.current?.id ?? null,
          last_person_id: state.last,
          idle_ask_minutes: null,
        },
      }),
      'POST /api/auth/person': (body: unknown) => {
        const { person_id, remember_device } = body as { person_id: string; remember_device: boolean };
        state.current = PEOPLE.find((p) => p.id === person_id) ?? null;
        state.last = remember_device ? person_id : null;
        return { body: me() };
      },
    },
  };
}

test.describe('Flow 0: W1 → W1b → W2', () => {
  test('W1b default: last person preselected, manager first @mobile', async ({ page }, info) => {
    const server = branchServer('p-jana');
    await mockApi(page, server.replies);
    await page.goto('/who');
    await expect(page.getByRole('heading', { name: 'Kto ste?' })).toBeVisible();
    const tiles = page.getByRole('list', { name: 'Kto ste?' }).getByRole('button');
    await expect(tiles).toHaveCount(3);
    await expect(tiles.first()).toContainText('Peter Hudák');
    await expect(page.getByRole('button', { name: /Jana Nováková/ })).toHaveAttribute('aria-current', 'true');
    if (info.project.name === 'mobile') {
      await expect(page.getByRole('switch', { name: 'Zapamätať na tomto telefóne' })).toBeChecked();
      await expect(page.getByRole('button', { name: /Pokračovať ako/ })).toHaveCount(0);
    } else {
      await expect(page.getByRole('button', { name: 'Pokračovať ako Jana' })).toBeFocused();
      await page.getByRole('button', { name: 'Pokračovať ako Jana' }).blur();
    }
    await shot(page, `W1b-default-${info.project.name}`);
  });

  test('W1b hover on a person', async ({ page }) => {
    await mockApi(page, branchServer('p-jana').replies);
    await page.goto('/who');
    await page.getByRole('button', { name: 'Pokračovať ako Jana' }).blur();
    await page.getByRole('button', { name: /Peter Hudák/ }).hover();
    await shot(page, 'W1b-hover-desktop');
  });

  test('login of a branch mailbox → one click on Jana → inbox, every request as Jana @mobile', async ({ page }) => {
    const server = branchServer(null);
    await mockApi(page, server.replies);
    await page.goto('/login');
    await page.getByLabel('E-mail').fill('senica@smartsro.sk');
    await page.getByLabel('Heslo', { exact: true }).fill('heslo12345');
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
    await expect(page).toHaveURL(/\/who$/);
    await page.getByRole('button', { name: /Jana Nováková/ }).click();
    await expect(page).toHaveURL(/\/mail\/default\/inbox$/);
    await expect(page.getByText('Osoba: Jana Nováková')).toBeVisible();
    expect(server.state.last).toBe('p-jana');
  });

  test('Enter continues as the remembered person', async ({ page }) => {
    const server = branchServer('p-marek');
    await mockApi(page, server.replies);
    await page.goto('/who');
    await expect(page.getByRole('button', { name: 'Pokračovať ako Marek' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/mail\/default\/inbox$/);
    expect(server.state.current?.full_name).toBe('Marek Kováč');
  });
});

test.describe('W2b PersonChip', () => {
  test('switch Jana → Peter from the popover, toast for 2 s', async ({ page }) => {
    const server = branchServer('p-jana');
    server.state.current = PEOPLE[1] ?? null;
    await mockApi(page, server.replies);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Pracuje: Jana Nováková' }).click();
    await expect(page.getByRole('menu', { name: 'Kto pracuje?' })).toBeVisible();
    await shot(page, 'W2b-popover-desktop');
    await page.getByRole('menuitemradio', { name: /Peter Hudák/ }).click();
    await expect(page.getByRole('status')).toHaveText('Teraz pracuje: Peter · podpis zmenený');
    await expect(page.getByRole('button', { name: 'Pracuje: Peter Hudák' })).toBeVisible();
    await shot(page, 'W2b-toast-desktop');
    await expect(page.getByRole('status')).toBeHidden({ timeout: 4000 });
    expect(server.state.current?.full_name).toBe('Peter Hudák');
  });

  test('Ctrl+Shift+P opens "Kto pracuje?", arrows + Enter switch', async ({ page }) => {
    const server = branchServer('p-jana');
    server.state.current = PEOPLE[1] ?? null;
    await mockApi(page, server.replies);
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('button', { name: 'Pracuje: Jana Nováková' })).toBeVisible();
    await page.keyboard.press('Control+Shift+P');
    await expect(page.getByRole('menuitemradio', { name: /Jana Nováková/ })).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Pracuje: Marek Kováč' })).toBeVisible();
  });
});
