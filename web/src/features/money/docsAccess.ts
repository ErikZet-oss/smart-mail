/** Roles with at least one Doklady tab today (Phase 3: Upomienky — accounting, sales, admin; SCREENS_SPEC §1). */
export const DOCS_ROLES: ReadonlySet<string> = new Set(['admin', 'sales', 'accounting']);

/** #193: the Doklady entry (rail + bottom nav) shows only with FEATURE_MONEY and a role with an allowed tab.
 * AppShell computes it once from its own `me` and passes it down (no extra queries in the nav). */
export function docsVisible(money: boolean, role: string | null | undefined): boolean {
  return money && DOCS_ROLES.has(role ?? '');
}
