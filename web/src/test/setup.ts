import '@testing-library/jest-dom/vitest';
import { beforeEach } from 'vitest';

import '../i18n';
import { TOUR_KEY } from '../features/system/systemUi';

// The onboarding tour (W13) opens once per browser until TOUR_KEY is "done", and jsdom's localStorage is shared by
// every test in a file. Whether a test saw the tour depended on which test ran first (#121) — so every test starts
// with the tour already seen; a tour test removes the key itself.
beforeEach(() => {
  try {
    localStorage.setItem(TOUR_KEY, 'done');
  } catch {
    /* no storage */
  }
});
