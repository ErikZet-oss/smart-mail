import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { refreshAfterPersonChange } from '../../lib/sessionCache';
import { clearCookies, mockApi } from '../../test/mockApi';

/** Fictional branch mailbox. Roles differ; the settings nav is whatever the API returns for that person. */
const erik = {
  id: 'p-erik',
  first_name: 'Erik',
  last_name: 'Testový',
  full_name: 'Erik Testový',
  role: 'admin',
  function: 'správca',
  is_manager: true,
};
const jan = {
  id: 'p-jan',
  first_name: 'Ján',
  last_name: 'Testový',
  full_name: 'Ján Testový',
  role: 'sales',
  function: 'obchod',
  is_manager: false,
};
type Person = typeof erik;

const personalSections = [
  {
    id: '01',
    path: 'preferences',
    title: 'Nastavenia',
    subs: [{ id: '01a', path: 'ui', title: 'Používateľské rozhranie' }],
  },
  {
    id: '03',
    path: 'identity',
    title: 'Identity',
    subs: [{ id: '03b', path: 'profile', title: 'Môj profil' }],
  },
];
const adminSections = [
  {
    id: '11',
    path: 'branches',
    title: 'Pobočky a osoby',
    subs: [{ id: '11a', path: 'details', title: 'Údaje' }],
  },
];
const navFor = (admin: boolean) => ({ sections: admin ? [...personalSections, ...adminSections] : personalSections });

const me = (person: Person) => ({
  account_id: 'a-fa',
  email: 'fa@smartmail.test',
  kind: 'branch' as const,
  branch: 'Testov',
  person,
  needs_person: false,
  read_only: false,
});

const picker = (current: Person) => ({
  branch: 'Testov',
  email: 'fa@smartmail.test',
  persons: [erik, jan],
  current_person_id: current.id,
  last_person_id: current.id,
  idle_ask_minutes: null,
});

const profile = (person: Person) => ({
  id: person.id,
  first_name: person.first_name,
  last_name: person.last_name,
  function: person.function,
  phone: null,
  mobile: null,
  personal_email: null,
  languages: ['sk'],
  style_guide: null,
  role: person.role,
  signature_preview_html: `<p>${person.first_name}</p>`,
});

const PREFS = {
  ui: { theme: 'system', classic: false },
  list: { density: 'compact', mode: 'list', page_size: 50, show_ai_summary: true },
  reading: {},
  composing: { undo_send_seconds: 10 },
  shortcuts: {},
};

const SHELL = {
  'GET /api/mail/prefs': { body: PREFS },
  'GET /api/notifications': { body: { items: [], unread_count: 0 } },
  'GET /api/settings/preferences': { body: PREFS },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: false } } },
};

function renderAt(path: string) {
  const router = createMemoryRouter(routeObjects, { future: ROUTER_FUTURE, initialEntries: [path] });
  render(<App router={router} />);
  return router;
}

beforeEach(() => {
  clearCookies();
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe('person cache', () => {
  it('test_switch_person_refreshes_settings_nav', async () => {
    let current = erik;
    mockApi({
      ...SHELL,
      'GET /api/auth/me': () => ({ body: me(current) }),
      'GET /api/auth/persons': () => ({ body: picker(current) }),
      'POST /api/auth/person': (body: unknown) => {
        const id = (body as { person_id?: string }).person_id;
        current = id === jan.id ? jan : erik;
        return { body: me(current) };
      },
      'GET /api/settings/nav': () => ({ body: navFor(current.role === 'admin') }),
    });
    renderAt('/settings');
    expect(await screen.findByRole('link', { name: 'Pobočky a osoby' })).toBeInTheDocument();
    expect(screen.getByText('Správa')).toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'Pracuje: Erik Testový' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Ján Testový/ }));
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Pobočky a osoby' })).toBeNull());
    expect(screen.queryByText('Správa')).toBeNull();
    expect(await screen.findByRole('button', { name: 'Pracuje: Ján Testový' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Pracuje: Ján Testový' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Erik Testový/ }));
    expect(await screen.findByRole('link', { name: 'Pobočky a osoby' })).toBeInTheDocument();
    expect(screen.getByText('Správa')).toBeInTheDocument();
  });

  it('test_login_after_session_revoke_clears_cache', async () => {
    let phase: 'admin' | 'revoked' | 'sales' = 'admin';
    let releaseNav = () => {};
    let navHold: Promise<void> = Promise.resolve();
    mockApi({
      ...SHELL,
      'GET /api/auth/me': () => ({ body: me(phase === 'sales' ? jan : erik) }),
      'GET /api/auth/persons': () => ({ body: picker(phase === 'sales' ? jan : erik) }),
      'GET /api/settings/nav': async () => {
        if (phase === 'sales') await navHold;
        return { body: navFor(phase !== 'sales') };
      },
      'GET /api/settings/profile': () => {
        if (phase === 'revoked') {
          return { status: 401, body: { detail: { code: 'unauthenticated', reason: 'expired' } } };
        }
        return { body: profile(phase === 'sales' ? jan : erik) };
      },
      'POST /api/auth/login': () => ({ body: { next: 'app', me: me(jan) } }),
    });
    const router = renderAt('/settings');
    expect(await screen.findByRole('link', { name: 'Pobočky a osoby' })).toBeInTheDocument();

    phase = 'revoked';
    fireEvent.click(screen.getByRole('link', { name: 'Môj profil' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));

    navHold = new Promise<void>((resolve) => {
      releaseNav = () => resolve();
    });
    phase = 'sales';
    fireEvent.change(screen.getByLabelText('E-mail'), { target: { value: 'fa@smartmail.test' } });
    fireEvent.change(screen.getByLabelText('Heslo'), { target: { value: 'heslo-fiktivne' } });
    fireEvent.click(screen.getByRole('button', { name: 'PRIHLÁSIŤ' }));

    expect(await screen.findByRole('heading', { name: 'Môj profil' })).toBeInTheDocument();
    // The new nav request is still in flight. A leftover admin cache would already show Správa.
    expect(screen.queryByRole('link', { name: 'Pobočky a osoby' })).toBeNull();
    expect(screen.queryByText('Správa')).toBeNull();

    releaseNav();
    expect(await screen.findByRole('link', { name: 'Môj profil' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Pobočky a osoby' })).toBeNull();
    expect(screen.queryByText('Správa')).toBeNull();
  });

  it('keeps the open compose draft when the person changes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(['me'], me(erik));
    client.setQueryData(['persons'], picker(erik));
    client.setQueryData(['settings', 'nav'], navFor(true));
    client.setQueryData(['compose', 'draft-1'], {
      id: 'draft-1',
      body_html: '<p>Podpis Erik</p>',
      signature_person_id: erik.id,
    });
    await refreshAfterPersonChange(client);
    expect(client.getQueryData(['settings', 'nav'])).toBeUndefined();
    expect(client.getQueryData(['compose', 'draft-1'])).toMatchObject({ signature_person_id: erik.id });
    expect(client.getQueryData(['me'])).toMatchObject({ person: { id: erik.id } });
    expect(client.getQueryData(['persons'])).toMatchObject({ current_person_id: erik.id });
  });
});
