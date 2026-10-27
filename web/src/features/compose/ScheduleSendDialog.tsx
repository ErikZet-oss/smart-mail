import { Clock } from 'lucide-react';
import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';

type Preset = 'tomorrow' | 'monday' | 'custom';

type Props = {
  onCancel: () => void;
  onSchedule: (when: Date) => void;
  busy?: boolean;
};

function atLocal(day: Date, hours: number, minutes: number): Date {
  const d = new Date(day);
  d.setHours(hours, minutes, 0, 0);
  return d;
}

function tomorrowEight(): Date {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return atLocal(d, 8, 0);
}

function nextMondayEight(): Date {
  const d = new Date();
  const day = d.getDay(); // 0 Sun … 6 Sat
  const add = day === 1 ? 7 : (8 - day) % 7 || 7;
  d.setDate(d.getDate() + add);
  return atLocal(d, 8, 0);
}

function formatShort(d: Date, locale: string): string {
  return d.toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'numeric' });
}

/** W4c Naplánovať odoslanie — presets + custom datetime (SCREENS_SPEC). */
export function ScheduleSendDialog({ onCancel, onSchedule, busy }: Props) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const tomorrow = useMemo(() => tomorrowEight(), []);
  const monday = useMemo(() => nextMondayEight(), []);
  const [preset, setPreset] = useState<Preset>('tomorrow');
  const [customDate, setCustomDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 2);
    return d.toISOString().slice(0, 10);
  });
  const [customTime, setCustomTime] = useState('08:00');

  function resolve(): Date | null {
    if (preset === 'tomorrow') return tomorrow;
    if (preset === 'monday') return monday;
    const [y, m, day] = customDate.split('-').map(Number);
    const [hh, mm] = customTime.split(':').map(Number);
    if (!y || !m || !day || hh === undefined || mm === undefined) return null;
    const d = new Date(y, m - 1, day, hh, mm, 0, 0);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  const locale = i18n.language?.startsWith('sk') ? 'sk-SK' : i18n.language;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4"
      data-testid="schedule-send-dialog"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-[420px] max-w-full rounded-lg bg-bg-canvas shadow-e3"
      >
        <div className="border-b border-border-default px-5 py-4">
          <h2 id={titleId} className="type-heading text-text-primary">
            {t('compose.scheduleTitle')}
          </h2>
        </div>
        <fieldset className="flex flex-col gap-2 px-5 py-4">
          <legend className="sr-only">{t('compose.scheduleTitle')}</legend>
          <label className="flex cursor-pointer items-center gap-3 rounded-sm px-2 py-2 hover:bg-bg-subtle">
            <input
              type="radio"
              name="schedule-preset"
              checked={preset === 'tomorrow'}
              onChange={() => setPreset('tomorrow')}
            />
            <span className="type-body flex-1 text-text-primary">{t('compose.scheduleTomorrow')}</span>
            <span className="type-caption text-text-secondary">{formatShort(tomorrow, locale)}</span>
          </label>
          <label className="flex cursor-pointer items-center gap-3 rounded-sm px-2 py-2 hover:bg-bg-subtle">
            <input
              type="radio"
              name="schedule-preset"
              checked={preset === 'monday'}
              onChange={() => setPreset('monday')}
            />
            <span className="type-body flex-1 text-text-primary">{t('compose.scheduleMonday')}</span>
            <span className="type-caption text-text-secondary">{formatShort(monday, locale)}</span>
          </label>
          <label className="flex cursor-pointer items-center gap-3 rounded-sm px-2 py-2 hover:bg-bg-subtle">
            <input
              type="radio"
              name="schedule-preset"
              checked={preset === 'custom'}
              onChange={() => setPreset('custom')}
            />
            <span className="type-body text-text-primary">{t('compose.scheduleCustom')}</span>
          </label>
          <div className={`mt-1 flex gap-2 pl-8 ${preset === 'custom' ? '' : 'pointer-events-none opacity-50'}`}>
            <input
              type="date"
              value={customDate}
              onChange={(e) => setCustomDate(e.target.value)}
              className="type-body h-9 flex-1 rounded-sm border border-border-default px-2"
              aria-label={t('compose.scheduleDate')}
            />
            <input
              type="time"
              value={customTime}
              onChange={(e) => setCustomTime(e.target.value)}
              className="type-body h-9 w-28 rounded-sm border border-border-default px-2"
              aria-label={t('compose.scheduleTime')}
            />
          </div>
          <p className="type-caption mt-3 flex items-start gap-2 text-text-secondary">
            <Clock size={14} className="mt-0.5 shrink-0" aria-hidden />
            {t('compose.scheduleOfflineInfo')}
          </p>
        </fieldset>
        <div className="flex justify-end gap-2 border-t border-border-default px-5 py-3">
          <Button type="button" variant="secondary" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            icon={<Clock size={16} />}
            disabled={busy}
            onClick={() => {
              const when = resolve();
              if (when && when.getTime() > Date.now()) onSchedule(when);
            }}
          >
            {t('compose.scheduleConfirm')}
          </Button>
        </div>
      </div>
    </div>
  );
}
