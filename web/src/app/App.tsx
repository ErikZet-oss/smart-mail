import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

type Health = 'checking' | 'ok' | 'down';

export function App() {
  const { t } = useTranslation();
  const [health, setHealth] = useState<Health>('checking');

  useEffect(() => {
    const controller = new AbortController();
    fetch('/healthz', { signal: controller.signal })
      .then((r) => setHealth(r.ok ? 'ok' : 'down'))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === 'AbortError')) setHealth('down');
      });
    return () => controller.abort();
  }, []);

  const statusText = {
    checking: t('phase0.statusChecking'),
    ok: t('phase0.statusOk'),
    down: t('phase0.statusDown'),
  }[health];

  return (
    <main className="flex min-h-full items-center justify-center bg-bg-subtle p-6">
      <section className="w-full max-w-md rounded-lg border border-border-default bg-bg-canvas p-8 text-center">
        <img src="/logo-smart.svg" alt="SMART" className="mx-auto mb-6 h-12" />
        <h1 className="mb-2 text-xl font-bold text-text-primary">{t('phase0.title')}</h1>
        <p className="mb-6 text-text-secondary">{t('phase0.body')}</p>
        <p className="text-sm" role="status">
          <span className="font-semibold">{t('phase0.status')}: </span>
          <span
            data-testid="health"
            className={
              health === 'ok' ? 'text-success-600' : health === 'down' ? 'text-danger-600' : 'text-text-tertiary'
            }
          >
            {statusText}
          </span>
        </p>
      </section>
    </main>
  );
}
