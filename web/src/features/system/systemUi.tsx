import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

export type SystemPanel = 'none' | 'notifications' | 'shortcuts' | 'about' | 'tour';

type Ctx = {
  panel: SystemPanel;
  open: (panel: Exclude<SystemPanel, 'none'>) => void;
  close: () => void;
  restartTour: () => void;
};

const SystemUiCtx = createContext<Ctx | null>(null);

/** Shared host state for W13 tour, W14/M16 notifications, W15 shortcuts, W15b about. */
export function SystemUiProvider({ children }: { children: ReactNode }) {
  const [panel, setPanel] = useState<SystemPanel>('none');
  const value = useMemo<Ctx>(
    () => ({
      panel,
      open: (next) => setPanel(next),
      close: () => setPanel('none'),
      restartTour: () => {
        localStorage.removeItem(TOUR_KEY);
        setPanel('tour');
      },
    }),
    [panel],
  );
  return <SystemUiCtx.Provider value={value}>{children}</SystemUiCtx.Provider>;
}

export const TOUR_KEY = 'sm.tour.v1';

/** Hook for W13–W15b overlays. Kept next to the provider on purpose. */
// eslint-disable-next-line react-refresh/only-export-components -- paired with SystemUiProvider
export function useSystemUi(): Ctx {
  const ctx = useContext(SystemUiCtx);
  if (!ctx) throw new Error('useSystemUi outside SystemUiProvider');
  return ctx;
}
