import { useQuery } from '@tanstack/react-query';

import { api } from '../../lib/api';

export type SystemFeatures = { money: boolean };

type Info = { admin_contact_email: string | null; features?: SystemFeatures };

const INFO_KEY = ['system', 'info'] as const;

async function fetchInfo(): Promise<Info> {
  return api<Info>('GET', '/api/system/info', undefined, { global: false });
}

/** Feature flags from `/api/system/info` (Money UI off on pilot deploy). */
export function useFeatures(): SystemFeatures {
  const q = useQuery({ queryKey: INFO_KEY, queryFn: fetchInfo, staleTime: 60_000 });
  return q.data?.features ?? { money: false };
}

/** Same flags plus whether they arrived — a screen that redirects without a flag must wait for them. */
export function useFeaturesState(): SystemFeatures & { loaded: boolean } {
  const q = useQuery({ queryKey: INFO_KEY, queryFn: fetchInfo, staleTime: 60_000 });
  return { ...(q.data?.features ?? { money: false }), loaded: q.isSuccess };
}
