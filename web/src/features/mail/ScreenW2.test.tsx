import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { ROUTER_FUTURE, routeObjects } from '../../app/router';
import { useToast } from '../../components/toastContext';
import { ToastProvider } from '../../components/Toasts';
import { foldersView, mailHandlers } from '../../test/mailFixtures';
import { clearCookies, mockApi } from '../../test/mockApi';
import type { FoldersView } from './mailApi';

const PERSON = {
  id: 'p1',
  first_name: 'Jana',
  last_name: 'Testová',
  full_name: 'Jana Testová',
  role: 'sales',
  function: null,
  is_manager: false,
};
const ME = {
  account_id: 'a1',
  email: 'pilot@smartmail.test',
  kind: 'personal',
  branch: null,
  person: PERSON,
  needs_person: false,
  read_only: false,
};
const PICKER = {
  branch: null,
  email: ME.email,
  persons: [PERSON],
  current_person_id: 'p1',
  last_person_id: null,
  idle_ask_minutes: null,
};

function base(view: FoldersView = foldersView(), me: object = ME) {
  return { ...mailHandlers(view), 'GET /api/auth/me': { body: me }, 'GET /api/auth/persons': { body: PICKER } };
}

function renderAt(path = '/mail/default/inbox') {
  const router = createMemoryRouter(routeObjects, { future: ROUTER_FUTURE, initialEntries: [path] });
  render(<App router={router} />);
  return router;
}

const folderNav = async () => screen.findByRole('navigation', { name: 'Priečinky' });

beforeEach(() => clearCookies());
afterEach(() => vi.unstubAllGlobals());

describe('W2 shell and folder column (1c)', () => {
  it('G3 special folders get the Roundcube SK names first, own folders (D21) follow', async () => {
    mockApi(base());
    renderAt();
    const links = within(await folderNav()).getAllByRole('link');
    expect(links.map((l) => l.textContent?.replace(/[\d\s]+$/, ''))).toEqual([
      'Doručená pošta',
      'Koncepty',
      'Odoslané',
      'Nevyžiadaná pošta',
      'Kôš',
      'Archív',
      'Dodávatelia',
      'Faktúry',
      'Senica',
    ]);
    expect(screen.getByRole('link', { name: 'Doručená pošta, neprečítané: 5' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('heading', { name: 'pilot@smartmail.test' })).toBeInTheDocument();
  });

  it('G3 unread counts use Slovak digit grouping and the URL uses the special-use key', async () => {
    const view = foldersView();
    const faktury = view.folders.find((f) => f.name === 'Faktúry');
    if (faktury) faktury.unread = 5220;
    mockApi(base(view));
    renderAt();
    const link = await screen.findByRole('link', { name: 'Faktúry, neprečítané: 5220' });
    expect(link.textContent?.replace(/\s/g, ' ')).toContain('5 220');
    expect(link).toHaveAttribute('href', `/mail/default/${faktury?.id}`);
    expect(screen.getByRole('link', { name: 'Kôš, neprečítané: 1' })).toHaveAttribute('href', '/mail/default/trash');
  });

  it('G1 the E-mail rail item is active and its badge is the unread count of Doručená pošta', async () => {
    mockApi(base());
    renderAt('/mail/default/trash');
    const mail = await screen.findByRole('link', { name: 'E-mail, neprečítané: 5' });
    expect(mail).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Vytvoriť správu' })).toHaveAttribute('href', '/compose');
    expect(screen.getByRole('button', { name: 'Odhlásiť' })).toBeEnabled();
  });

  it('G3 quota above 90 % is red (fixture of the full test mailbox)', async () => {
    mockApi(base(foldersView('plna@smartmail.test', { used_kb: 1905, limit_kb: 2048, percent: 93, level: 'danger' })));
    renderAt();
    const meter = await screen.findByRole('meter', { name: 'Využitie schránky' });
    expect(meter).toHaveAttribute('aria-valuenow', '93');
    expect(within(meter).getByText('93 %')).toHaveClass('text-danger-600');
  });

  it('G3 quota below 75 % stays neutral', async () => {
    mockApi(base());
    renderAt();
    const meter = await screen.findByRole('meter', { name: 'Využitie schránky' });
    expect(within(meter).getByText('40 %')).toHaveClass('text-text-secondary');
  });

  it('G3 the ⋮ menu lists the mailboxes; "Všetky schránky" only with 2+', async () => {
    const view = foldersView();
    mockApi({
      ...base(view),
      'GET /api/mail/mailboxes': {
        body: [view.mailbox, { id: 'mb-2', email: 'senica@smartmail.test', unread: 0, sync_state: 'ok' }],
      },
    });
    const router = renderAt();
    await folderNav();
    fireEvent.click(screen.getByRole('button', { name: 'Menu schránky' }));
    const menu = await screen.findByRole('menu', { name: 'Menu schránky' });
    expect(within(menu).getByRole('menuitemradio', { name: 'pilot@smartmail.test' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await within(menu).findByRole('menuitemradio', { name: 'senica@smartmail.test' });
    expect(within(menu).getByRole('menuitem', { name: 'Všetky schránky' })).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'senica@smartmail.test' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail/mb-2/inbox'));
  });

  it('G3 with one mailbox there is no "Všetky schránky"', async () => {
    mockApi(base());
    renderAt();
    await folderNav();
    fireEvent.click(screen.getByRole('button', { name: 'Menu schránky' }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: 'Všetky schránky' })).toBeNull();
    expect(within(menu).getByRole('menuitem', { name: 'Zhustiť' })).toBeInTheDocument();
  });

  it('G3 context menu (right click): special folders cannot be renamed or deleted', async () => {
    mockApi(base());
    renderAt();
    fireEvent.contextMenu(await screen.findByRole('link', { name: 'Doručená pošta, neprečítané: 5' }));
    const menu = screen.getByRole('menu', { name: 'Akcie priečinka Doručená pošta' });
    expect(within(menu).getByRole('menuitem', { name: 'Premenovať' })).toHaveAttribute('aria-disabled', 'true');
    expect(within(menu).getByRole('menuitem', { name: 'Vymazať' })).toHaveAttribute('aria-disabled', 'true');
    expect(within(menu).getByRole('menuitem', { name: 'Vyprázdniť' })).toHaveAttribute('aria-disabled', 'true');
    expect(within(menu).getByRole('menuitem', { name: 'Označiť všetko ako prečítané' })).toHaveFocus();
    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('G3 Shift+F10 opens the context menu from the keyboard', async () => {
    mockApi(base());
    renderAt();
    const link = await screen.findByRole('link', { name: 'Senica' });
    fireEvent.keyDown(link, { key: 'F10', shiftKey: true });
    expect(screen.getByRole('menu', { name: 'Akcie priečinka Senica' })).toBeInTheDocument();
  });

  it('G3 Vyprázdniť Kôš asks first (G5 confirm), then empties and shows a toast', async () => {
    const view = foldersView();
    const trash = view.folders.find((f) => f.special_use === 'trash');
    const after = foldersView();
    const api = mockApi({
      ...base(view),
      [`POST /api/mail/mailboxes/default/folders/${trash?.id}/empty`]: { body: after },
    });
    renderAt();
    fireEvent.contextMenu(await screen.findByRole('link', { name: 'Kôš, neprečítané: 1' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Vyprázdniť' }));
    const dialog = screen.getByRole('dialog', { name: 'Vyprázdniť priečinok Kôš?' });
    expect(dialog).toHaveTextContent('3 správy budú natrvalo vymazané.');
    expect(within(dialog).getByRole('button', { name: 'Zrušiť' })).toHaveFocus();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vyprázdniť' }));
    expect(await screen.findByText('Priečinok Kôš je vyprázdnený.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.calls.some((c) => c.key.endsWith('/empty'))).toBe(true);
  });

  it('G5 Esc closes the confirm dialog without calling the server', async () => {
    const api = mockApi(base());
    renderAt();
    const link = await screen.findByRole('link', { name: 'Senica' });
    fireEvent.contextMenu(link);
    fireEvent.click(screen.getByRole('menuitem', { name: 'Vymazať' }));
    const dialog = screen.getByRole('dialog', { name: 'Vymazať priečinok Senica?' });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.calls.some((c) => c.key.startsWith('DELETE'))).toBe(false);
  });

  it('G3 Nový podpriečinok sends the parent and shows a name conflict inline', async () => {
    const view = foldersView();
    const parent = view.folders.find((f) => f.name === 'Dodávatelia');
    const api = mockApi({
      ...base(view),
      'POST /api/mail/mailboxes/default/folders': { status: 409, body: { detail: { code: 'folder_exists' } } },
    });
    renderAt();
    fireEvent.contextMenu(await screen.findByRole('link', { name: 'Dodávatelia, neprečítané: 3' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Nový podpriečinok' }));
    const dialog = screen.getByRole('dialog', { name: 'Nový podpriečinok v Dodávatelia' });
    fireEvent.change(within(dialog).getByLabelText('Názov priečinka'), { target: { value: ' Würth ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Vytvoriť' }));
    expect(await within(dialog).findByText('Priečinok s týmto názvom už existuje.')).toBeInTheDocument();
    expect(api.calls.find((c) => c.key === 'POST /api/mail/mailboxes/default/folders')?.body).toEqual({
      parent_id: parent?.id,
      name: 'Würth',
    });
  });

  it('G3 Premenovať of the open folder follows it to the new name', async () => {
    const view = foldersView();
    const senica = view.folders.find((f) => f.name === 'Senica');
    const after = foldersView();
    const renamed = after.folders.find((f) => f.name === 'Senica');
    if (renamed) {
      renamed.id = 'f-new';
      renamed.name = 'Senica 2';
      renamed.label = 'Senica 2';
    }
    const api = mockApi({
      ...base(view),
      [`PATCH /api/mail/mailboxes/default/folders/${senica?.id}`]: { body: after },
    });
    const router = renderAt(`/mail/default/${senica?.id}`);
    fireEvent.contextMenu(await screen.findByRole('link', { name: 'Senica' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Premenovať' }));
    const input = screen.getByLabelText('Názov priečinka');
    expect(input).toHaveValue('Senica');
    fireEvent.change(input, { target: { value: 'Senica 2' } });
    fireEvent.submit(input);
    await waitFor(() => expect(router.state.location.pathname).toBe('/mail/default/f-new'));
    expect(api.calls.find((c) => c.key.startsWith('PATCH'))?.body).toEqual({ name: 'Senica 2' });
  });

  it('G3 without an active person (read-only) folder actions are disabled', async () => {
    mockApi(base(foldersView(), { ...ME, person: null, read_only: true }));
    renderAt();
    fireEvent.contextMenu(await screen.findByRole('link', { name: 'Dodávatelia, neprečítané: 3' }));
    const menu = screen.getByRole('menu');
    for (const item of within(menu).getAllByRole('menuitem')) expect(item).toHaveAttribute('aria-disabled', 'true');
  });

  it('W2 empty folder and empty inbox states', async () => {
    const view = foldersView();
    const inbox = view.folders.find((f) => f.special_use === 'inbox');
    if (inbox) {
      inbox.total = 0;
      inbox.unread = 0;
    }
    mockApi(base(view));
    renderAt();
    expect(await screen.findByText('Všetko vybavené ✓')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Senica' }));
    expect(await screen.findByText('Priečinok je prázdny')).toBeInTheDocument();
    expect(screen.getByText(/Správy:.*0/)).toBeInTheDocument();
  });

  it('W2a nothing selected shows the watermark and "Vyberte správu"', async () => {
    mockApi(base());
    renderAt();
    expect(await screen.findByText('Vyberte správu')).toBeInTheDocument();
  });

  it('W2 list rows show sender and subject; click opens the reading pane', async () => {
    mockApi(base());
    renderAt();
    expect(await screen.findByText('Kópia faktúry 2026123')).toBeInTheDocument();
    expect(screen.getByText('Ján Novák')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Kópia faktúry 2026123'));
    expect(await screen.findByRole('heading', { name: 'Kópia faktúry 2026123' })).toBeInTheDocument();
    expect(screen.getByText(/prosím o zaslanie kópie faktúry/)).toBeInTheDocument();
  });

  it('W2 an unknown folder opens W16b', async () => {
    mockApi(base());
    const router = renderAt('/mail/default/neexistuje');
    await waitFor(() => expect(router.state.location.pathname).toBe('/404'));
  });

  it('W2 an unknown mailbox opens W16b', async () => {
    mockApi({
      ...base(),
      'GET /api/mail/mailboxes/xyz/folders': { status: 404, body: { detail: { code: 'mailbox_not_found' } } },
    });
    const router = renderAt('/mail/xyz/inbox');
    await waitFor(() => expect(router.state.location.pathname).toBe('/404'));
  });

  it('W2 IMAP error: banner "Nepodarilo sa načítať priečinok" with Skúsiť znova → refresh', async () => {
    const view = foldersView();
    view.sync = { state: 'error', error: 'unavailable', last_synced_at: null };
    const api = mockApi({ ...base(view), 'POST /api/mail/mailboxes/default/refresh': { body: foldersView() } });
    renderAt();
    const banner = await screen.findByText('Nepodarilo sa načítať priečinok – skúšame znova.');
    fireEvent.click(within(banner.parentElement as HTMLElement).getByRole('button', { name: 'Skúsiť znova' }));
    await waitFor(() => expect(screen.queryByText('Nepodarilo sa načítať priečinok – skúšame znova.')).toBeNull());
    expect(api.calls.some((c) => c.key === 'POST /api/mail/mailboxes/default/refresh')).toBe(true);
  });

  it('W1c a sync that finds a changed password logs out to W1c', async () => {
    mockApi({
      ...base(),
      'POST /api/mail/mailboxes/default/refresh': {
        status: 401,
        body: { detail: { code: 'unauthenticated', reason: 'password_changed' } },
      },
    });
    const router = renderAt();
    fireEvent.click(await screen.findByRole('button', { name: 'Obnoviť' }));
    await waitFor(() => expect(router.state.location.search).toBe('?reason=password-changed'));
  });

  it('G6 offline banner', async () => {
    mockApi(base());
    const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    renderAt();
    expect(await screen.findByText('Ste offline – zobrazujeme uložené správy, odoslanie počká.')).toBeInTheDocument();
    online.mockRestore();
  });

  it('G7 dragging a file shows the drop zone; dropping never opens the file', async () => {
    mockApi(base());
    renderAt();
    await folderNav();
    const dataTransfer = { types: ['Files'] };
    act(() => {
      window.dispatchEvent(Object.assign(new Event('dragenter'), { dataTransfer }));
    });
    expect(screen.getByText('Pustite súbor sem – doklad dodávateľa alebo objednávka')).toBeInTheDocument();
    const drop = Object.assign(new Event('drop', { cancelable: true }), { dataTransfer });
    act(() => {
      window.dispatchEvent(drop);
    });
    expect(drop.defaultPrevented).toBe(true);
    expect(screen.queryByText('Pustite súbor sem – doklad dodávateľa alebo objednávka')).toBeNull();
  });
});

function Pusher() {
  const push = useToast();
  return (
    <>
      <button type="button" onClick={() => push({ message: `t${Date.now()}-${Math.random()}` })}>
        push
      </button>
      <button
        type="button"
        onClick={() => push({ kind: 'success', message: 'undo', action: { label: 'Späť', onClick: () => undefined } })}
      >
        undo
      </button>
    </>
  );
}

describe('G4 toast stack', () => {
  afterEach(() => vi.useRealTimers());

  it('G4 shows at most 3 toasts, plain ones hide after 5 s, with "Späť" after 10 s', () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Pusher />
      </ToastProvider>,
    );
    for (let i = 0; i < 4; i += 1) fireEvent.click(screen.getByText('push'));
    expect(screen.getAllByRole('status')).toHaveLength(3);
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.queryAllByRole('status')).toHaveLength(0);
    fireEvent.click(screen.getByText('undo'));
    act(() => vi.advanceTimersByTime(9000));
    expect(screen.getByRole('button', { name: 'Späť' })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1100));
    expect(screen.queryByRole('button', { name: 'Späť' })).toBeNull();
  });

  it('G4 hovering pauses the timer', () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Pusher />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText('push'));
    const toast = screen.getByRole('status');
    act(() => vi.advanceTimersByTime(3000));
    fireEvent.mouseEnter(toast);
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByRole('status')).toBeInTheDocument();
    fireEvent.mouseLeave(toast);
    act(() => vi.advanceTimersByTime(2100));
    expect(screen.queryByRole('status')).toBeNull();
  });
});
