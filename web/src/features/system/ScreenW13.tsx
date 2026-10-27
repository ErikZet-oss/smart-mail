import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { TOUR_KEY } from './systemUi';

type Step = { id: string; titleKey: string; bodyKey: string };

/** Desktop Phase-1 tour (AI / Dnes / Asistent steps deferred — those screens are not in Phase 1). */
const DESKTOP: Step[] = [
  { id: 'toolbar', titleKey: 'tour.d1.title', bodyKey: 'tour.d1.body' },
  { id: 'folders', titleKey: 'tour.d2.title', bodyKey: 'tour.d2.body' },
  { id: 'search', titleKey: 'tour.d3.title', bodyKey: 'tour.d3.body' },
  { id: 'classic', titleKey: 'tour.d4.title', bodyKey: 'tour.d4.body' },
  { id: 'settings', titleKey: 'tour.d5.title', bodyKey: 'tour.d5.body' },
];

const DESKTOP_BRANCH: Step = { id: 'person', titleKey: 'tour.d6.title', bodyKey: 'tour.d6.body' };

/** M-W13 — three mobile steps. */
const MOBILE: Step[] = [
  { id: 'm1', titleKey: 'tour.m1.title', bodyKey: 'tour.m1.body' },
  { id: 'm2', titleKey: 'tour.m2.title', bodyKey: 'tour.m2.body' },
  { id: 'm3', titleKey: 'tour.m3.title', bodyKey: 'tour.m3.body' },
];

type Props = { onClose: () => void };

/** W13 / M-W13 Úvodná prehliadka. */
export function ScreenW13({ onClose }: Props) {
  const { t } = useTranslation();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const branchExtra = me.data?.kind === 'branch';
  const steps = mobile ? MOBILE : branchExtra ? [...DESKTOP, DESKTOP_BRANCH] : DESKTOP;
  const [index, setIndex] = useState(0);
  const step = steps[index] ?? steps[0];

  function finish() {
    localStorage.setItem(TOUR_KEY, 'done');
    onClose();
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        localStorage.setItem(TOUR_KEY, 'done');
        onClose();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!step) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tour-title"
      data-testid={mobile ? 'screen-m-w13' : 'screen-w13'}
    >
      <div className="w-full max-w-md rounded-md border border-border-default bg-bg-canvas p-5 shadow-lg">
        <p className="type-caption mb-2 text-text-tertiary">
          {t('tour.progress', { n: index + 1, total: steps.length })}
        </p>
        <h1 id="tour-title" className="type-heading text-text-primary">
          {t(step.titleKey)}
        </h1>
        <p className="type-body mt-2 text-text-secondary">{t(step.bodyKey)}</p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button type="button" variant="secondary" onClick={finish}>
            {t('tour.skip')}
          </Button>
          {index < steps.length - 1 ? (
            <Button type="button" onClick={() => setIndex((i) => i + 1)}>
              {t('tour.next')}
            </Button>
          ) : (
            <Button type="button" onClick={finish}>
              {t('tour.done')}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Auto-open tour once per browser after first signed-in shell mount. */
// eslint-disable-next-line react-refresh/only-export-components -- tour helper next to ScreenW13
export function maybeStartTour(open: (panel: 'tour') => void) {
  try {
    if (localStorage.getItem(TOUR_KEY) === 'done') return;
    // Playwright sets webdriver; keep e2e free of the auto-tour unless a test clears TOUR_KEY.
    if (navigator.webdriver) return;
    open('tour');
  } catch {
    /* private mode */
  }
}
