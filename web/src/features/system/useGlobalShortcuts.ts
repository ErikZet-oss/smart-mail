import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { useSystemUi } from './systemUi';

/**
 * Phase-1 global shortcuts (UX_SPEC §6 subset): `?` help, `C` compose, `/` search, `G I` inbox.
 * Skips when focus is in an editable field (except `?` still opens help from body).
 */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const { open, panel } = useSystemUi();

  useEffect(() => {
    let gPending = false;
    let gTimer: number | undefined;

    function editable(el: EventTarget | null): boolean {
      if (!(el instanceof HTMLElement)) return false;
      const tag = el.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
    }

    function onKey(e: KeyboardEvent) {
      if (panel !== 'none' && e.key !== 'Escape') return;
      if (e.altKey || e.metaKey) return;

      // `?` or Shift+/ (layouts where key stays `/` with shift)
      if (!e.ctrlKey && !editable(e.target) && (e.key === '?' || (e.key === '/' && e.shiftKey))) {
        e.preventDefault();
        open('shortcuts');
        return;
      }

      if (editable(e.target)) return;

      if (e.key === 'c' && !e.ctrlKey && !e.shiftKey) {
        e.preventDefault();
        navigate('/compose');
        return;
      }
      if (e.key === '/' && !e.ctrlKey && !e.shiftKey) {
        e.preventDefault();
        navigate('/search');
        return;
      }
      if (e.key.toLowerCase() === 'g' && !e.ctrlKey && !e.shiftKey) {
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
      }
    }

    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.clearTimeout(gTimer);
    };
  }, [navigate, open, panel]);
}
