import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

type Props = {
  children: ReactNode;
  onDone: () => void;
};

const THRESHOLD = 72;

/** M1 swipe left = Vybavené only. Right-swipe Odložiť is Phase 5 — omit until it works. */
export function SwipeRow({ children, onDone }: Props) {
  const { t } = useTranslation();
  const startX = useRef(0);
  const [dx, setDx] = useState(0);
  const dragging = useRef(false);

  return (
    <div className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className={`absolute inset-y-0 right-0 flex w-24 items-center justify-center bg-brand-primary-50 text-brand-primary-700 ${
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
          // Left swipe only (negative dx); block right swipe until snooze ships.
          setDx(Math.max(-120, Math.min(0, x - startX.current)));
        }}
        onTouchEnd={() => {
          dragging.current = false;
          if (dx <= -THRESHOLD) onDone();
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
