import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { clearCookies, mockApi } from '../../test/mockApi';

const ME = {
  account_id: 'a1',
  email: 'jana@smartsro.sk',
  kind: 'personal',
  branch: null,
  person: { id: 'p1', first_name: 'Jana', last_name: 'Testová', full_name: 'Jana Testová', role: 'sales' },
  needs_person: false,
  read_only: false,
};

function renderAt(path: string, state?: unknown) {
  const router = createMemoryRouter(routeObjects, {
    future: ROUTER_FUTURE,
    initialEntries: [
      { pathname: path.split('?')[0], search: path.includes('?') ? `?${path.split('?')[1]}` : '', state },
    ],
  });
  render(<App router={router} />);
  return router;
}

async function submit(email = 'jana@smartsro.sk', password = 'heslo') {
  fireEvent.change(screen.getByLabelText('E-mail'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText('Heslo'), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: 'PRIHLÁSIŤ' }));
}

beforeEach(() => {
  clearCookies();
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe('W1 Prihlásenie', () => {
  it('signs in and returns to the route the user came from (W1c)', async () => {
    const api = mockApi({
      'POST /api/auth/login': { body: { next: 'app', me: ME } },
      'GET /api/auth/me': { body: ME },
    });
    const router = renderAt('/login', { from: '/mail/default/inbox' });
    await submit();
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail/default/inbox'));
    const login = api.calls.find((c) => c.key === 'POST /api/auth/login');
    expect(login?.body).toEqual({ email: 'jana@smartsro.sk', password: 'heslo', remember: false });
    expect(login?.headers['X-CSRF-Token']).toBe('test-csrf');
    expect(await screen.findByText('Prihlásený ako jana@smartsro.sk')).toBeInTheDocument();
  });

  it('shows the generic error for wrong credentials', async () => {
    mockApi({ 'POST /api/auth/login': { status: 401, body: { detail: { code: 'invalid_credentials' } } } });
    renderAt('/login');
    await submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Nesprávny e-mail alebo heslo.');
    expect(screen.getByLabelText('Heslo')).toHaveAttribute('aria-invalid', 'true');
  });

  it('says when the mail server is down', async () => {
    mockApi({ 'POST /api/auth/login': { status: 503, body: { detail: { code: 'mail_server_unavailable' } } } });
    renderAt('/login');
    await submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Mailový server je nedostupný – skúste o chvíľu.');
  });

  it('locks the button while rate-limited, with Slovak plural', async () => {
    mockApi({ 'POST /api/auth/login': { status: 429, body: { detail: { code: 'rate_limited', retry_after: 300 } } } });
    renderAt('/login');
    await submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Príliš veľa pokusov, skúste o 5 minút.');
    expect(screen.getByRole('button', { name: 'PRIHLÁSIŤ' })).toBeDisabled();
  });

  it.each([
    [60, 'skúste o 1 minútu.'],
    [150, 'skúste o 3 minúty.'],
  ])('rate limit of %i s reads "%s"', async (seconds, text) => {
    mockApi({
      'POST /api/auth/login': { status: 429, body: { detail: { code: 'rate_limited', retry_after: seconds } } },
    });
    renderAt('/login');
    await submit();
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });

  it('goes to W1a when the account has 2FA', async () => {
    mockApi({ 'POST /api/auth/login': { body: { next: '2fa', me: null } } });
    const router = renderAt('/login');
    await submit();
    await waitFor(() => expect(router.state.location.pathname).toBe('/login/2fa'));
    expect(await screen.findByRole('heading', { name: 'Overenie (2FA)' })).toBeInTheDocument();
  });

  it('goes to the person picker route for a shared branch mailbox and remembers the device', async () => {
    const branchMe = { ...ME, kind: 'branch', person: null, needs_person: true, read_only: true };
    mockApi({
      'POST /api/auth/login': { body: { next: 'who', me: branchMe } },
      'GET /api/auth/me': { body: branchMe },
    });
    const router = renderAt('/login');
    await submit('nitra@smartsro.sk');
    await waitFor(() => expect(router.state.location.pathname).toBe('/who'));
    expect(localStorage.getItem('sm.sharedDevice')).toBe('1');
  });

  it('"Zostať prihlásený" is on by default on a shared branch PC', () => {
    localStorage.setItem('sm.sharedDevice', '1');
    mockApi({});
    renderAt('/login');
    expect(screen.getByLabelText('Zostať prihlásený na tomto zariadení')).toBeChecked();
  });

  it('shows the Caps Lock hint', () => {
    mockApi({});
    renderAt('/login');
    fireEvent.keyUp(screen.getByLabelText('Heslo'), { key: 'a', modifierCapsLock: true });
    expect(screen.getByText('Zapnutý Caps Lock')).toBeInTheDocument();
  });

  it('shows and hides the password', () => {
    mockApi({});
    renderAt('/login');
    fireEvent.click(screen.getByRole('button', { name: 'Zobraziť heslo' }));
    expect(screen.getByLabelText('Heslo')).toHaveAttribute('type', 'text');
  });

  it.each([
    ['password-changed', 'Heslo k e-mailu sa zmenilo – prihláste sa novým heslom.'],
    ['expired', 'Boli ste odhlásený po 12 hodinách nečinnosti.'],
  ])('W1c banner for reason=%s', (reason, text) => {
    mockApi({});
    renderAt(`/login?reason=${reason}`);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe('global API errors', () => {
  it('a session ended by a password change sends the user to W1c', async () => {
    mockApi({
      'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated', reason: 'password_changed' } } },
    });
    const router = renderAt('/mail/default/inbox');
    await waitFor(() => expect(router.state.location.search).toBe('?reason=password-changed'));
    expect(await screen.findByText('Heslo k e-mailu sa zmenilo – prihláste sa novým heslom.')).toBeInTheDocument();
  });

  it('maintenance sends the user to W17', async () => {
    mockApi({
      'GET /api/auth/me': { status: 503, body: { detail: { code: 'maintenance', until: null } } },
      'GET /api/system/maintenance': { body: { active: true, until: null } },
    });
    const router = renderAt('/mail/default/inbox');
    await waitFor(() => expect(router.state.location.pathname).toBe('/maintenance'));
    expect(await screen.findByText(/Smart Mail bude čoskoro opäť dostupný/)).toBeInTheDocument();
  });

  it('an unexpected error shows W16c with the reference code', async () => {
    mockApi({ 'GET /api/auth/me': { status: 500, body: { detail: { code: 'server_error', ref: '7F3A21C9' } } } });
    const router = renderAt('/mail/default/inbox');
    await waitFor(() => expect(router.state.location.pathname).toBe('/500'));
    expect(await screen.findByText('500 · ref. 7F3A-21C9')).toBeInTheDocument();
  });
});
