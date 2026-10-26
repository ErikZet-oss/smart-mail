import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { mockApi } from '../../test/mockApi';

function renderAt(path: string) {
  const router = createMemoryRouter(routeObjects, { future: ROUTER_FUTURE, initialEntries: [path] });
  render(<App router={router} />);
}

afterEach(() => vi.unstubAllGlobals());

describe('W16a Prístup zamietnutý', () => {
  it('"Požiadať správcu" mails the admin address from config', async () => {
    mockApi({ 'GET /api/system/info': { body: { admin_contact_email: 'it@smartsro.sk' } } });
    renderAt('/403');
    const link = await screen.findByRole('link', { name: 'Požiadať správcu' });
    await waitFor(() => expect(link.getAttribute('href')).toMatch(/^mailto:it%40smartsro\.sk\?subject=/));
  });

  it('still opens the mail client when no admin address is configured', async () => {
    mockApi({ 'GET /api/system/info': { body: { admin_contact_email: null } } });
    renderAt('/403');
    const link = await screen.findByRole('link', { name: 'Požiadať správcu' });
    expect(link.getAttribute('href')).toMatch(/^mailto:\?subject=/);
  });
});
