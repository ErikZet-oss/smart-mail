import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { RouterProvider } from 'react-router-dom';

import { ErrorBoundary } from '../components/ErrorBoundary';
import { ReauthDialogHost } from '../components/ReauthDialog';
import { ToastProvider } from '../components/Toasts';
import { SendTracker } from '../features/compose/SendTracker';
import { ThemeProvider } from '../features/prefs/ThemeProvider';
import { SystemUiProvider } from '../features/system/systemUi';
import { onGlobalError } from '../lib/api';
import { createRouter, handleGlobalError, routeForError } from './router';

type Router = ReturnType<typeof createRouter>;

export function App({ router: given }: { router?: Router }) {
  const [router] = useState(() => given ?? createRouter());
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }),
  );

  useEffect(() => {
    onGlobalError((error) => {
      const { pathname, search } = router.state.location;
      const current = pathname + search;
      const target = routeForError(error, current);
      // A revoked session must not keep the previous person's lists, settings or drafts.
      if (error.status === 401 && target?.startsWith('/login')) queryClient.clear();
      void handleGlobalError(error, current, (to, options) => router.navigate(to, options));
    });
    return () => onGlobalError(undefined);
  }, [queryClient, router]);

  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <ThemeProvider>
          <SystemUiProvider>
            <ToastProvider>
              <SendTracker router={router} />
              <RouterProvider router={router} future={{ v7_startTransition: true }} />
              {/* after the router: the password prompt stacks above a confirm dialog that triggered it (#77) */}
              <ReauthDialogHost />
            </ToastProvider>
          </SystemUiProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </QueryClientProvider>
  );
}
