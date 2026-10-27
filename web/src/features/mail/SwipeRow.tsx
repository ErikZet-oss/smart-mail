import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

type Props = {
  children: ReactNode;
  onDone: () => void;
  onSnooze: () => void;
};

const THRESHOLD = 72;

/** M1 swipe: left = Vybavené, right = Odložiť (Phase 1 snooze = toast “coming soon” if not wired). */
export function SwipeRow({ children, onDone, onSnooze }: Props) {
  const { t } = useTranslation();
  const startX = useRef(0);
  const [dx, setDx] = useState(0);
  const dragging = useRef(false);

  return (
    <div className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className={`absolute inset-y-0 left-0 flex w-24 items-center justify-center bg-success-50 text-success-700 ${
          dx > 20 ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <span className="type-caption">{t('mail.toolbar.snooze')}</span>
      </div>
      <div
        aria-hidden="true"
        className={`absolute inset-y-0 right-0 flex w-24 items-center justify-center bg-brand-primary-50 text-brand-primary-800 ${
          dx < -20 ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <span className="type-caption">{t('mail.toolbar.done')}</span>
      </div>
      <div
        className="relative touch-pan-y bg-bg-canvas transition-transform duration-100"
        style={{ transform: `translateX(${dx}px)` }}
        onTouchStart={(e) => {
          dragging.current = true;
          startX.current = e.touches[0]?.clientX ?? 0;
        }}
        onTouchMove={(e) => {
          if (!dragging.current) return;
          const x = e.touches[0]?.clientX ?? startX.current;
          setDx(Math.max(-120, Math.min(120, x - startX.current)));
        }}
        onTouchEnd={() => {
          dragging.current = false;
          if (dx <= -THRESHOLD) onDone();
          else if (dx >= THRESHOLD) onSnooze();
          setDx(0);
        }}
        onTouchCancel={() => {
          dragging.current = false;
          setDx(0);
        }}
      >
        {children}
      </div>
    </div>
  );
}
