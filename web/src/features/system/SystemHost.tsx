import { useEffect } from 'react';

import { NotificationsPanel } from './NotificationsPanel';
import { ScreenW13, maybeStartTour } from './ScreenW13';
import { ScreenW15 } from './ScreenW15';
import { ScreenW15b } from './ScreenW15b';
import { useSystemUi } from './systemUi';

/** Renders the active system overlay (tour / notifs / shortcuts / about). */
export function SystemHost() {
  const { panel, close, open } = useSystemUi();

  useEffect(() => {
    maybeStartTour(open);
  }, [open]);

  if (panel === 'tour') return <ScreenW13 onClose={close} />;
  if (panel === 'notifications') return <NotificationsPanel onClose={close} />;
  if (panel === 'shortcuts') return <ScreenW15 onClose={close} />;
  if (panel === 'about') return <ScreenW15b onClose={close} />;
  return null;
}
