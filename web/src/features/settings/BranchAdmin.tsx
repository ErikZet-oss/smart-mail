import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Link2, Plus, Trash2, UserPlus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Avatar } from '../../components/Avatar';
import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import { adminErrorText, INPUT } from './adminUi';
import {
  addPersonAdmin,
  createBranch,
  deletePersonAdmin,
  fetchAdminMailboxes,
  linkBranchLogin,
  ROLES,
  saveBranch,
  savePersonAdmin,
  type AdminPerson,
  type BranchLogin,
  type RoleId,
} from './settingsApi';
import { FormRow } from './UsersPanel';

type Branch = Record<string, unknown>;
const BRANCHES = ['settings', 'branches'];

const peopleOf = (branch: Branch) => (branch.people as AdminPerson[] | undefined) ?? [];

/** Middle column of W12-11: branches (Názov, schránka, osoby, vedúci) + „Pridať pobočku“. */
export function BranchList({
  branches,
  currentId,
  onSelect,
}: {
  branches: Branch[];
  currentId: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  return (
    <div className="flex w-full shrink-0 flex-col gap-2 lg:w-72">
      <ul className="flex flex-col border-y border-border-default" aria-label={t('settings.branches.pick')}>
        {branches.map((b) => {
          const people = peopleOf(b);
          const manager = people.find((p) => p.is_manager && p.active);
          const mailbox = String(b.mailbox_email ?? '').split('@')[0];
          const meta = [
            mailbox ? `${mailbox}@` : null,
            t('settings.users.persons', { count: people.filter((p) => p.active).length }),
            manager ? `${manager.first_name} ${manager.last_name}` : null,
          ]
            .filter(Boolean)
            .join(' · ');
          const selected = String(b.id) === currentId;
          return (
            <li key={String(b.id)} className="border-b border-border-default last:border-b-0">
              <button
                type="button"
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(String(b.id))}
                className={`w-full px-3 py-2.5 text-left ${selected ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'}`}
              >
                <span
                  className={`type-body block truncate ${selected ? 'text-brand-primary-700' : 'text-text-primary'}`}
                >
                  {String(b.name)}
                </span>
                <span className="type-small block truncate text-text-secondary">{meta}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <Button type="button" variant="secondary" onClick={() => setAdding(true)}>
        <Plus size={16} aria-hidden="true" />
        {t('settings.branches.add')}
      </Button>
      {adding ? <AddBranchDialog onClose={() => setAdding(false)} onCreated={onSelect} /> : null}
    </div>
  );
}

function AddBranchDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const create = useMutation({
    mutationFn: () => createBranch({ name }) as Promise<{ id: string }>,
    onSuccess: (branch) => {
      void qc.invalidateQueries({ queryKey: BRANCHES });
      onCreated(branch.id);
      onClose();
    },
  });
  return (
    <Dialog
      title={t('settings.branches.addTitle')}
      width={440}
      onClose={onClose}
      onSubmit={() => name.trim() && create.mutate()}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            {t('settings.branches.add')}
          </Button>
        </>
      }
    >
      {create.isError ? <Banner kind="danger" message={adminErrorText(t, create.error)} /> : null}
      <label className="flex flex-col gap-1">
        <span className="type-small text-text-primary">{t('settings.branches.name')}</span>
        <input
          className={INPUT}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('settings.branches.nameHelp')}
          data-autofocus
        />
      </label>
    </Dialog>
  );
}

/** W12-11a Údaje: name, branch mailbox, address, phone, hours + the login of the mailbox („Prepojiť…“, #33). */
export function BranchDetails({ branch }: { branch: Branch }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const mailboxes = useQuery({ queryKey: ['settings', 'mailboxes'], queryFn: fetchAdminMailboxes });
  const [form, setForm] = useState({
    name: String(branch.name ?? ''),
    mailbox_id: String(branch.mailbox_id ?? ''),
    address: String(branch.address ?? ''),
    phone: String(branch.phone ?? ''),
    hours: String(branch.hours ?? ''),
  });
  const set = (key: keyof typeof form) => (value: string) => setForm((prev) => ({ ...prev, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      saveBranch(String(branch.id), {
        ...form,
        mailbox_id: form.mailbox_id || null,
        address: form.address || null,
        phone: form.phone || null,
        hours: form.hours || null,
      }),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: BRANCHES });
    },
  });
  const link = useMutation({
    mutationFn: () => linkBranchLogin(String(branch.id)),
    onSuccess: () => {
      toasts.success(t('settings.branches.linked'));
      void qc.invalidateQueries({ queryKey: BRANCHES });
      void qc.invalidateQueries({ queryKey: ['settings', 'users'] });
    },
  });
  const login = (branch.login_account as BranchLogin | null | undefined) ?? null;
  const savedMailbox = String(branch.mailbox_id ?? '');
  const loginText = !login
    ? t('settings.branches.loginNone')
    : login.linked
      ? t('settings.branches.loginLinked', { email: login.email })
      : login.kind === 'branch'
        ? t('settings.branches.loginOther', { email: login.email })
        : t('settings.branches.loginPersonal', { email: login.email });

  return (
    <div className="flex max-w-3xl flex-col gap-4" data-testid="branch-details">
      {save.isError ? <Banner kind="danger" message={adminErrorText(t, save.error)} /> : null}
      <FormRow label={t('settings.branches.name')} help={t('settings.branches.nameHelp')} htmlFor="branch-name">
        <input id="branch-name" className={INPUT} value={form.name} onChange={(e) => set('name')(e.target.value)} />
      </FormRow>
      <FormRow label={t('settings.branches.mailbox')} htmlFor="branch-mailbox">
        <select
          id="branch-mailbox"
          className={INPUT}
          value={form.mailbox_id}
          onChange={(e) => set('mailbox_id')(e.target.value)}
        >
          <option value="">{t('settings.branches.mailboxNone')}</option>
          {(mailboxes.data ?? []).map((m) => (
            <option key={String(m.id)} value={String(m.id)}>
              {String(m.email)}
            </option>
          ))}
        </select>
      </FormRow>
      {savedMailbox ? (
        <FormRow label={t('settings.branches.login')}>
          <div className="flex flex-col items-start gap-2" data-testid="branch-login">
            <p className={`type-small ${login?.linked ? 'text-text-secondary' : 'text-warning-700'}`}>{loginText}</p>
            {login?.linked ? null : (
              <Button type="button" variant="secondary" onClick={() => link.mutate()} disabled={link.isPending}>
                <Link2 size={16} aria-hidden="true" />
                {t('settings.branches.link')}
              </Button>
            )}
            {link.isError ? <Banner kind="danger" message={adminErrorText(t, link.error)} /> : null}
          </div>
        </FormRow>
      ) : null}
      <FormRow label={t('settings.branches.address')} htmlFor="branch-address">
        <textarea
          id="branch-address"
          rows={3}
          className={`${INPUT} h-auto py-2`}
          value={form.address}
          onChange={(e) => set('address')(e.target.value)}
        />
      </FormRow>
      <FormRow label={t('settings.branches.phone')} htmlFor="branch-phone">
        <input id="branch-phone" className={INPUT} value={form.phone} onChange={(e) => set('phone')(e.target.value)} />
      </FormRow>
      <FormRow label={t('settings.branches.hours')} htmlFor="branch-hours">
        <input id="branch-hours" className={INPUT} value={form.hours} onChange={(e) => set('hours')(e.target.value)} />
      </FormRow>
      <div className="flex gap-2 border-t border-border-default pt-4">
        <Button type="button" onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>
          <Check size={16} aria-hidden="true" />
          {t('settings.save')}
        </Button>
      </div>
    </div>
  );
}

/** W12-11b Osoby: table + drawer to add / edit / remove a person (PRODUCT_SPEC §2.0, D10). */
export function BranchPeople({ branch }: { branch: Branch }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<AdminPerson | 'new' | null>(null);
  const people = peopleOf(branch);
  return (
    <div className="flex flex-col gap-4" data-testid="branch-people">
      <div className="flex items-center gap-4">
        <p className="type-small flex-1 text-text-secondary">{t('settings.branches.peopleHint')}</p>
        <Button type="button" onClick={() => setOpen('new')}>
          <UserPlus size={16} aria-hidden="true" />
          {t('settings.branches.addPerson')}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-md border border-border-default">
        <table className="w-full min-w-[640px] border-collapse">
          <thead className="bg-bg-subtle">
            <tr className="type-label text-left text-text-secondary">
              <th className="w-14 px-3 py-2" aria-hidden="true" />
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.name')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.function')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.mobile')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.role')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.manager')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.active')}</th>
            </tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.id} className="type-body border-t border-border-default text-text-primary">
                <td className="px-3 py-2">
                  <Avatar initials={`${p.first_name[0] ?? ''}${p.last_name[0] ?? ''}`} seed={p.id} size={32} />
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    className="text-left hover:text-brand-primary-700 hover:underline"
                    onClick={() => setOpen(p)}
                  >
                    {p.first_name} {p.last_name}
                  </button>
                </td>
                <td className="px-3 py-2">{p.function ?? ''}</td>
                <td className="px-3 py-2">{p.mobile ?? ''}</td>
                <td className="px-3 py-2">{t(`settings.roles.${p.role}`)}</td>
                <td className="px-3 py-2">
                  {p.is_manager ? <Check size={16} className="text-success-600" aria-label="✓" /> : null}
                </td>
                <td className="px-3 py-2">{p.active ? t('settings.users.active') : t('settings.users.inactive')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open ? (
        <PersonDrawer
          branchId={String(branch.id)}
          person={open === 'new' ? null : open}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </div>
  );
}

function PersonDrawer({
  branchId,
  person,
  onClose,
}: {
  branchId: string;
  person: AdminPerson | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const box = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState({
    first_name: person?.first_name ?? '',
    last_name: person?.last_name ?? '',
    function: person?.function ?? '',
    phone: person?.phone ?? '',
    mobile: person?.mobile ?? '',
    role: person?.role ?? ('sales' as RoleId),
    is_manager: person?.is_manager ?? false,
    active: person?.active ?? true,
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const text = (key: 'first_name' | 'last_name' | 'function' | 'phone' | 'mobile') => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => setForm((prev) => ({ ...prev, [key]: e.target.value })),
  });
  const done = () => {
    void qc.invalidateQueries({ queryKey: BRANCHES });
    onClose();
  };
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        function: form.function || null,
        phone: form.phone || null,
        mobile: form.mobile || null,
        personal_email: person?.personal_email ?? null,
      };
      return person ? savePersonAdmin(person.id, body) : addPersonAdmin(branchId, body);
    },
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      done();
    },
  });
  const remove = useMutation({
    mutationFn: () => deletePersonAdmin(person?.id ?? ''),
    onSuccess: (result) => {
      toasts.success(
        result.result === 'deleted' ? t('settings.branches.person.deleted') : t('settings.branches.person.deactivated'),
      );
      done();
    },
    onError: () => setConfirmDelete(false),
  });
  const error = save.error ?? remove.error;
  const name = `${person?.first_name ?? ''} ${person?.last_name ?? ''}`.trim();

  useEffect(() => {
    box.current?.querySelector<HTMLElement>('input')?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-bg-overlay"
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-label={name || t('settings.branches.person.new')}
        className="flex h-full w-full max-w-[520px] flex-col bg-bg-canvas shadow-e3"
        data-testid="person-drawer"
      >
        <header className="flex h-14 shrink-0 items-center border-b border-border-default px-5">
          <h2 className="type-heading min-w-0 flex-1 truncate text-text-primary">
            {name || t('settings.branches.person.new')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="rounded-xs text-text-secondary hover:text-text-primary"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
          {error ? <Banner kind="danger" message={adminErrorText(t, error)} /> : null}
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.person.firstName')}</span>
              <input className={INPUT} required {...text('first_name')} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.person.lastName')}</span>
              <input className={INPUT} required {...text('last_name')} />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-primary">{t('settings.branches.person.function')}</span>
            <input className={INPUT} maxLength={60} {...text('function')} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.person.phone')}</span>
              <input className={INPUT} type="tel" {...text('phone')} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.person.mobile')}</span>
              <input className={INPUT} type="tel" {...text('mobile')} />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-primary">{t('settings.branches.person.role')}</span>
            <select
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
          </label>
          <div className="flex flex-col gap-0.5">
            <Switch
              checked={form.is_manager}
              onChange={(v) => setForm((prev) => ({ ...prev, is_manager: v }))}
              label={t('settings.branches.person.manager')}
            />
            <p className="type-caption pl-[42px] text-text-secondary">{t('settings.branches.person.managerHelp')}</p>
          </div>
          <Switch
            checked={form.active}
            onChange={(v) => setForm((prev) => ({ ...prev, active: v }))}
            label={t('settings.branches.person.active')}
          />
        </div>
        <footer className="flex shrink-0 items-center gap-2 border-t border-border-default p-5">
          {person ? (
            <Button
              type="button"
              className="bg-danger-600 hover:bg-danger-600 hover:brightness-95"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 size={16} aria-hidden="true" />
              {t('settings.branches.person.delete')}
            </Button>
          ) : null}
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || !form.first_name.trim() || !form.last_name.trim()}
          >
            <Check size={16} aria-hidden="true" />
            {t('settings.save')}
          </Button>
        </footer>
      </div>
      {confirmDelete ? (
        <ConfirmDialog
          title={t('settings.branches.person.deleteTitle', { name })}
          body={t('settings.branches.person.deleteBody')}
          confirmLabel={t('settings.branches.person.delete')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirmDelete(false)}
        />
      ) : null}
    </div>
  );
}
