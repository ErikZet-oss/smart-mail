import { expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #127 W2 folder menu „Stiahnuť priečinok (.zip)…“ → range + estimate → background job → progress → download.
// No Figma frame exists for this dialog; it is built from the Dialog component.

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

test('#127 folder backup: dialog, estimate, progress, download link', async ({ page }, info) => {
  const view = foldersView();
  const folder = view.folders.find((f) => f.name === 'Dodávatelia');
  if (!folder) throw new Error('fixture has no Dodávatelia');
  const estimates: unknown[] = [];
  const started: unknown[] = [];
  let polls = 0;
  const status = (over: object) => ({
    id: 'exp1',
    status: 'running',
    done: 0,
    total: 0,
    bytes: 0,
    archive_size: 0,
    filename: 'smartmail-dodavatelia-2026-10-30.zip',
    expires_at: null,
    downloaded_at: null,
    error: null,
    folder_names: ['Dodávatelia'],
    ...over,
  });
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/exports/estimate': (payload) => {
      estimates.push(payload);
      return { body: { folders: 1, messages: 1234, bytes: 52_428_800 } };
    },
    'POST /api/mail/mailboxes/default/exports': (payload) => {
      started.push(payload);
      return { status: 202, body: status({ status: 'queued' }) };
    },
    'GET /api/mail/exports/exp1': () => {
      polls += 1;
      return {
        body:
          polls < 2
            ? status({ done: 600, total: 1234 })
            : status({ status: 'ready', done: 1234, total: 1234, archive_size: 41_943_040 }),
      };
    },
  });
  await page.goto('/mail/default/inbox');
  await page.getByRole('link', { name: /^Dodávatelia/ }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Stiahnuť priečinok (.zip)…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Stiahnuť priečinok Dodávatelia' });
  await expect(dialog.getByTestId('export-estimate')).toHaveText('Približne 1234 správ, 50,0 MB.');

  await dialog.getByRole('radio', { name: /Staršie ako/ }).check();
  await dialog.getByLabel('Počet mesiacov').fill('6');
  await expect.poll(() => estimates.at(-1)).toMatchObject({ range: { kind: 'older', months: 6 } });
  await shot(page, `issue127-export-dialog-${info.project.name}`);

  await dialog.getByRole('button', { name: 'Pripraviť archív' }).click();
  await expect
    .poll(() => started.at(-1))
    .toEqual({ folder_ids: [folder.id], include_children: false, range: { kind: 'older', months: 6 } });
  await expect(dialog.getByRole('progressbar')).toBeVisible();
  const link = dialog.getByRole('link', { name: 'Stiahnuť archív' });
  await expect(link).toHaveAttribute('href', '/api/mail/exports/exp1/download', { timeout: 10_000 });
  await expect(dialog).toContainText('Archív je pripravený: 1234 správ, 40,0 MB.');
  await expect(dialog).toContainText('Odkaz platí 24 hodín');
  await shot(page, `issue127-export-ready-${info.project.name}`);
});

test('#127 a second export of the same mailbox explains it is running', async ({ page }) => {
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/exports/estimate': { body: { folders: 3, messages: 10, bytes: 2048 } },
    'POST /api/mail/mailboxes/default/exports': {
      status: 409,
      body: { detail: { code: 'export_running' } },
    },
  });
  await page.goto('/mail/default/inbox');
  await page.getByRole('button', { name: 'Menu schránky' }).click();
  await page.getByRole('menuitem', { name: 'Stiahnuť celú schránku (.zip)…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Stiahnuť celú schránku' });
  await dialog.getByRole('button', { name: 'Pripraviť archív' }).click();
  await expect(dialog.getByRole('alert')).toContainText('už pripravuje iný archív');
});

test('#127 part 2: delete the archived messages only after download, with confirm and password', async ({ page }) => {
  let reauthed = false;
  let downloaded: string | null = null;
  let purged = 0;
  const ready = () => ({
    id: 'exp2',
    status: 'ready',
    done: 3,
    total: 3,
    bytes: 3000,
    archive_size: 2048,
    filename: 'smartmail-pilot-2026-10-30.zip',
    expires_at: '2026-10-31T12:00:00Z',
    downloaded_at: downloaded,
    purged_at: purged ? '2026-10-30T12:30:00Z' : null,
    purged,
    error: null,
    folder_names: ['INBOX'],
  });
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/exports/estimate': { body: { folders: 3, messages: 3, bytes: 3000 } },
    'POST /api/mail/mailboxes/default/exports': { status: 202, body: { ...ready(), status: 'queued' } },
    'GET /api/mail/exports/exp2': () => ({ body: ready() }),
    'GET /api/mail/exports/exp2/download': () => {
      downloaded = '2026-10-30T12:10:00Z';
      return { body: {} };
    },
    'POST /api/mail/exports/exp2/purge': () => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      purged = 3;
      return { body: { deleted: 3, folders: ['INBOX'], skipped: {} } };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/mail/default/inbox');
  await page.getByRole('button', { name: 'Menu schránky' }).click();
  await page.getByRole('menuitem', { name: 'Stiahnuť celú schránku (.zip)…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Stiahnuť celú schránku' });
  await dialog.getByRole('button', { name: 'Pripraviť archív' }).click();
  const purgeButton = dialog.getByRole('button', { name: /Vymazať správy zahrnuté v archíve/ });
  await expect(purgeButton).toBeDisabled();
  await expect(dialog).toContainText('Najprv archív stiahnite');

  await dialog.getByRole('link', { name: 'Stiahnuť archív' }).click();
  await expect(purgeButton).toBeEnabled();
  await purgeButton.click();
  const confirm = page.getByRole('dialog', { name: 'Vymazať správy zo servera?' });
  await expect(confirm).toContainText(
    'Natrvalo vymaže 3 správ (3 kB) z priečinkov Doručená pošta. Máte archív uložený?',
  );
  await confirm.getByRole('button', { name: 'Vymazať natrvalo' }).click();
  const password = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await password.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await password.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(page.getByText('Zo servera vymazaných 3 správ.').first()).toBeVisible();
  expect(purged).toBe(3);
});
