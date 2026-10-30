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
