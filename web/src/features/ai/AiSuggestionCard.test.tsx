import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ToastProvider } from '../../components/Toasts';
import { AiSuggestionCard } from './AiSuggestionCard';
import type { Suggestion } from './suggestionsApi';

const SUGGESTION: Suggestion = {
  id: 's1',
  type: 'reply',
  status: 'pending',
  to: ['novak@abcstav.example'],
  subject: 'Re: Faktúra',
  body: 'Dobrý deň, v prílohe posielame kópiu faktúry 2026123. S pozdravom, Jana Testová zo Smart s.r.o. a celý tím.',
  language: 'sk',
  rationale: null,
  confidence: 0.9,
  checks: [{ id: 'new_recipient', level: 'warning', params: { address: 'novak@abcstav.example' } }],
  blocked: false,
};

function renderCard(suggestion: Suggestion = SUGGESTION) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ToastProvider>
          <AiSuggestionCard suggestion={suggestion} mailbox="default" messageId="m1" category={null} readOnly={false} />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.getByTestId('ai-suggestion-card');
}

describe('#156 AiSuggestionCard collapsed by default', () => {
  it('starts collapsed with a short preview, a warning count and no approve button', () => {
    const card = renderCard();
    expect(card).toHaveAttribute('data-collapsed', 'true');
    expect(screen.queryByRole('button', { name: 'Pripraviť koncept' })).toBeNull();
    expect(card).toHaveTextContent('Dobrý deň, v prílohe posielame');
    expect(card).not.toHaveTextContent('celý tím'); // clipped to ~80 characters
    expect(screen.getByText('1 upozornenie')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Zamietnuť' })).toBeInTheDocument();
  });

  it('a click expands it, shows approve and focuses Zbaliť; Zbaliť collapses again', () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    expect(screen.getByTestId('ai-suggestion-card')).toHaveAttribute('data-collapsed', 'false');
    expect(screen.getByRole('button', { name: 'Pripraviť koncept' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Zbaliť' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Zbaliť' }));
    expect(screen.getByTestId('ai-suggestion-card')).toHaveAttribute('data-collapsed', 'true');
  });

  it('reject from the collapsed row opens the reason chips', () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Zamietnuť' }));
    expect(screen.getByRole('button', { name: 'Zamietnuť návrh' })).toBeInTheDocument();
  });

  it('a blocking check is shown as blocked while collapsed', () => {
    renderCard({
      ...SUGGESTION,
      body: 'Cena je [[DOPLNIŤ: cena]].',
      checks: [{ id: 'placeholder', level: 'blocking', params: {} }],
      blocked: true,
    });
    expect(screen.getByText('Návrh treba doplniť – obsahuje blokujúcu kontrolu')).toBeInTheDocument();
  });
});
