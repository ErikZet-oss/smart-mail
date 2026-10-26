import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { clearCookies, mockApi } from '../../test/mockApi';
import { initials } from './personsApi';

const person = (id: string, first: string, last: string, fn: string, manager = false) => ({
  id,
  first_name: first,
  last_name: last,
  full_name: `${first} ${last}`,
  role: 'sales',
  function: fn,
  is_manager: manager,
});
const PETER = person('p-peter', 'Peter', 'Hudák', 'vedúci pobočky', true);
const JANA = person('p-jana', 'Jana', 'Nováková', 'obchod');
const MAREK = person('p-marek', 'Marek', 'Kováč', 'sklad');

const PICKER = {
  branch: 'Senica',
  email: 'senica@smartsro.sk',
  persons: [PETER, JANA, MAREK],
  current_person_id: null,
  last_person_id: 'p-jana',
  idle_ask_minutes: null,
};

const meAs = (person: typeof PETER) => ({
  account_id: 'a1',
  email: 'senica@smartsro.sk',
  kind: 'branch',
  branch: 'Senica',
  person,
  needs_person: false,
  read_only: false,
});

function setMobile(mobile: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: mobile,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

function renderWho(state: unknown = { from: '/mail/default/inbox' }) {
  const router = createMemoryRouter(routeObjects, {
    future: ROUTER_FUTURE,
    initialEntries: [{ pathname: '/who', state }],
  });
  render(<App router={router} />);
  return router;
}

beforeEach(() => clearCookies());
afterEach(() => vi.unstubAllGlobals());

describe('W1b Kto ste?', () => {
  it('W1b shows the branch people in server order with the manager flag', async () => {
    setMobile(false);
    mockApi({ 'GET /api/auth/persons': { body: PICKER } });
    renderWho();
    const list = await screen.findByRole('list', { name: 'Kto ste?' });
    const names = within(list)
      .getAllByRole('button')
      .map((b) => b.textContent);
    expect(names[0]).toContain('Peter Hudák');
    expect(names[0]).toContain('Vedúci');
    expect(names[1]).toContain('Jana Nováková');
    expect(names[2]).toContain('Marek Kováč');
    expect(screen.getByText('Pobočka Senica · senica@smartsro.sk')).toBeInTheDocument();
  });

  it('W1b one click on a person selects it (no PIN, D9) and opens the route the user came from', async () => {
    setMobile(false);
    const api = mockApi({
      'GET /api/auth/persons': { body: PICKER },
      'POST /api/auth/person': { body: meAs(MAREK) },
      'GET /api/auth/me': { body: meAs(MAREK) },
    });
    const router = renderWho({ from: '/mail/default/sent' });
    fireEvent.click(await screen.findByRole('button', { name: /Marek Kováč/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail/default/sent'));
    expect(api.calls.find((c) => c.key === 'POST /api/auth/person')?.body).toEqual({
      person_id: 'p-marek',
      remember_device: true,
    });
  });

  it('W1b the last person on this device is preselected and Enter continues as that person', async () => {
    setMobile(false);
    const api = mockApi({
      'GET /api/auth/persons': { body: PICKER },
      'POST /api/auth/person': { body: meAs(JANA) },
      'GET /api/auth/me': { body: meAs(JANA) },
    });
    const router = renderWho();
    const cont = await screen.findByRole('button', { name: 'Pokračovať ako Jana' });
    expect(screen.getByRole('button', { name: /Jana Nováková/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(document.activeElement).toBe(cont));
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(window, { key: 'Enter' });
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail/default/inbox'));
    expect(api.calls.find((c) => c.key === 'POST /api/auth/person')?.body).toEqual({
      person_id: 'p-jana',
      remember_device: true,
    });
  });

  it('W1b without a remembered person there is no "Pokračovať ako" button', async () => {
    setMobile(false);
    mockApi({ 'GET /api/auth/persons': { body: { ...PICKER, last_person_id: null } } });
    renderWho();
    await screen.findByRole('list', { name: 'Kto ste?' });
    expect(screen.queryByRole('button', { name: /Pokračovať ako/ })).toBeNull();
  });

  it('W1b idle re-ask preselects the current person when the device has none', async () => {
    setMobile(false);
    mockApi({ 'GET /api/auth/persons': { body: { ...PICKER, last_person_id: null, current_person_id: 'p-peter' } } });
    renderWho();
    expect(await screen.findByRole('button', { name: 'Pokračovať ako Peter' })).toBeInTheDocument();
  });

  it('W1b "Prihlásiť sa iným e-mailom" signs out and opens W1', async () => {
    setMobile(false);
    const api = mockApi({
      'GET /api/auth/persons': { body: PICKER },
      'POST /api/auth/logout': { body: { ok: true } },
    });
    const router = renderWho();
    fireEvent.click(await screen.findByRole('button', { name: 'Prihlásiť sa iným e-mailom' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(api.calls.some((c) => c.key === 'POST /api/auth/logout')).toBe(true);
  });

  it('W1b a person deactivated meanwhile is refused and the list reloads', async () => {
    setMobile(false);
    let listCalls = 0;
    mockApi({
      'GET /api/auth/persons': () => {
        listCalls += 1;
        return { body: listCalls === 1 ? PICKER : { ...PICKER, persons: [PETER, JANA] } };
      },
      'POST /api/auth/person': { status: 403, body: { detail: { code: 'person_not_allowed' } } },
    });
    const router = renderWho();
    fireEvent.click(await screen.findByRole('button', { name: /Marek Kováč/ }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /Marek Kováč/ })).toBeNull());
    expect(router.state.location.pathname).toBe('/who');
  });
});

describe('M0 Kto ste? (mobile)', () => {
  it('M0 shows two initials, no Pokračovať button and "Zapamätať na tomto telefóne" on by default', async () => {
    setMobile(true);
    mockApi({ 'GET /api/auth/persons': { body: PICKER } });
    renderWho();
    await screen.findByRole('list', { name: 'Kto ste?' });
    expect(screen.getByText('JN')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Pokračovať ako/ })).toBeNull();
    expect(screen.getByRole('switch', { name: 'Zapamätať na tomto telefóne' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('Kliknite na svoje meno – podpis sa nastaví sám. Bez PIN-u.')).toBeInTheDocument();
  });

  it('M0 with "Zapamätať" switched off the phone does not remember the person', async () => {
    setMobile(true);
    const api = mockApi({
      'GET /api/auth/persons': { body: PICKER },
      'POST /api/auth/person': { body: meAs(PETER) },
      'GET /api/auth/me': { body: meAs(PETER) },
    });
    renderWho();
    fireEvent.click(await screen.findByRole('switch', { name: 'Zapamätať na tomto telefóne' }));
    fireEvent.click(screen.getByRole('button', { name: /Peter Hudák/ }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.key === 'POST /api/auth/person')?.body).toEqual({
        person_id: 'p-peter',
        remember_device: false,
      }),
    );
  });
});

describe('initials', () => {
  it('uses the first letter on W1b / W2b and both letters on M0', () => {
    expect(initials({ first_name: 'Čestmír', last_name: 'Šťastný' }, 1)).toBe('Č');
    expect(initials({ first_name: 'jana', last_name: 'nováková' }, 2)).toBe('JN');
  });
});
