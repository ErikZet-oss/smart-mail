import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { RouterProvider } from 'react-router-dom';

import { onGlobalError } from '../lib/api';
import { createRouter, handleGlobalError } from './router';

type Router = ReturnType<typeof createRouter>;

export function App({ router: given }: { router?: Router }) {
  const [router] = useState(() => given ?? createRouter());
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }),
  );

  useEffect(() => {
    onGlobalError((error) => {
      const { pathname, search } = router.state.location;
      void handleGlobalError(error, pathname + search, (to, options) => router.navigate(to, options));
    });
    return () => onGlobalError(undefined);
  }, [router]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </QueryClientProvider>
  );
}
