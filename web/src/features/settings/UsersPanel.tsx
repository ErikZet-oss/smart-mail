import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Check, Plus, Search, User } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import {
  createUser,
  fetchAdminBranches,
  fetchUsers,
  patchUser,
  ROLES,
  type AdminUser,
  type RoleId,
} from './settingsApi';
import { adminErrorText, INPUT } from './adminUi';

/** Figma settings field row: label + help on the left (300 px), control on the right (440 px). */
export function FormRow({
  label,
  help,
  htmlFor,
  children,
}: {
  label: string;
  help?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 sm:grid sm:grid-cols-[300px_minmax(0,440px)] sm:items-center sm:gap-x-6">
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="type-small block text-text-primary">
          {label}
        </label>
        {help ? <p className="type-caption mt-0.5 text-text-secondary">{help}</p> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled,
}: {
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-sm bg-bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          disabled={disabled}
          onClick={() => onChange(o.id)}
          className={`type-body rounded-xs px-3 py-1.5 ${
            value === o.id ? 'bg-bg-canvas font-semibold text-text-primary shadow-e1' : 'text-text-secondary'
          } disabled:opacity-60`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function userSubtitle(t: ReturnType<typeof useTranslation>['t'], user: AdminUser): string {
  const kind = t(`settings.users.${user.kind}`);
  const detail =
    user.kind === 'branch' ? (user.branch_name ?? '—') : user.person ? t(`settings.roles.${user.person.role}`) : '—';
  return [kind, detail, user.active ? null : t('settings.users.inactive')].filter(Boolean).join(' · ');
}

/** W12-10 Používatelia a role (#33): accounts list, create, kind/branch/role/status, conversion to a branch login. */
export function UsersPanel() {
  const { t } = useTranslation();
  const users = useQuery({ queryKey: ['settings', 'users'], queryFn: fetchUsers });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const list = (users.data ?? []).filter((u) => u.email.includes(query.trim().toLowerCase()));
  const current = (users.data ?? []).find((u) => u.id === selectedId) ?? list[0] ?? null;

  return (
    <div className="flex flex-col gap-6 lg:flex-row" data-testid="users-panel">
      <div className="flex w-full shrink-0 flex-col gap-2 lg:w-72">
        <div className="flex items-center gap-2">
          <label className="relative min-w-0 flex-1">
            <Search
              size={16}
              aria-hidden="true"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
            />
            <input
              className={`${INPUT} pl-9`}
              placeholder={t('settings.users.search')}
              aria-label={t('settings.users.search')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <Button type="button" variant="secondary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden="true" />
            {t('settings.users.create')}
          </Button>
        </div>
        <ul className="flex flex-col border-y border-border-default">
          {list.map((u) => (
            <li key={u.id} className="border-b border-border-default last:border-b-0">
              <button
                type="button"
                aria-current={u.id === current?.id ? 'true' : undefined}
                onClick={() => setSelectedId(u.id)}
                className={`flex w-full items-start gap-3 px-3 py-2.5 text-left ${
                  u.id === current?.id ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                }`}
              >
                {u.kind === 'branch' ? (
                  <Building2 size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-text-secondary" />
                ) : (
                  <User size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-text-secondary" />
                )}
                <span className="min-w-0">
                  <span
                    className={`type-body block truncate ${u.id === current?.id ? 'text-brand-primary-700' : 'text-text-primary'}`}
                  >
                    {u.email}
                  </span>
                  <span className="type-small block truncate text-text-secondary">{userSubtitle(t, u)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {current ? (
        <UserDetail key={current.id} user={current} />
      ) : (
        <p className="type-body text-text-secondary">{t('settings.users.empty')}</p>
      )}
      {creating ? <CreateUserDialog onClose={() => setCreating(false)} onCreated={(id) => setSelectedId(id)} /> : null}
    </div>
  );
}

function UserDetail({ user }: { user: AdminUser }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ['settings', 'branches'], queryFn: fetchAdminBranches });
  const [kind, setKind] = useState(user.kind);
  const [branchId, setBranchId] = useState(user.branch_id ?? '');
  const [role, setRole] = useState<RoleId>(user.person?.role ?? 'sales');
  const [active, setActive] = useState(user.active);
  const [confirm, setConfirm] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      patchUser(user.id, {
        active,
        kind,
        branch_id: kind === 'branch' ? branchId || null : null,
        ...(kind === 'personal' ? { role } : {}),
      }),
    onSuccess: () => {
      setConfirm(false);
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'users'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
    },
    onError: () => setConfirm(false),
  });

  const converting = user.kind === 'personal' && kind === 'branch';
  const branchName = String(branches.data?.find((b) => String(b.id) === branchId)?.name ?? '');
  const submit = () => (converting && branchId ? setConfirm(true) : save.mutate());

  return (
    <div className="flex min-w-0 max-w-3xl flex-1 flex-col gap-5" data-testid="user-detail">
      <h2 className="type-heading text-text-primary">{t('settings.users.account')}</h2>
      {save.isError ? <Banner kind="danger" message={adminErrorText(t, save.error)} /> : null}
      <FormRow label={t('settings.users.email')} help={t('settings.users.emailHelp')} htmlFor="user-email">
        <input id="user-email" className={INPUT} value={user.email} readOnly disabled />
      </FormRow>
      <FormRow label={t('settings.users.kind')} help={t('settings.users.kindHelp')}>
        <Segmented
          label={t('settings.users.kind')}
          value={kind}
          onChange={setKind}
          options={[
            { id: 'personal', label: t('settings.users.personal') },
            { id: 'branch', label: t('settings.users.branch') },
          ]}
        />
      </FormRow>
      {kind === 'branch' ? (
        <FormRow label={t('settings.users.branchField')} help={t('settings.users.branchHelp')} htmlFor="user-branch">
          <select id="user-branch" className={INPUT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
            <option value="">{t('settings.users.branchPick')}</option>
            {(branches.data ?? []).map((b) => (
              <option key={String(b.id)} value={String(b.id)}>
                {String(b.name)}
              </option>
            ))}
          </select>
        </FormRow>
      ) : (
        <FormRow label={t('settings.users.role')} htmlFor="user-role">
          <select id="user-role" className={INPUT} value={role} onChange={(e) => setRole(e.target.value as RoleId)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`settings.roles.${r}`)}
              </option>
            ))}
          </select>
        </FormRow>
      )}
      <FormRow label={t('settings.users.status')} help={t('settings.users.statusHelp')}>
        <Switch checked={active} onChange={setActive} label={t('settings.users.active')} />
      </FormRow>
      <div className="flex gap-2 border-t border-border-default pt-4">
        <Button type="button" onClick={submit} disabled={save.isPending}>
          <Check size={16} aria-hidden="true" />
          {t('settings.save')}
        </Button>
      </div>
      {confirm ? (
        <ConfirmDialog
          title={t('settings.users.convertTitle')}
          body={t('settings.users.convertBody', { email: user.email, branch: branchName })}
          confirmLabel={t('settings.users.convert')}
          busy={save.isPending}
          onConfirm={() => save.mutate()}
          onClose={() => setConfirm(false)}
        />
      ) : null}
    </div>
  );
}

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ['settings', 'branches'], queryFn: fetchAdminBranches });
  const [email, setEmail] = useState('');
  const [kind, setKind] = useState<'personal' | 'branch'>('personal');
  const [branchId, setBranchId] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [role, setRole] = useState<RoleId>('sales');
  const create = useMutation({
    mutationFn: () =>
      createUser(
        kind === 'branch'
          ? { email, kind, branch_id: branchId || null }
          : { email, kind, first_name: firstName, last_name: lastName, role },
      ),
    onSuccess: (user) => {
      toasts.success(t('settings.users.created'));
      void qc.invalidateQueries({ queryKey: ['settings', 'users'] });
      onCreated(user.id);
      onClose();
    },
  });

  return (
    <Dialog
      title={t('settings.users.createTitle')}
      width={520}
      onClose={onClose}
      onSubmit={() => create.mutate()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {t('settings.users.create')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {create.isError ? <Banner kind="danger" message={adminErrorText(t, create.error)} /> : null}
        <label className="flex flex-col gap-1">
          <span className="type-small text-text-primary">{t('settings.users.email')}</span>
          <input
            className={INPUT}
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-autofocus
          />
        </label>
        <Segmented
          label={t('settings.users.kind')}
          value={kind}
          onChange={setKind}
          options={[
            { id: 'personal', label: t('settings.users.personal') },
            { id: 'branch', label: t('settings.users.branch') },
          ]}
        />
        {kind === 'branch' ? (
          <label className="flex flex-col gap-1">
            <span className="type-small text-text-primary">{t('settings.users.branchField')}</span>
            <select className={INPUT} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
              <option value="">{t('settings.users.branchPick')}</option>
              {(branches.data ?? []).map((b) => (
                <option key={String(b.id)} value={String(b.id)}>
                  {String(b.name)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1">
                <span className="type-small text-text-primary">{t('settings.users.firstName')}</span>
                <input className={INPUT} value={firstName} onChange={(e) => setFirstName(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="type-small text-text-primary">{t('settings.users.lastName')}</span>
                <input className={INPUT} value={lastName} onChange={(e) => setLastName(e.target.value)} />
              </label>
            </div>
            <label className="flex flex-col gap-1">
              <span className="type-small text-text-primary">{t('settings.users.role')}</span>
              <select className={INPUT} value={role} onChange={(e) => setRole(e.target.value as RoleId)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(`settings.roles.${r}`)}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>
    </Dialog>
  );
}
