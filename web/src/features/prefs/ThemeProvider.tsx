import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';

import { fetchPrefs, PREFS_KEY, savePrefs, type Prefs, type UiPrefs } from './prefsApi';

type ThemeCtx = {
  prefs: Prefs | undefined;
  classic: boolean;
  theme: UiPrefs['theme'];
  setTheme: (theme: UiPrefs['theme']) => void;
  setClassic: (classic: boolean) => void;
  toggleTheme: () => void;
};

const Ctx = createContext<ThemeCtx | null>(null);

function applyTheme(theme: UiPrefs['theme']) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

/** Loads prefs.ui and applies `data-theme` (tokens.css light/dark). Classic hides AI chrome until Phase 2. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const prefs = useQuery({
    queryKey: PREFS_KEY,
    queryFn: fetchPrefs,
    staleTime: 60_000,
    retry: false,
    // unsigned-in screens still mount the provider; 401 is ignored until AppShell loads mail
  });
  const save = useMutation({
    mutationFn: savePrefs,
    onSuccess: (data) => queryClient.setQueryData(PREFS_KEY, data),
  });

  const ui = prefs.data?.ui;
  useEffect(() => {
    if (ui) applyTheme(ui.theme);
  }, [ui]);

  const value = useMemo<ThemeCtx>(() => {
    const theme = ui?.theme ?? 'system';
    const classic = ui?.classic ?? false;
    const baseUi: UiPrefs = ui ?? { theme: 'system', classic: false, remote_images: 'known', prefer_html: true };
    return {
      prefs: prefs.data,
      classic,
      theme,
      setTheme: (next) => save.mutate({ ui: { ...baseUi, theme: next } }),
      setClassic: (next) => save.mutate({ ui: { ...baseUi, classic: next } }),
      toggleTheme: () => {
        const resolved =
          theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
            ? 'light'
            : 'dark';
        save.mutate({ ui: { ...baseUi, theme: resolved } });
      },
    };
  }, [prefs.data, ui, save]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Hook for theme / classic prefs. Kept next to the provider on purpose (small prefs surface). */
// eslint-disable-next-line react-refresh/only-export-components -- paired with ThemeProvider
export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTheme outside ThemeProvider');
  return ctx;
}
