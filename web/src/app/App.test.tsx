import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

afterEach(() => vi.unstubAllGlobals());

describe('App (phase 0)', () => {
  it('shows Slovak texts and a healthy server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    render(<App />);
    expect(screen.getByText('Kostra aplikácie je pripravená')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('health')).toHaveTextContent('Server beží'));
  });

  it('says when the server is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId('health')).toHaveTextContent('Server nie je dostupný'));
  });
});
