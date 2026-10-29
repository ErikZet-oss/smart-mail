import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Check, Search, SquarePlus, User } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import {
  createUser,
  fetchAdminBranches,
  fetchMailboxAccess,
  fetchUsers,
  logoutUserEverywhere,
  resetUserTwoFactor,
  patchUser,
  ROLES,
  saveMailboxAccess,
  verifyUserLogin,
  type AdminUser,
  type RoleId,
} from './settingsApi';
import { adminErrorText, INPUT } from './adminUi';
import { SettingsBreadcrumb } from './SettingsNav';

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

function lastLogin(t: ReturnType<typeof useTranslation>['t'], iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso);
  const today = new Date();
  const days = Math.round(
    (new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() -
      new Date(then.getFullYear(), then.getMonth(), then.getDate()).getTime()) /
      86_400_000,
  );
  if (days <= 0) return t('settings.users.today');
  if (days === 1) return t('settings.users.yesterday');
  return then.toLocaleDateString('sk-SK', { day: 'numeric', month: 'numeric' });
}

function userSubtitle(t: ReturnType<typeof useTranslation>['t'], user: AdminUser): string {
  const kind = t(`settings.users.${user.kind}`);
  const detail =
    user.kind === 'branch'
      ? t('settings.users.persons', { count: user.persons_count ?? 0 })
      : user.person
        ? t(`settings.roles.${user.person.role}`)
        : '—';
  return [kind, detail, lastLogin(t, user.last_login_at), user.active ? null : t('settings.users.inactive')]
    .filter(Boolean)
    .join(' · ');
}

/** PRODUCT_SPEC §4 — read-only „Matica oprávnení“ (the API enforces it, the UI only shows it). */
const MATRIX: { key: string; roles: RoleId[] }[] = [
  { key: 'read', roles: ['viewer', 'sales', 'warehouse', 'accounting', 'admin'] },
  { key: 'send', roles: ['sales', 'accounting', 'admin'] },
  { key: 'money', roles: ['sales', 'accounting', 'admin'] },
  { key: 'deliveryNotes', roles: ['warehouse', 'accounting', 'admin'] },
  { key: 'undo', roles: ['sales', 'warehouse', 'accounting', 'admin'] },
  { key: 'override', roles: ['admin'] },
  { key: 'admin', roles: ['admin'] },
];
const MATRIX_ROLES: RoleId[] = ['admin', 'sales', 'warehouse', 'accounting', 'viewer'];

/** W12-10 Používatelia a role (Figma `68:59425`): the accounts as a full-height column with search, „Vytvoriť“ in the
 * header, the detail with „Overiť“, Stav + „Odhlásiť zo všetkých zariadení“, Prístup k schránkam, Matica oprávnení
 * and the Uložiť / Zrušiť bar. On a phone the list sits above the detail. */
export function UsersPanel({ crumbs = [], mobile = true }: { crumbs?: string[]; mobile?: boolean }) {
  const { t } = useTranslation();
  const users = useQuery({ queryKey: ['settings', 'users'], queryFn: fetchUsers });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const list = (users.data ?? []).filter((u) => u.email.includes(query.trim().toLowerCase()));
  const current = (users.data ?? []).find((u) => u.id === selectedId) ?? list[0] ?? null;

  const create = (
    <button
      type="button"
      onClick={() => setCreating(true)}
      className="type-label inline-flex shrink-0 items-center gap-1.5 rounded-xs text-brand-primary-700 hover:underline"
    >
      <SquarePlus size={16} aria-hidden="true" />
      {t('settings.users.create')}
    </button>
  );
  const column = (
    <div
      className={
        mobile
          ? 'flex w-full flex-col gap-2'
          : 'flex w-[var(--layout-settings-list)] shrink-0 flex-col border-r border-border-default bg-bg-canvas'
      }
      data-testid="users-list"
    >
      <div className={mobile ? '' : 'p-3'}>
        <label className="relative block">
          <Search
            size={16}
            aria-hidden="true"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
          />
          <input
            className={`${INPUT} border-transparent bg-bg-subtle pl-9`}
            placeholder={t('settings.users.search')}
            aria-label={t('settings.users.search')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>
      <ul className={`flex flex-col ${mobile ? 'border-y border-border-default' : 'min-h-0 flex-1 overflow-y-auto'}`}>
        {list.map((u) => (
          <li key={u.id} className="border-b border-border-default">
            <button
              type="button"
              aria-current={u.id === current?.id ? 'true' : undefined}
              onClick={() => setSelectedId(u.id)}
              className={`flex w-full items-start gap-3 px-3.5 py-2.5 text-left ${
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
                  className={`type-small block truncate ${u.id === current?.id ? 'font-semibold text-brand-primary-700' : 'text-text-primary'}`}
                >
                  {u.email}
                </span>
                <span className="type-caption block truncate text-text-secondary">{userSubtitle(t, u)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
  const detail = current ? (
    <UserDetail key={current.id} user={current} />
  ) : (
    <p className="type-body text-text-secondary">{t('settings.users.empty')}</p>
  );
  const dialog = creating ? (
    <CreateUserDialog onClose={() => setCreating(false)} onCreated={(id) => setSelectedId(id)} />
  ) : null;

  if (mobile) {
    return (
      <div className="flex min-w-0 flex-col gap-4" data-testid="users-panel">
        <div className="flex justify-end">{create}</div>
        {column}
        {detail}
        {dialog}
      </div>
    );
  }
  return (
    <>
      {column}
      <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas" data-testid="users-panel">
        <header className="flex h-[var(--layout-topbar)] shrink-0 items-center gap-4 border-b border-border-default bg-bg-subtle px-6">
          <div className="min-w-0 flex-1">
            <SettingsBreadcrumb parts={[...crumbs, ...(current ? [current.email] : [])]} />
          </div>
          {create}
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-8 pt-6">
          <h1 className="type-title mb-6 text-text-primary">{t('settings.users.title')}</h1>
          {detail}
        </div>
      </main>
      {dialog}
    </>
  );
}

type Access = { mailbox_id: string; email: string; read: boolean; send: boolean; own: boolean };

function UserDetail({ user }: { user: AdminUser }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ['settings', 'branches'], queryFn: fetchAdminBranches });
  const access = useQuery({
    queryKey: ['settings', 'users', user.id, 'access'],
    queryFn: () => fetchMailboxAccess(user.id),
  });
  const initial = () => ({
    kind: user.kind,
    branchId: user.branch_id ?? '',
    role: (user.person?.role ?? 'sales') as RoleId,
    active: user.active,
    require2fa: Boolean(user.require_2fa),
  });
  const [form, setForm] = useState(initial);
  const [accessEdits, setAccessEdits] = useState<Record<string, Pick<Access, 'read' | 'send'>>>({});
  const [confirm, setConfirm] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [resetting2fa, setResetting2fa] = useState(false);
  const reset2fa = useMutation({
    mutationFn: () => resetUserTwoFactor(user.id),
    onSuccess: () => {
      setResetting2fa(false);
      toasts.success(t('settings.users.twoFactorReset'));
      void qc.invalidateQueries({ queryKey: ['settings', 'users'] });
    },
    onError: (error) => {
      setResetting2fa(false);
      toasts.error(adminErrorText(t, error));
    },
  });
  const rows: Access[] = (access.data ?? []).map((r) => ({ ...r, ...(accessEdits[r.mailbox_id] ?? {}) }));
  const dirty =
    form.kind !== user.kind ||
    form.branchId !== (user.branch_id ?? '') ||
    (form.kind === 'personal' && form.role !== (user.person?.role ?? 'sales')) ||
    form.active !== user.active ||
    form.require2fa !== Boolean(user.require_2fa) ||
    Object.keys(accessEdits).length > 0;

  const save = useMutation({
    mutationFn: async () => {
      await patchUser(user.id, {
        active: form.active,
        kind: form.kind,
        branch_id: form.kind === 'branch' ? form.branchId || null : null,
        ...(form.kind === 'personal' ? { role: form.role } : {}),
        ...(user.kind === 'personal' && form.require2fa !== Boolean(user.require_2fa)
          ? { require_2fa: form.require2fa }
          : {}),
      });
      if (Object.keys(accessEdits).length) {
        await saveMailboxAccess(
          user.id,
          rows.filter((r) => !r.own).map((r) => ({ mailbox_id: r.mailbox_id, read: r.read, send: r.read && r.send })),
        );
      }
    },
    onSuccess: () => {
      setConfirm(false);
      setAccessEdits({});
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'users'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
    },
    onError: () => setConfirm(false),
  });
  const logoutAll = useMutation({
    mutationFn: () => logoutUserEverywhere(user.id),
    onSuccess: (result) => {
      setLoggingOut(false);
      toasts.success(t('settings.users.loggedOut', { count: result.revoked_sessions }));
    },
    onError: (error) => {
      setLoggingOut(false);
      toasts.error(adminErrorText(t, error));
    },
  });

  const converting = user.kind === 'personal' && form.kind === 'branch';
  const branchName = String(branches.data?.find((b) => String(b.id) === form.branchId)?.name ?? '');
  const submit = () => (converting && form.branchId ? setConfirm(true) : save.mutate());
  const setAccess = (row: Access, change: Partial<Pick<Access, 'read' | 'send'>>) => {
    const next = { read: row.read, send: row.send, ...change };
    if (change.send) next.read = true; // Odosielať ako needs Čítať
    if (change.read === false) next.send = false;
    setAccessEdits((prev) => ({ ...prev, [row.mailbox_id]: next }));
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5" data-testid="user-detail">
      {verifyError ? <Banner kind="danger" message={verifyError} /> : null}
      {save.isError ? <Banner kind="danger" message={adminErrorText(t, save.error)} /> : null}
      <h2 className="type-heading text-text-primary">{t('settings.users.account')}</h2>
      <FormRow label={t('settings.users.email')} help={t('settings.users.emailHelp')} htmlFor="user-email">
        <div className="flex gap-2">
          <input id="user-email" className={INPUT} value={user.email} readOnly disabled />
          <Button type="button" variant="secondary" onClick={() => setVerifying(true)}>
            {t('settings.users.verify')}
          </Button>
        </div>
      </FormRow>
      <FormRow label={t('settings.users.kind')} help={t('settings.users.kindHelp')}>
        <Segmented
          label={t('settings.users.kind')}
          value={form.kind}
          onChange={(kind) => setForm((prev) => ({ ...prev, kind }))}
          options={[
            { id: 'personal', label: t('settings.users.personal') },
            { id: 'branch', label: t('settings.users.branch') },
          ]}
        />
      </FormRow>
      {form.kind === 'branch' ? (
        <FormRow label={t('settings.users.branchField')} help={t('settings.users.branchHelp')} htmlFor="user-branch">
          <select
            id="user-branch"
            className={INPUT}
            value={form.branchId}
            onChange={(e) => setForm((prev) => ({ ...prev, branchId: e.target.value }))}
          >
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
          <select
            id="user-role"
            className={INPUT}
            value={form.role}
            onChange={(e) => setForm((prev) => ({ ...prev, role: e.target.value as RoleId }))}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`settings.roles.${r}`)}
              </option>
            ))}
          </select>
        </FormRow>
      )}
      {user.kind === 'personal' ? (
        <FormRow label={t('settings.users.twoFactor')} help={t('settings.users.twoFactorHelp')}>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2" data-testid="user-2fa">
            <Switch
              checked={form.require2fa}
              onChange={(require2fa) => setForm((prev) => ({ ...prev, require2fa }))}
              label={t('settings.users.require2fa')}
            />
            <span
              className={`type-caption rounded-full px-2 py-0.5 ${
                user.totp_enabled ? 'bg-success-50 text-success-700' : 'bg-bg-muted text-text-secondary'
              }`}
            >
              {user.totp_enabled ? t('settings.twoFactor.on') : t('settings.twoFactor.off')}
            </span>
            {user.totp_enabled ? (
              <button
                type="button"
                onClick={() => setResetting2fa(true)}
                className="type-label rounded-xs text-brand-primary-700 hover:underline"
              >
                {t('settings.users.reset2fa')}
              </button>
            ) : null}
          </div>
        </FormRow>
      ) : null}
      <FormRow label={t('settings.users.status')} help={t('settings.users.statusHelp')}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Switch
            checked={form.active}
            onChange={(active) => setForm((prev) => ({ ...prev, active }))}
            label={t('settings.users.active')}
          />
          <button
            type="button"
            onClick={() => setLoggingOut(true)}
            className="type-label rounded-xs text-brand-primary-700 hover:underline"
          >
            {t('settings.users.logoutAll')}
          </button>
        </div>
      </FormRow>

      <h2 className="type-heading mt-2 text-text-primary">{t('settings.users.accessTitle')}</h2>
      <div className="relative max-w-[700px] overflow-x-auto rounded-md border border-border-default">
        <table className="w-full min-w-[420px] border-collapse" data-testid="mailbox-access">
          <thead className="bg-bg-subtle">
            <tr className="type-label text-left text-text-secondary">
              <th className="px-3 py-2 font-semibold">{t('settings.users.accessMailbox')}</th>
              <th className="w-28 px-3 py-2 text-center font-normal">{t('settings.users.accessRead')}</th>
              <th className="w-36 px-3 py-2 text-center font-normal">{t('settings.users.accessSend')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.mailbox_id} className="type-body border-t border-border-default text-text-primary">
                <td className="px-3 py-2.5">
                  {r.email}
                  {r.own ? (
                    <span className="type-caption ml-2 text-text-secondary">{t('settings.users.accessOwn')}</span>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand-primary-600"
                    aria-label={t('settings.users.accessReadOf', { email: r.email })}
                    checked={r.read}
                    disabled={r.own}
                    onChange={(e) => setAccess(r, { read: e.target.checked })}
                  />
                </td>
                <td className="px-3 py-2.5 text-center">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand-primary-600"
                    aria-label={t('settings.users.accessSendOf', { email: r.email })}
                    checked={r.send}
                    disabled={r.own}
                    onChange={(e) => setAccess(r, { send: e.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="type-heading mt-2 text-text-primary">{t('settings.users.matrixTitle')}</h2>
      <div className="relative overflow-x-auto rounded-md border border-border-default">
        <table className="w-full min-w-[640px] border-collapse" data-testid="permission-matrix">
          <thead className="bg-bg-subtle">
            <tr className="type-label text-left text-text-secondary">
              <th className="px-3 py-2 font-semibold">{t('settings.users.matrix.permission')}</th>
              {MATRIX_ROLES.map((r) => (
                <th key={r} className="px-3 py-2 text-center font-normal">
                  {t(`settings.roles.${r}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MATRIX.map((row) => (
              <tr key={row.key} className="type-body border-t border-border-default text-text-primary">
                <td className="px-3 py-2">{t(`settings.users.matrix.${row.key}`)}</td>
                {MATRIX_ROLES.map((r) => (
                  <td key={r} className="px-3 py-2 text-center">
                    {row.roles.includes(r) ? (
                      <Check
                        size={16}
                        className="inline text-success-600"
                        aria-label={t('settings.users.matrix.yes')}
                      />
                    ) : (
                      <span className="text-text-tertiary" aria-label={t('settings.users.matrix.no')}>
                        —
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sticky bottom-0 -mx-4 mt-auto flex items-center gap-2 border-t border-border-default bg-bg-canvas px-4 py-4 sm:-mx-8 sm:px-8">
        <Button type="button" onClick={submit} disabled={save.isPending}>
          <Check size={16} aria-hidden="true" />
          {t('settings.save')}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={save.isPending}
          onClick={() => {
            setForm(initial());
            setAccessEdits({});
          }}
        >
          {t('common.cancel')}
        </Button>
        {dirty ? (
          <span className="type-small ml-2 inline-flex items-center gap-1.5 text-warning-700">
            <span aria-hidden="true" className="size-2 rounded-full bg-warning-600" />
            {t('settings.users.unsaved')}
          </span>
        ) : null}
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
      {loggingOut ? (
        <ConfirmDialog
          title={t('settings.users.logoutAllTitle', { email: user.email })}
          body={t('settings.users.logoutAllBody')}
          confirmLabel={t('settings.users.logoutAll')}
          busy={logoutAll.isPending}
          onConfirm={() => logoutAll.mutate()}
          onClose={() => setLoggingOut(false)}
        />
      ) : null}
      {resetting2fa ? (
        <ConfirmDialog
          title={t('settings.users.reset2faTitle', { email: user.email })}
          body={t('settings.users.reset2faBody')}
          confirmLabel={t('settings.users.reset2fa')}
          busy={reset2fa.isPending}
          onConfirm={() => reset2fa.mutate()}
          onClose={() => setResetting2fa(false)}
        />
      ) : null}
      {verifying ? (
        <VerifyDialog
          user={user}
          onClose={() => setVerifying(false)}
          onResult={(error) => {
            setVerifying(false);
            setVerifyError(error);
            if (!error) toasts.success(t('settings.users.verifyOk'));
          }}
        />
      ) : null}
    </div>
  );
}

/** „Overiť“: the admin types the mailbox password once; it is sent for one test login and never stored. */
function VerifyDialog({
  user,
  onClose,
  onResult,
}: {
  user: AdminUser;
  onClose: () => void;
  onResult: (error: string | null) => void;
}) {
  const { t } = useTranslation();
  const [password, setPassword] = useState('');
  const verify = useMutation({
    mutationFn: () => verifyUserLogin(user.id, password),
    onSuccess: () => onResult(null),
    onError: (error) =>
      onResult(
        t('settings.users.verifyFailed', {
          reason:
            error instanceof ApiError && error.detail.code === 'verify_failed'
              ? t('settings.users.verifyRejected')
              : adminErrorText(t, error),
        }),
      ),
  });
  return (
    <Dialog
      title={t('settings.users.verifyTitle', { email: user.email })}
      width={440}
      onClose={onClose}
      onSubmit={() => password && verify.mutate()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={verify.isPending || !password}>
            {t('settings.users.verify')}
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1">
        <span className="type-small text-text-primary">{t('settings.users.verifyPassword')}</span>
        <input
          className={INPUT}
          type="password"
          autoComplete="off"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          data-autofocus
        />
        <span className="type-caption text-text-secondary">{t('settings.users.verifyHelp')}</span>
      </label>
    </Dialog>
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
