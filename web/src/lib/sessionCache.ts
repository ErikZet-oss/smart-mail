import type { QueryClient, QueryFunction, QueryKey } from '@tanstack/react-query';

import { PICKER_KEY } from '../features/persons/personsApi';

/** `['me']` and the Kto ste? picker stay. An open compose draft stays too (PRODUCT_SPEC §2.0):
 * the draft keeps its signature instead of being rebuilt for the new person. */
export function keptOnPersonChange(key: QueryKey): boolean {
  if (key.length === 1 && key[0] === 'me') return true;
  if (key.length === PICKER_KEY.length && key.every((part, index) => part === PICKER_KEY[index])) return true;
  if (key[0] === 'compose') return true;
  return false;
}

function isPicker(key: QueryKey): boolean {
  return key.length === PICKER_KEY.length && key.every((part, index) => part === PICKER_KEY[index]);
}

/** After Kto ste? or a person switch: drop every other cache, then reload what is on screen.
 * The open compose draft is not refetched, so its signature block stays put. */
export async function refreshAfterPersonChange(client: QueryClient): Promise<void> {
  const reload = client
    .getQueryCache()
    .findAll({ type: 'active' })
    .filter((query) => {
      const key = query.queryKey;
      if (key[0] === 'compose') return false;
      if (key.length === 1 && key[0] === 'me') return false;
      return typeof query.options.queryFn === 'function';
    })
    .map((query) => ({
      queryKey: query.queryKey,
      queryFn: query.options.queryFn as QueryFunction,
      kept: keptOnPersonChange(query.queryKey),
    }));

  client.removeQueries({ predicate: (query) => !keptOnPersonChange(query.queryKey) });

  await Promise.all(
    reload.map(async ({ queryKey, queryFn, kept }) => {
      try {
        if (kept && isPicker(queryKey)) {
          await client.refetchQueries({ queryKey, exact: true, type: 'active' });
          return;
        }
        if (kept) return;
        await client.fetchQuery({ queryKey, queryFn });
      } catch {
        // One stale list failing must not undo the person change. That screen shows its own error.
      }
    }),
  );
}
