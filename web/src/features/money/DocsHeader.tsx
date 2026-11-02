import { useQuery } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { UploadDialog } from '../purchasing/UploadDialog';
import { DOCS_TABS, UPLOAD_ROLES } from './docsAccess';

type TabId = (typeof DOCS_TABS)[number]['id'];

/**
 * Doklady hub header (Figma W6e `46:41526`, M13 `85:3245`): title, „Nahrať doklad“ (W6u, `?upload=1`) and the module
 * tabs. A tab the person's role cannot open is hidden; tabs of later phases are shown disabled.
 */
export function DocsHeader({ active, counts = {} }: { active: TabId; counts?: Partial<Record<TabId, number>> }) {
  const { t } = useTranslation();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const [search, setSearch] = useSearchParams();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const role = me.data?.person?.role ?? '';
  const canUpload = UPLOAD_ROLES.has(role);
  const tabClass = (on: boolean) =>
    mobile
      ? `type-label inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm px-3 ${
          on ? 'bg-bg-canvas text-text-primary shadow-e1' : 'text-text-secondary'
        }`
      : `type-label inline-flex h-10 shrink-0 items-center gap-1.5 border-b-2 ${
          on
            ? 'border-brand-primary-600 text-brand-primary-700'
            : 'border-transparent text-text-secondary hover:text-text-primary'
        }`;
  const badge = (n: number | undefined) =>
    n ? <span className="type-micro rounded-full bg-brand-primary-50 px-1.5 text-brand-primary-700">{n}</span> : null;
  return (
    <header className="flex flex-col gap-3 border-b border-border-default px-4 pt-4 md:px-6">
      <div className="flex items-center gap-3">
        <h1 className="type-title min-w-0 flex-1 text-text-primary">{t('documents.title')}</h1>
        <Button
          type="button"
          variant={canUpload ? 'primary' : 'secondary'}
          disabled={!canUpload}
          title={canUpload ? undefined : t('documents.uploadRole')}
          icon={<Upload size={16} aria-hidden="true" />}
          onClick={() => setSearch((prev) => ({ ...Object.fromEntries(prev), upload: '1' }))}
        >
          {t('documents.upload')}
        </Button>
      </div>
      <nav
        aria-label={t('documents.title')}
        data-scroll-x
        className={
          mobile ? 'mb-3 flex gap-1 overflow-x-auto rounded-md bg-bg-subtle p-1' : 'flex gap-4 overflow-x-auto'
        }
      >
        {DOCS_TABS.map((tab) => {
          if (!('path' in tab)) {
            return (
              <span
                key={tab.id}
                aria-disabled="true"
                title={t('documents.later', { phase: tab.phase })}
                className={`${tabClass(false)} cursor-not-allowed text-text-tertiary`}
              >
                {t(`documents.tabs.${tab.id}`)}
              </span>
            );
          }
          if (!(tab.roles as readonly string[]).includes(role)) return null;
          const on = tab.id === active;
          return (
            <Link
              key={tab.id}
              to={tab.path}
              aria-current={on ? 'page' : undefined}
              ref={(node) => {
                if (on && mobile && node) node.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
              }}
              className={tabClass(on)}
            >
              {t(`documents.tabs.${tab.id}`)}
              {badge(counts[tab.id])}
            </Link>
          );
        })}
      </nav>
      {search.get('upload') === '1' && canUpload ? (
        <UploadDialog
          onClose={() =>
            setSearch((prev) => {
              const next = new URLSearchParams(prev);
              next.delete('upload');
              return next;
            })
          }
        />
      ) : null}
    </header>
  );
}
