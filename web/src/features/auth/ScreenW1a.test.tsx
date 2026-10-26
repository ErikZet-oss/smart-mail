import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { clearCookies, mockApi } from '../../test/mockApi';

function renderW1a() {
  const router = createMemoryRouter(routeObjects, {
    future: ROUTER_FUTURE,
    initialEntries: ['/login/2fa'],
  });
  render(<App router={router} />);
  return router;
}

function boxes() {
  return Array.from({ length: 6 }, (_, i) => screen.getByLabelText(`Číslica ${i + 1} zo 6`));
}

const box = (i: number) => screen.getByLabelText(`Číslica ${i + 1} zo 6`);

beforeEach(() => clearCookies());
afterEach(() => vi.unstubAllGlobals());

describe('W1a Overenie (2FA)', () => {
  it('pasting the whole code fills all six boxes', () => {
    mockApi({});
    renderW1a();
    fireEvent.paste(box(0), { clipboardData: { getData: () => '481 920' } });
    expect(
      boxes()
        .map((b) => (b as HTMLInputElement).value)
        .join(''),
    ).toBe('481920');
  });

  it('typing advances to the next box', () => {
    mockApi({});
    renderW1a();
    fireEvent.change(box(0), { target: { value: '4' } });
    expect(document.activeElement).toBe(boxes()[1]);
  });

  it('a wrong code shows the remaining attempts (Slovak plural)', async () => {
    mockApi({ 'POST /api/auth/2fa': { status: 401, body: { detail: { code: 'invalid_code', attempts_left: 3 } } } });
    renderW1a();
    fireEvent.paste(box(0), { clipboardData: { getData: () => '000000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Overiť' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Kód nie je správny. Zostávajú 3 pokusy.');
  });

  it('after the last wrong code it returns to W1', async () => {
    mockApi({ 'POST /api/auth/2fa': { status: 401, body: { detail: { code: 'mfa_locked' } } } });
    const router = renderW1a();
    fireEvent.paste(box(0), { clipboardData: { getData: () => '000000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Overiť' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(await screen.findByText('Príliš veľa nesprávnych kódov – prihláste sa znova.')).toBeInTheDocument();
  });

  it('accepts a backup code', async () => {
    const api = mockApi({ 'POST /api/auth/2fa': { body: { next: 'who', me: null } } });
    const router = renderW1a();
    fireEvent.click(screen.getByRole('button', { name: 'Použiť záložný kód' }));
    fireEvent.change(screen.getByLabelText('Záložný kód'), { target: { value: 'abcd-efgh' } });
    fireEvent.click(screen.getByRole('button', { name: 'Overiť' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/who'));
    expect(api.calls.find((c) => c.key === 'POST /api/auth/2fa')?.body).toEqual({
      code: 'abcd-efgh',
      remember_device: false,
    });
  });
});
