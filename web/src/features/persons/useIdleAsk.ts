import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const ACTIVITY = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

/**
 * Branch setting "Pýtať sa po nečinnosti" (PRODUCT_SPEC §2.0): after `minutes` without any input on a shared branch
 * PC the picker comes back with the current person preselected. `null` = off.
 */
export function useIdleAsk(minutes: number | null | undefined, enabled: boolean): void {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.pathname + location.search;

  useEffect(() => {
    if (!enabled || !minutes || minutes <= 0) return;
    let timer = 0;
    const restart = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => navigate('/who', { replace: false, state: { from } }), minutes * 60_000);
    };
    restart();
    for (const name of ACTIVITY) window.addEventListener(name, restart, { passive: true });
    return () => {
      window.clearTimeout(timer);
      for (const name of ACTIVITY) window.removeEventListener(name, restart);
    };
  }, [minutes, enabled, navigate, from]);
}
