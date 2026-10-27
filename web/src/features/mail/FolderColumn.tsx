import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  EllipsisVertical,
  Eraser,
  Flame,
  Folder as FolderIcon,
  FolderPlus,
  HardDrive,
  Inbox,
  MailCheck,
  Pencil,
  Send,
  Settings,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import { ConfirmDialog, PromptDialog } from '../../components/Dialog';
import { Menu, type MenuEntry } from '../../components/Menu';
import { useToasts } from '../../components/toastContext';
import { useMenu } from '../../components/useMenu';
import { ApiError } from '../../lib/api';
import { useFeatures } from '../system/features';
import {
  createFolder,
  deleteFolder,
  EMPTYABLE,
  fetchMailboxes,
  folderRef,
  foldersKey,
  formatCount,
  MAILBOXES_KEY,
  renameFolder,
  runFolderAction,
  type AiCategory,
  type Folder,
  type FolderAction,
  type FoldersView,
  type Quota,
  type SpecialUse,
} from './mailApi';
import { categoryDotClass } from './MessageRow';
import { useFolderLabel } from './useFolderLabel';

const SPECIAL_ICON: Record<SpecialUse, ReactNode> = {
  inbox: <Inbox size={16} />,
  drafts: <Pencil size={16} />,
  sent: <Send size={16} />,
  junk: <Flame size={16} />,
  trash: <Trash2 size={16} />,
};

const MAILBOX_MENU_W = 250;
const FOLDER_MENU_W = 260;

type Dialog =
  | { kind: 'empty'; folder: Folder }
  | { kind: 'delete'; folder: Folder }
  | { kind: 'create'; parent: Folder }
  | { kind: 'rename'; folder: Folder };

type Props = {
  mailboxRef: string;
  view: FoldersView;
  activeRef: string;
  readOnly: boolean;
  classic?: boolean;
  aiCategories?: AiCategory[];
  activeCategory?: string | null;
};

/** G3 folder column (232 px): mailbox header with ⋮, folders in Roundcube order with counts, quota + Money status. */
export function FolderColumn({
  mailboxRef,
  view,
  activeRef,
  readOnly,
  classic = false,
  aiCategories = [],
  activeCategory = null,
}: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const labelOf = useFolderLabel();
  const mailboxes = useQuery({ queryKey: MAILBOXES_KEY, queryFn: fetchMailboxes });
  const mailboxMenu = useMenu<null>();
  const folderMenu = useMenu<Folder>();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  const active = view.folders.find((f) => folderRef(f) === activeRef) ?? null;

  function errorText(error: unknown): string {
    const code = error instanceof ApiError ? error.detail.code : '';
    const known = [
      'folder_exists',
      'folder_name_length',
      'folder_name_reserved',
      'folder_name_characters',
      'mail_server_unavailable',
      'special_folder',
      'person_required',
    ];
    return known.includes(code) ? t(`folders.errors.${code}`) : t('folders.errors.generic');
  }

  const mutation = useMutation({
    mutationFn: async (job: { run: () => Promise<FoldersView>; done: (view: FoldersView) => void }) => {
      const result = await job.run();
      return { result, done: job.done };
    },
    onSuccess: ({ result, done }) => {
      queryClient.setQueryData(foldersKey(mailboxRef), result);
      void queryClient.invalidateQueries({ queryKey: MAILBOXES_KEY });
      done(result);
    },
  });

  function run(runner: () => Promise<FoldersView>, done: (view: FoldersView) => void, inDialog = false) {
    setNameError(null);
    mutation.mutate(
      { run: runner, done },
      {
        onError: (error) => {
          const code = error instanceof ApiError ? error.detail.code : '';
          if (inDialog && code.startsWith('folder_name_')) {
            setNameError(errorText(error));
            return;
          }
          if (inDialog && code === 'folder_exists') {
            setNameError(errorText(error));
            return;
          }
          setDialog(null);
          toasts.error(errorText(error));
        },
      },
    );
  }

  function act(folder: Folder, action: FolderAction) {
    const name = labelOf(folder);
    run(
      () => runFolderAction(mailboxRef, folder.id, action),
      () => {
        setDialog(null);
        toasts.success(t(`folders.done.${action}`, { name }));
      },
    );
  }

  function goTo(folder: Folder | undefined) {
    navigate(`/mail/${encodeURIComponent(mailboxRef)}/${folder ? folderRef(folder) : 'inbox'}`);
  }

  const canEmpty = (f: Folder) => f.special_use !== null && EMPTYABLE.has(f.special_use) && f.total > 0;

  function folderEntries(folder: Folder): MenuEntry[] {
    const special = folder.special_use !== null;
    return [
      {
        kind: 'item',
        id: 'read',
        label: t('folders.menu.markRead'),
        icon: <MailCheck size={16} />,
        disabled: readOnly || folder.unread === 0,
        onSelect: () => act(folder, 'mark-read'),
      },
      {
        kind: 'item',
        id: 'empty',
        label: t('folders.menu.empty'),
        icon: <Eraser size={16} />,
        disabled: readOnly || !canEmpty(folder),
        onSelect: () => setDialog({ kind: 'empty', folder }),
      },
      {
        kind: 'item',
        id: 'create',
        label: t('folders.menu.newChild'),
        icon: <FolderPlus size={16} />,
        disabled: readOnly,
        onSelect: () => setDialog({ kind: 'create', parent: folder }),
      },
      {
        kind: 'item',
        id: 'rename',
        label: t('folders.menu.rename'),
        icon: <Pencil size={16} />,
        disabled: readOnly || special,
        onSelect: () => setDialog({ kind: 'rename', folder }),
      },
      { kind: 'divider', id: 'd1' },
      {
        kind: 'item',
        id: 'delete',
        label: t('folders.menu.delete'),
        icon: <Trash2 size={16} />,
        danger: true,
        disabled: readOnly || special,
        onSelect: () => setDialog({ kind: 'delete', folder }),
      },
    ];
  }

  function mailboxEntries(): MenuEntry[] {
    const list = mailboxes.data ?? [view.mailbox];
    const entries: MenuEntry[] = [{ kind: 'label', id: 'l1', label: t('folders.mailboxMenu.switch') }];
    for (const mailbox of list) {
      entries.push({
        kind: 'item',
        id: `m-${mailbox.id}`,
        label: mailbox.email,
        icon: <Inbox size={16} />,
        checked: mailbox.id === view.mailbox.id,
        onSelect: () => {
          if (mailbox.id !== view.mailbox.id) navigate(`/mail/${mailbox.id}/inbox`);
        },
      });
    }
    if (list.length > 1) {
      entries.push({
        kind: 'item',
        id: 'all',
        label: t('folders.mailboxMenu.all'),
        icon: <Inbox size={16} />,
        disabled: true,
        hint: t('common.comingSoon'),
        onSelect: () => undefined,
      });
    }
    entries.push(
      { kind: 'divider', id: 'd1' },
      { kind: 'label', id: 'l2', label: t('folders.mailboxMenu.actions') },
      {
        kind: 'item',
        id: 'compact',
        label: t('folders.mailboxMenu.compact'),
        icon: <Archive size={16} />,
        disabled: readOnly || !active,
        onSelect: () => active && act(active, 'compact'),
      },
      {
        kind: 'item',
        id: 'empty',
        label: t('folders.menu.empty'),
        icon: <Eraser size={16} />,
        disabled: readOnly || !active || !canEmpty(active),
        onSelect: () => active && setDialog({ kind: 'empty', folder: active }),
      },
      {
        kind: 'item',
        id: 'manage',
        label: t('folders.mailboxMenu.manage'),
        icon: <Settings size={16} />,
        disabled: true,
        hint: t('common.comingSoon'),
        onSelect: () => undefined,
      },
    );
    return entries;
  }

  function onItemContext(event: MouseEvent<HTMLElement>, folder: Folder) {
    event.preventDefault();
    folderMenu.openAt(event.clientX, event.clientY, folder, event.currentTarget);
  }

  function onItemKey(event: KeyboardEvent<HTMLElement>, folder: Folder) {
    if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
      event.preventDefault();
      const box = event.currentTarget.getBoundingClientRect();
      folderMenu.openAt(box.left + 24, box.bottom, folder, event.currentTarget);
    }
  }

  const busy = mutation.isPending;

  return (
    <aside
      aria-label={t('folders.label')}
      className="flex h-full w-full shrink-0 flex-col border-r border-border-default bg-bg-subtle sm:w-[232px]"
    >
      <div className="flex h-14 shrink-0 items-center gap-1 pl-4 pr-2">
        <h2 className="type-body-strong min-w-0 flex-1 truncate text-text-primary" title={view.mailbox.email}>
          {view.mailbox.email}
        </h2>
        <button
          type="button"
          aria-label={t('folders.mailboxMenu.label')}
          aria-haspopup="menu"
          aria-expanded={mailboxMenu.state !== null}
          onClick={(event) => mailboxMenu.openBelow(event.currentTarget, null, true, MAILBOX_MENU_W)}
          className="flex size-8 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500"
        >
          <EllipsisVertical size={16} aria-hidden="true" />
        </button>
      </div>
      <nav aria-label={t('folders.label')} className="min-h-0 flex-1 overflow-y-auto px-2 pb-4 pt-1">
        <ul className="flex flex-col">
          {view.folders.map((folder) => (
            <li key={folder.id}>
              <FolderItem
                folder={folder}
                label={labelOf(folder)}
                to={`/mail/${encodeURIComponent(mailboxRef)}/${folderRef(folder)}`}
                active={!activeCategory && folderRef(folder) === activeRef}
                onContextMenu={(event) => onItemContext(event, folder)}
                onKeyDown={(event) => onItemKey(event, folder)}
              />
            </li>
          ))}
        </ul>
        {!classic && aiCategories.length > 0 ? (
          <div className="mt-3 border-t border-border-default pt-3" data-testid="ai-triage">
            <div className="mb-1 flex items-center gap-1.5 px-2 text-text-tertiary">
              <Sparkles size={14} aria-hidden="true" className="text-brand-primary-500" />
              <span className="type-caption uppercase tracking-wide">{t('ai.triage.title')}</span>
            </div>
            <ul className="flex flex-col">
              {aiCategories.map((cat) => {
                const active = activeCategory === cat.id;
                return (
                  <li key={cat.id}>
                    <Link
                      to={`/mail/${encodeURIComponent(mailboxRef)}/view/${encodeURIComponent(cat.id)}`}
                      aria-current={active ? 'page' : undefined}
                      className={`flex h-8 items-center gap-2 rounded-sm px-2 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
                        active ? 'bg-brand-primary-50 text-text-primary' : 'text-text-secondary hover:bg-bg-muted'
                      }`}
                    >
                      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${categoryDotClass(cat.color_token)}`} />
                      <span className="type-small min-w-0 flex-1 truncate">{cat.label_sk}</span>
                      {cat.count > 0 ? (
                        <span className="type-caption tabular-nums text-text-tertiary">{formatCount(cat.count)}</span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </nav>
      <QuotaRow quota={view.quota} />

      {mailboxMenu.state ? (
        <Menu
          label={t('folders.mailboxMenu.label')}
          entries={mailboxEntries()}
          at={mailboxMenu.state.at}
          width={MAILBOX_MENU_W}
          onClose={mailboxMenu.close}
        />
      ) : null}
      {folderMenu.state ? (
        <Menu
          label={t('folders.menu.label', { name: labelOf(folderMenu.state.target) })}
          entries={folderEntries(folderMenu.state.target)}
          at={folderMenu.state.at}
          width={FOLDER_MENU_W}
          onClose={folderMenu.close}
        />
      ) : null}

      {dialog?.kind === 'empty' ? (
        <ConfirmDialog
          title={t('folders.dialog.emptyTitle', { name: labelOf(dialog.folder) })}
          body={t('folders.dialog.emptyBody', { count: dialog.folder.total })}
          confirmLabel={t('folders.menu.empty')}
          busy={busy}
          onConfirm={() => act(dialog.folder, 'empty')}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === 'delete' ? (
        <ConfirmDialog
          title={t('folders.dialog.deleteTitle', { name: labelOf(dialog.folder) })}
          body={t('folders.dialog.deleteBody', { count: dialog.folder.total })}
          confirmLabel={t('folders.menu.delete')}
          busy={busy}
          onConfirm={() => {
            const folder = dialog.folder;
            run(
              () => deleteFolder(mailboxRef, folder.id),
              () => {
                setDialog(null);
                toasts.success(t('folders.done.delete', { name: labelOf(folder) }));
                if (folderRef(folder) === activeRef) goTo(undefined);
              },
            );
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === 'create' ? (
        <PromptDialog
          title={t('folders.dialog.createChildTitle', { name: labelOf(dialog.parent) })}
          label={t('folders.dialog.nameLabel')}
          submitLabel={t('folders.dialog.create')}
          busy={busy}
          error={nameError}
          onSubmit={(name) => {
            const parentId = dialog.parent.id;
            run(
              () => createFolder(mailboxRef, parentId, name),
              () => {
                setDialog(null);
                toasts.success(t('folders.done.create', { name }));
              },
              true,
            );
          }}
          onClose={() => {
            setNameError(null);
            setDialog(null);
          }}
        />
      ) : null}
      {dialog?.kind === 'rename' ? (
        <PromptDialog
          title={t('folders.dialog.renameTitle', { name: labelOf(dialog.folder) })}
          label={t('folders.dialog.nameLabel')}
          initial={dialog.folder.label}
          submitLabel={t('folders.dialog.rename')}
          busy={busy}
          error={nameError}
          onSubmit={(name) => {
            const folder = dialog.folder;
            run(
              () => renameFolder(mailboxRef, folder.id, name),
              (result) => {
                setDialog(null);
                toasts.success(t('folders.done.rename', { name }));
                if (folderRef(folder) === activeRef) {
                  goTo(result.folders.find((f) => f.parent_id === folder.parent_id && f.label === name));
                }
              },
              true,
            );
          }}
          onClose={() => {
            setNameError(null);
            setDialog(null);
          }}
        />
      ) : null}
    </aside>
  );
}

type ItemProps = {
  folder: Folder;
  label: string;
  to: string;
  active: boolean;
  onContextMenu: (event: MouseEvent<HTMLElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
};

/** Figma `FolderItem` (32 px): icon, label (semibold with unread), blue count pill. */
function FolderItem({ folder, label, to, active, onContextMenu, onKeyDown }: ItemProps) {
  const { t } = useTranslation();
  const unread = folder.unread > 0;
  const className = `flex h-8 items-center gap-2.5 rounded-sm pr-2 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
    active ? 'bg-brand-primary-50 text-brand-primary-700' : 'text-text-primary hover:bg-bg-muted'
  }`;
  const body = (
    <>
      <span aria-hidden="true" className={`flex shrink-0 ${active ? '' : 'text-text-secondary'}`}>
        {folder.special_use ? SPECIAL_ICON[folder.special_use] : <FolderIcon size={16} />}
      </span>
      <span className={`min-w-0 flex-1 truncate ${unread || active ? 'type-body-strong' : 'type-body'}`}>{label}</span>
      {unread ? (
        <span
          aria-hidden="true"
          className="type-micro flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full bg-brand-primary-600 px-1.5 text-text-on-primary"
        >
          {formatCount(folder.unread)}
        </span>
      ) : null}
    </>
  );
  const style = { paddingLeft: 10 + folder.depth * 16 };
  const name = unread ? t('folders.withUnread', { name: label, count: folder.unread }) : label;
  if (!folder.selectable) {
    return (
      <span
        tabIndex={0}
        aria-label={name}
        style={style}
        className={className}
        onContextMenu={onContextMenu}
        onKeyDown={onKeyDown}
      >
        {body}
      </span>
    );
  }
  return (
    <Link
      to={to}
      aria-current={active ? 'page' : undefined}
      aria-label={name}
      style={style}
      className={className}
      onContextMenu={onContextMenu}
      onKeyDown={onKeyDown}
    >
      {body}
    </Link>
  );
}

const QUOTA_BAR = { normal: 'bg-brand-primary-600', warning: 'bg-warning-600', danger: 'bg-danger-600' } as const;
const QUOTA_TEXT = { normal: 'text-text-secondary', warning: 'text-warning-700', danger: 'text-danger-600' } as const;

function megabytes(kb: number): string {
  return new Intl.NumberFormat('sk-SK', { maximumFractionDigits: 1 }).format(kb / 1024);
}

/** Roundcube's quota line (icon + bar + %, red ≥ 90 %) and the Money ● status (Money comes in Phase 3). */
function QuotaRow({ quota }: { quota: Quota | null }) {
  const { t } = useTranslation();
  const { money: moneyFeature } = useFeatures();
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-t border-border-default bg-bg-subtle px-3">
      {quota ? (
        <div
          className="flex items-center gap-2"
          role="meter"
          aria-label={t('folders.quota.label')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={quota.percent}
          aria-valuetext={t('folders.quota.text', {
            percent: quota.percent,
            used: megabytes(quota.used_kb),
            limit: megabytes(quota.limit_kb),
          })}
          title={t('folders.quota.text', {
            percent: quota.percent,
            used: megabytes(quota.used_kb),
            limit: megabytes(quota.limit_kb),
          })}
        >
          <HardDrive size={16} aria-hidden="true" className="shrink-0 text-text-secondary" />
          <span className="h-1.5 w-[84px] overflow-hidden rounded-full bg-bg-muted">
            <span
              className={`block h-full rounded-full ${QUOTA_BAR[quota.level]}`}
              style={{ width: `${Math.min(100, quota.percent)}%` }}
            />
          </span>
          <span
            className={`type-caption whitespace-nowrap ${QUOTA_TEXT[quota.level]}`}
          >{`${quota.percent}\u00a0%`}</span>
        </div>
      ) : null}
      <span className="flex-1" />
      {moneyFeature ? (
        <span className="flex items-center gap-1.5" title={t('folders.money.off')}>
          <span aria-hidden="true" className="size-[7px] rounded-full bg-text-tertiary" />
          <span className="type-caption text-text-secondary">{t('folders.money.label')}</span>
          <span className="sr-only">{t('folders.money.off')}</span>
        </span>
      ) : null}
    </div>
  );
}
