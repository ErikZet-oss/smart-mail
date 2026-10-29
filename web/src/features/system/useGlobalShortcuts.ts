import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchPrefs, PREFS_KEY } from '../prefs/prefsApi';
import { dispatchMailShortcut, isEditable, matchShortcut, modalOpen } from './shortcuts';
import { useSystemUi } from './systemUi';

/** Inside a menu or on a button/link, Enter and the arrows keep their native meaning. */
function nativeKeys(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.closest('[role="menu"], [role="menuitem"], button, a[href]') !== null;
}

/**
 * The one keydown listener for UX_SPEC §6 (#93): `?`, `C`, `/`, `G I` here; list and message keys go to the handlers
 * the mail screen registered (`registerMailShortcuts`). Never while typing or while a modal is open, and not at all
 * when Settings › Klávesové skratky is off.
 */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const { open, panel } = useSystemUi();
  const prefs = useQuery({ queryKey: PREFS_KEY, queryFn: fetchPrefs });
  const enabled = prefs.data?.shortcuts?.enabled !== false;

  useEffect(() => {
    if (!enabled) return;
    let gPending = false;
    let gTimer: number | undefined;

    function onKey(e: KeyboardEvent) {
      if (panel !== 'none' || e.defaultPrevented) return;
      if (isEditable(e.target) || modalOpen()) return;

      if (!e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey && e.key.toLowerCase() === 'g') {
        gPending = true;
        window.clearTimeout(gTimer);
        gTimer = window.setTimeout(() => {
          gPending = false;
        }, 800);
        return;
      }
      if (gPending && e.key.toLowerCase() === 'i') {
        e.preventDefault();
        gPending = false;
        navigate('/mail/default/inbox');
        return;
      }

      const id = matchShortcut(e);
      if (!id) return;
      if (id === 'help') {
        e.preventDefault();
        open('shortcuts');
      } else if (id === 'compose') {
        e.preventDefault();
        navigate('/compose');
      } else if (id === 'search') {
        e.preventDefault();
        navigate('/search');
      } else {
        if ((id === 'open' || id === 'up' || id === 'down') && nativeKeys(e.target)) return;
        if (dispatchMailShortcut(id)) e.preventDefault();
      }
    }

    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.clearTimeout(gTimer);
    };
  }, [enabled, navigate, open, panel]);
}
