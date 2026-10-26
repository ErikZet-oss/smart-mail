import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { clearCookies, mockApi } from '../../test/mockApi';

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

const picker = (current: string, persons = [PETER, JANA, MAREK], idle: number | null = null) => ({
  branch: 'Senica',
  email: 'senica@smartsro.sk',
  persons,
  current_person_id: current,
  last_person_id: current,
  idle_ask_minutes: idle,
});
const me = (p: typeof PETER) => ({
  account_id: 'a1',
  email: 'senica@smartsro.sk',
  kind: 'branch',
  branch: 'Senica',
  person: p,
  needs_person: false,
  read_only: false,
});

function renderInbox() {
  const router = createMemoryRouter(routeObjects, { future: ROUTER_FUTURE, initialEntries: ['/mail/default/inbox'] });
  render(<App router={router} />);
  return router;
}

beforeEach(() => clearCookies());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('W2b PersonChip', () => {
  it('W2b one click in "Kto pracuje?" switches the person and shows the toast', async () => {
    let current = 'p-jana';
    const api = mockApi({
      'GET /api/auth/me': () => ({ body: me(current === 'p-jana' ? JANA : PETER) }),
      'GET /api/auth/persons': () => ({ body: picker(current) }),
      'POST /api/auth/person': () => {
        current = 'p-peter';
        return { body: me(PETER) };
      },
    });
    renderInbox();
    const chip = await screen.findByRole('button', { name: 'Pracuje: Jana Nováková' });
    fireEvent.click(chip);
    const menu = screen.getByRole('menu', { name: 'Kto pracuje?' });
    expect(screen.getByRole('menuitemradio', { name: /Jana Nováková/ })).toHaveAttribute('aria-checked', 'true');
    expect(menu).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Peter Hudák/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('Teraz pracuje: Peter · podpis zmenený');
    expect(await screen.findByRole('button', { name: 'Pracuje: Peter Hudák' })).toBeInTheDocument();
    expect(api.calls.find((c) => c.key === 'POST /api/auth/person')?.body).toEqual({
      person_id: 'p-peter',
      remember_device: true,
    });
    expect(screen.getByText('Osoba: Peter Hudák')).toBeInTheDocument();
  });

  it('W2b Ctrl+Shift+P opens the popover and Escape closes it', async () => {
    mockApi({ 'GET /api/auth/me': { body: me(JANA) }, 'GET /api/auth/persons': { body: picker('p-jana') } });
    renderInbox();
    await screen.findByRole('button', { name: 'Pracuje: Jana Nováková' });
    fireEvent.keyDown(window, { key: 'P', ctrlKey: true, shiftKey: true });
    expect(screen.getByRole('menu', { name: 'Kto pracuje?' })).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toHaveAttribute('aria-checked', 'true'));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('W2b the toast disappears after 2 s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = 'p-jana';
    mockApi({
      'GET /api/auth/me': () => ({ body: me(current === 'p-jana' ? JANA : MAREK) }),
      'GET /api/auth/persons': () => ({ body: picker(current) }),
      'POST /api/auth/person': () => {
        current = 'p-marek';
        return { body: me(MAREK) };
      },
    });
    renderInbox();
    fireEvent.click(await screen.findByRole('button', { name: 'Pracuje: Jana Nováková' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Marek Kováč/ }));
    await screen.findByRole('status');
    act(() => {
      vi.advanceTimersByTime(1900);
    });
    expect(screen.getByRole('status')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('W2b with one person the chip only shows who works (nothing to switch)', async () => {
    mockApi({
      'GET /api/auth/me': { body: { ...me(JANA), kind: 'personal', branch: null } },
      'GET /api/auth/persons': { body: picker('p-jana', [JANA]) },
    });
    renderInbox();
    expect(await screen.findByRole('img', { name: 'Pracuje: Jana Nováková' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Pracuje:/ })).toBeNull();
  });

  it('W1b idle re-ask: after the branch idle minutes the picker comes back', async () => {
    mockApi({
      'GET /api/auth/me': { body: me(JANA) },
      'GET /api/auth/persons': { body: picker('p-jana', undefined, 30) },
    });
    const router = renderInbox();
    await screen.findByRole('button', { name: 'Pracuje: Jana Nováková' });
    vi.useFakeTimers();
    fireEvent.pointerDown(window);
    act(() => {
      vi.advanceTimersByTime(30 * 60_000);
    });
    vi.useRealTimers();
    await waitFor(() => expect(router.state.location.pathname).toBe('/who'));
  });

  it('W1b a 409 person_inactive from any request opens the picker', async () => {
    mockApi({ 'GET /api/auth/me': { status: 409, body: { detail: { code: 'person_inactive' } } } });
    const router = renderInbox();
    await waitFor(() => expect(router.state.location.pathname).toBe('/who'));
  });
});
