import { createBrowserRouter, Navigate, type RouteObject } from 'react-router-dom';

import { ScreenW1 } from '../features/auth/ScreenW1';
import { ScreenW1a } from '../features/auth/ScreenW1a';
import { SignedInPlaceholder } from '../features/auth/SignedInPlaceholder';
import { ScreenW16a, ScreenW16b, ScreenW16c } from '../features/system/ScreenW16';
import { ScreenW17 } from '../features/system/ScreenW17';
import { ApiError } from '../lib/api';
import { HOME, ROUTES } from './routes';

export const routeObjects: RouteObject[] = [
  { path: '/', element: <Navigate to={HOME} replace /> },
  { id: ROUTES.W1.id, path: ROUTES.W1.path, element: <ScreenW1 /> },
  { id: ROUTES.W1a.id, path: ROUTES.W1a.path, element: <ScreenW1a /> },
  { id: ROUTES.W1b.id, path: ROUTES.W1b.path, element: <SignedInPlaceholder /> },
  { id: ROUTES.W2.id, path: ROUTES.W2.path, element: <SignedInPlaceholder /> },
  { id: ROUTES.W16a.id, path: ROUTES.W16a.path, element: <ScreenW16a /> },
  { id: ROUTES.W16b.id, path: ROUTES.W16b.path, element: <ScreenW16b /> },
  { id: ROUTES.W16c.id, path: ROUTES.W16c.path, element: <ScreenW16c /> },
  { id: ROUTES.W17.id, path: ROUTES.W17.path, element: <ScreenW17 /> },
  { path: '*', element: <ScreenW16b /> },
];

type Navigate = (to: string, options: { replace: boolean; state: { from: string } }) => unknown;

/** What any screen does with an API error it does not handle itself (W1c, W17, W16a, W16c). */
export function routeForError(error: ApiError, currentPath: string): string | null {
  const { status, detail } = error;
  if (status === 503 && detail.code === 'maintenance') return ROUTES.W17.path;
  if (status === 401) {
    const reason = detail.reason;
    if (reason === 'password_changed') return `${ROUTES.W1.path}?reason=password-changed`;
    if (reason === 'expired') return `${ROUTES.W1.path}?reason=expired`;
    return currentPath.startsWith(ROUTES.W1.path) ? null : ROUTES.W1.path;
  }
  if (status === 403 && detail.code !== 'csrf') return ROUTES.W16a.path;
  if (status >= 500 && detail.code === 'server_error') {
    return `${ROUTES.W16c.path}?ref=${encodeURIComponent(String(detail.ref ?? ''))}`;
  }
  return null;
}

export function handleGlobalError(error: ApiError, currentPath: string, navigate: Navigate): void {
  const target = routeForError(error, currentPath);
  if (target && !currentPath.startsWith(target.split('?')[0] ?? target)) {
    navigate(target, { replace: true, state: { from: currentPath } });
  }
}

export const ROUTER_FUTURE = {
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialHydration: true,
  v7_skipActionErrorRevalidation: true,
} as const;

export function createRouter() {
  return createBrowserRouter(routeObjects, { future: ROUTER_FUTURE });
}
