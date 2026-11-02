import { useQuery } from '@tanstack/react-query';
import { Navigate } from 'react-router-dom';

import { fetchMe } from '../auth/authApi';
import { useFeaturesState } from '../system/features';
import { firstDocsTab } from './docsAccess';

/** W6 `/docs` → the first Doklady tab the person's role may open (SCREENS_SPEC §1); none → 403. */
export function ScreenW6() {
  const features = useFeaturesState();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  if (!features.loaded || !me.data) return null;
  if (!features.money) return <Navigate to="/404" replace />;
  return <Navigate to={firstDocsTab(me.data.person?.role) ?? '/403'} replace />;
}
