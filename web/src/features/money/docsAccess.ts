/** Doklady tabs and who may open them (SCREENS_SPEC §1 W6e / W8b). Future tabs are shown disabled to everybody. */
export const DOCS_TABS = [
  { id: 'delivery-notes', path: '/docs/delivery-notes', roles: ['warehouse', 'accounting', 'admin'] },
  { id: 'orders', phase: 4 },
  { id: 'offers', phase: 6 },
  { id: 'complaints', phase: 4 },
  { id: 'reminders', path: '/docs/reminders', roles: ['accounting', 'sales', 'admin'] },
] as const;

/** Roles of Upomienky (W8b). */
export const DOCS_ROLES: ReadonlySet<string> = new Set(['admin', 'sales', 'accounting']);
/** W6u „Nahrať doklad“ and W6e Dodacie listy (Phase 4a). */
export const UPLOAD_ROLES: ReadonlySet<string> = new Set(['warehouse', 'accounting', 'admin']);

/** The first Doklady tab this role may open (W6 `/docs` redirects there), or null. */
export function firstDocsTab(role: string | null | undefined): string | null {
  for (const tab of DOCS_TABS) {
    if ('roles' in tab && (tab.roles as readonly string[]).includes(role ?? '')) return tab.path;
  }
  return null;
}

/** #193: the Doklady entry (rail + bottom nav) shows only with FEATURE_MONEY and a role with an allowed tab.
 * AppShell computes it once from its own `me` and passes it down (no extra queries in the nav). */
export function docsVisible(money: boolean, role: string | null | undefined): boolean {
  return money && firstDocsTab(role) !== null;
}
