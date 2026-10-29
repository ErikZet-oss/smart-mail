import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Link2, Pencil, Plus, Trash2, UserPlus, X } from 'lucide-react';
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
  fetchBranchFolders,
  linkBranchLogin,
  removeBranchLogo,
  removePersonPhoto,
  ROLES,
  saveBranch,
  savePersonAdmin,
  fetchPersonalPeople,
  uploadBranchLogo,
  uploadPersonPhoto,
  type AdminPerson,
  type BranchLogin,
  type PersonalPerson,
  type RoleId,
} from './settingsApi';
import { svgFileToPng } from './signatureHtml';
import { FormRow } from './UsersPanel';

type Branch = Record<string, unknown>;
const BRANCHES = ['settings', 'branches'];

const peopleOf = (branch: Branch) => (branch.people as AdminPerson[] | undefined) ?? [];

/** Middle column of W12-11: branches (Názov, schránka, osoby, vedúci) + „Pridať pobočku“. As `column` it is the
 * full-height list of the Figma frames with the button at the bottom. */
export function BranchList({
  branches,
  currentId,
  onSelect,
  column = false,
}: {
  branches: Branch[];
  currentId: string;
  onSelect: (id: string) => void;
  column?: boolean;
}) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  return (
    <div
      className={
        column
          ? 'flex w-[var(--layout-settings-list)] shrink-0 flex-col border-r border-border-default bg-bg-canvas'
          : 'flex w-full flex-col gap-2'
      }
      data-testid="branch-list"
    >
      <ul
        className={`flex flex-col ${column ? 'min-h-0 flex-1 overflow-y-auto' : 'border-y border-border-default'}`}
        aria-label={t('settings.branches.pick')}
      >
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
            <li key={String(b.id)} className="border-b border-border-default">
              <button
                type="button"
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(String(b.id))}
                className={`w-full px-3.5 py-2.5 text-left ${selected ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'}`}
              >
                <span
                  className={`type-small block truncate ${selected ? 'font-semibold text-brand-primary-700' : 'text-text-primary'}`}
                >
                  {String(b.name)}
                </span>
                <span className="type-caption block truncate text-text-secondary">{meta}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className={column ? 'shrink-0 p-3' : ''}>
        <Button type="button" variant="secondary" className="w-full" onClick={() => setAdding(true)}>
          <Plus size={16} aria-hidden="true" />
          {t('settings.branches.add')}
        </Button>
      </div>
      {adding ? <AddBranchDialog onClose={() => setAdding(false)} onCreated={onSelect} /> : null}
    </div>
  );
}

/** Chips with × plus „+ pridať“ (Figma „Priečinky pobočky“, „Pôsobí aj na pobočkách“). */
function ChipPicker({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: string; label: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const [picking, setPicking] = useState(false);
  const free = options.filter((o) => !value.includes(o.id));
  const name = (id: string) => options.find((o) => o.id === id)?.label ?? id;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {value.map((id) => (
        <span
          key={id}
          className="type-small inline-flex h-6 items-center gap-1 rounded-full bg-brand-primary-600 pl-2.5 pr-1.5 text-text-on-primary"
        >
          {name(id)}
          <button
            type="button"
            aria-label={t('settings.branches.chipRemove', { name: name(id) })}
            onClick={() => onChange(value.filter((v) => v !== id))}
            className="rounded-full hover:bg-brand-primary-700"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </span>
      ))}
      {picking ? (
        <select
          className={`${INPUT} h-8 w-auto`}
          aria-label={label}
          value=""
          autoFocus
          onBlur={() => setPicking(false)}
          onChange={(e) => {
            if (e.target.value) onChange([...value, e.target.value]);
            setPicking(false);
          }}
        >
          <option value="">{t('settings.branches.chipPick')}</option>
          {free.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      ) : free.length ? (
        <button
          type="button"
          onClick={() => setPicking(true)}
          className="type-small text-brand-primary-700 hover:underline"
        >
          {t('settings.branches.chipAdd')}
        </button>
      ) : null}
    </div>
  );
}

/** Uložiť / Zrušiť bar at the bottom of the tab (Figma W12-11a, W12-11d). */
function SaveBar({
  onSave,
  onCancel,
  busy,
  disabled,
}: {
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="sticky bottom-0 -mx-4 mt-auto flex gap-2 border-t border-border-default bg-bg-canvas px-4 py-4 sm:-mx-8 sm:px-8">
      <Button type="button" onClick={onSave} disabled={busy || disabled}>
        <Check size={16} aria-hidden="true" />
        {t('settings.save')}
      </Button>
      <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
        {t('common.cancel')}
      </Button>
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

const branchForm = (branch: Branch) => ({
  name: String(branch.name ?? ''),
  mailbox_id: String(branch.mailbox_id ?? ''),
  address: String(branch.address ?? ''),
  phone: String(branch.phone ?? ''),
  hours: String(branch.hours ?? ''),
  folder_ids: ((branch.folder_ids as string[] | undefined) ?? []).map(String),
});

/** W12-11a Údaje (Figma `68:60641`): name, branch mailbox, the login of the mailbox („Prepojiť…“, #33), address,
 * phone, hours, „Logo do podpisu“ and „Priečinky pobočky“ (D21), with the Uložiť / Zrušiť bar. */
export function BranchDetails({ branch }: { branch: Branch }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const mailboxes = useQuery({ queryKey: ['settings', 'mailboxes'], queryFn: fetchAdminMailboxes });
  const folders = useQuery({ queryKey: [...BRANCHES, 'folders'], queryFn: fetchBranchFolders });
  const [form, setForm] = useState(() => branchForm(branch));
  const set = (key: 'name' | 'mailbox_id' | 'address' | 'phone' | 'hours') => (value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));
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
  const folderOptions = (folders.data ?? []).map((f) => ({
    id: f.id,
    label: `${f.mailbox_email.split('@')[0]}@ › ${f.name}`,
  }));

  return (
    <div className="flex flex-1 flex-col gap-4" data-testid="branch-details">
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
          maxLength={200}
          className={`${INPUT} h-auto py-2`}
          value={form.address}
          onChange={(e) => set('address')(e.target.value)}
        />
      </FormRow>
      <FormRow label={t('settings.branches.phone')} htmlFor="branch-phone">
        <input
          id="branch-phone"
          type="tel"
          className={INPUT}
          value={form.phone}
          onChange={(e) => set('phone')(e.target.value)}
        />
      </FormRow>
      <FormRow label={t('settings.branches.hours')} htmlFor="branch-hours">
        <input
          id="branch-hours"
          maxLength={120}
          className={INPUT}
          value={form.hours}
          onChange={(e) => set('hours')(e.target.value)}
        />
      </FormRow>
      <FormRow label={t('settings.branches.logo')} help={t('settings.branches.logoHelp')}>
        <BranchLogo branch={branch} />
      </FormRow>
      <FormRow label={t('settings.branches.folders')} help={t('settings.branches.foldersHelp')}>
        <ChipPicker
          label={t('settings.branches.folders')}
          options={folderOptions}
          value={form.folder_ids}
          onChange={(folder_ids) => setForm((prev) => ({ ...prev, folder_ids }))}
        />
      </FormRow>
      <SaveBar
        onSave={() => save.mutate()}
        onCancel={() => setForm(branchForm(branch))}
        busy={save.isPending}
        disabled={!form.name.trim()}
      />
    </div>
  );
}

/** „Logo do podpisu“: preview + Zmeniť / Odstrániť. SVG is converted to PNG here, like signature images. */
function BranchLogo({ branch }: { branch: Branch }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const url = (branch.logo_url as string | null | undefined) ?? null;
  const done = () => void qc.invalidateQueries({ queryKey: BRANCHES });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const svg = file.type === 'image/svg+xml' || file.name.toLowerCase().endsWith('.svg');
      return uploadBranchLogo(String(branch.id), svg ? await svgFileToPng(file) : file);
    },
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      done();
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const remove = useMutation({ mutationFn: () => removeBranchLogo(String(branch.id)), onSuccess: done });
  return (
    <div className="flex items-center gap-2" data-testid="branch-logo">
      <span className="flex h-10 w-[120px] items-center justify-center rounded-sm border border-border-default bg-bg-canvas p-1">
        <img
          src={url ?? '/logo-smart.svg'}
          alt={t('settings.branches.logo')}
          className="max-h-full max-w-full object-contain"
        />
      </span>
      <Button type="button" variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
        {url ? t('settings.branches.logoChange') : t('settings.branches.logoUpload')}
      </Button>
      {url ? (
        <Button type="button" variant="secondary" onClick={() => remove.mutate()} disabled={remove.isPending}>
          {t('settings.branches.logoRemove')}
        </Button>
      ) : null}
      <input
        ref={input}
        type="file"
        hidden
        accept="image/png,image/svg+xml,.svg"
        data-testid="branch-logo-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file) upload.mutate(file);
        }}
      />
    </div>
  );
}

/** W12-11d Prihlasovanie (Figma `72:62234`): „Kto ste?“ after inactivity and „Zostať prihlásený“ for the branch.
 * „Prehľad pobočky – upozorniť na nevybavené“ comes with the branch overview (Phase 5). */
export function BranchLoginSettings({ branch }: { branch: Branch }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const initial = () => ({
    idle: String(branch.idle_ask_minutes ?? 0),
    remember: String(branch.remember_days ?? 30),
  });
  const [form, setForm] = useState(initial);
  const save = useMutation({
    mutationFn: () =>
      saveBranch(String(branch.id), {
        name: branch.name,
        address: branch.address ?? null,
        phone: branch.phone ?? null,
        hours: branch.hours ?? null,
        mailbox_id: branch.mailbox_id ?? null,
        idle_ask_minutes: Number(form.idle),
        remember_days: Number(form.remember),
      }),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: BRANCHES });
    },
  });
  return (
    <div className="flex flex-1 flex-col gap-4" data-testid="branch-login-settings">
      {save.isError ? <Banner kind="danger" message={adminErrorText(t, save.error)} /> : null}
      <FormRow label={t('settings.branches.idleAsk')} htmlFor="branch-idle">
        <select
          id="branch-idle"
          className={`${INPUT} max-w-[200px]`}
          value={form.idle}
          onChange={(e) => setForm((prev) => ({ ...prev, idle: e.target.value }))}
        >
          {['0', '30', '60', '120'].map((v) => (
            <option key={v} value={v}>
              {v === '0' ? t('settings.branches.idleNever') : t('settings.branches.minutes', { count: Number(v) })}
            </option>
          ))}
        </select>
      </FormRow>
      <FormRow label={t('settings.branches.remember')} htmlFor="branch-remember">
        <select
          id="branch-remember"
          className={`${INPUT} max-w-[200px]`}
          value={form.remember}
          onChange={(e) => setForm((prev) => ({ ...prev, remember: e.target.value }))}
        >
          {['1', '7', '30'].map((v) => (
            <option key={v} value={v}>
              {t('settings.branches.days', { count: Number(v) })}
            </option>
          ))}
        </select>
      </FormRow>
      <SaveBar onSave={() => save.mutate()} onCancel={() => setForm(initial())} busy={save.isPending} />
    </div>
  );
}

function PersonAvatar({ person, size = 32 }: { person: AdminPerson; size?: 32 | 56 }) {
  if (person.photo_url) {
    return (
      <img
        src={person.photo_url}
        alt=""
        className={`${size === 32 ? 'size-8' : 'size-14'} shrink-0 rounded-full object-cover`}
      />
    );
  }
  return <Avatar initials={`${person.first_name[0] ?? ''}${person.last_name[0] ?? ''}`} seed={person.id} size={size} />;
}

const personBody = (p: AdminPerson, changes: Record<string, unknown> = {}) => ({
  first_name: p.first_name,
  last_name: p.last_name,
  function: p.function,
  phone: p.phone,
  mobile: p.mobile,
  role: p.role,
  is_manager: p.is_manager,
  active: p.active,
  personal_email: p.personal_email,
  ...changes,
});

/** W12-11b Osoby (Figma `68:61587`): the whole row opens the drawer (click, Enter) and so does the „Upraviť“ pencil
 * (pilot finding on #55); „Aktívna“ is a switch in the row. */
export function BranchPeople({ branch, branches = [] }: { branch: Branch; branches?: Branch[] }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [open, setOpen] = useState<AdminPerson | 'new' | null>(null);
  const people = peopleOf(branch);
  const toggle = useMutation({
    mutationFn: (p: AdminPerson) => savePersonAdmin(p.id, personBody(p, { active: !p.active })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BRANCHES }),
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="branch-people">
      <div className="flex items-center gap-4">
        <p className="type-small flex-1 text-text-secondary">{t('settings.branches.peopleHint')}</p>
        <Button type="button" onClick={() => setOpen('new')}>
          <UserPlus size={16} aria-hidden="true" />
          {t('settings.branches.addPerson')}
        </Button>
      </div>
      <div className="relative overflow-x-auto rounded-md border border-border-default">
        <table className="w-full min-w-[680px] border-collapse">
          <thead className="bg-bg-subtle">
            <tr className="type-label text-left text-text-secondary">
              <th className="w-14 px-3 py-2" aria-hidden="true" />
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.name')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.function')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.mobile')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.role')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.manager')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.active')}</th>
              <th className="w-12 px-2 py-2" aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {people.map((p) => {
              const name = `${p.first_name} ${p.last_name}`;
              return (
                <tr
                  key={p.id}
                  tabIndex={0}
                  onClick={() => setOpen(p)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target === e.currentTarget) setOpen(p);
                  }}
                  className="type-body cursor-pointer border-t border-border-default text-text-primary hover:bg-bg-subtle focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500"
                  data-testid="person-row"
                >
                  <td className="px-3 py-2">
                    <PersonAvatar person={p} />
                  </td>
                  <td className="px-3 py-2">{name}</td>
                  <td className="px-3 py-2">{p.function ?? ''}</td>
                  <td className="px-3 py-2">{p.mobile ?? ''}</td>
                  <td className="px-3 py-2">{t(`settings.roles.${p.role}`)}</td>
                  <td className="px-3 py-2">
                    {p.is_manager ? (
                      <Check
                        size={16}
                        className="text-success-600"
                        aria-label={t('settings.branches.columns.manager')}
                      />
                    ) : null}
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    <Switch
                      checked={p.active}
                      disabled={toggle.isPending}
                      onChange={() => toggle.mutate(p)}
                      label={<span className="sr-only">{t('settings.branches.person.activeOf', { name })}</span>}
                    />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      aria-label={t('settings.branches.person.edit', { name })}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpen(p);
                      }}
                      onKeyDown={(e) => e.stopPropagation()}
                      className="inline-flex size-8 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-muted hover:text-text-primary"
                    >
                      <Pencil size={16} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {open ? (
        <PersonDrawer
          branchId={String(branch.id)}
          branches={branches}
          person={open === 'new' ? null : open}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </div>
  );
}

/** W12-11b „Osobné účty“ (#71): persons of personal logins (eshop@) — same drawer, plus the branch for the signature.
 * They never appear in „Kto ste?“ of that branch. */
export function PersonalAccountPeople({ branches }: { branches: Branch[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<PersonalPerson | null>(null);
  const people = useQuery({ queryKey: [...BRANCHES, 'personal'], queryFn: fetchPersonalPeople });
  const branchName = (id: string | null) => branches.find((b) => String(b.id) === id)?.name;
  if (!people.data?.length) return null;
  return (
    <section
      className="flex min-w-0 flex-col gap-3"
      data-testid="personal-people"
      aria-labelledby="personal-people-title"
    >
      <h3 id="personal-people-title" className="type-heading text-text-primary">
        {t('settings.branches.personal.title')}
      </h3>
      <p className="type-small text-text-secondary">{t('settings.branches.personal.hint')}</p>
      <div className="relative overflow-x-auto rounded-md border border-border-default">
        <table className="w-full min-w-[640px] border-collapse">
          <thead className="bg-bg-subtle">
            <tr className="type-label text-left text-text-secondary">
              <th className="px-3 py-2 font-semibold">{t('settings.branches.personal.login')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.name')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.function')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.personal.branch')}</th>
              <th className="px-3 py-2 font-semibold">{t('settings.branches.columns.active')}</th>
            </tr>
          </thead>
          <tbody>
            {people.data.map((p) => (
              <tr key={p.id} className="type-body border-t border-border-default text-text-primary">
                <td className="px-3 py-2">{p.login_email}</td>
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
                <td className="px-3 py-2">
                  {p.branch_id ? String(branchName(p.branch_id) ?? '') : t('settings.branches.personal.noBranch')}
                </td>
                <td className="px-3 py-2">{p.active ? t('settings.users.active') : t('settings.users.inactive')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open ? <PersonDrawer branchId="" person={open} personal={{ branches }} onClose={() => setOpen(null)} /> : null}
    </section>
  );
}

function PersonDrawer({
  branchId,
  branches = [],
  person,
  personal,
  onClose,
}: {
  branchId: string;
  branches?: Branch[];
  person: AdminPerson | PersonalPerson | null;
  /** Person of a personal login (#71): branch select for the signature, no manager flag and no delete. */
  personal?: { branches: Branch[] };
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
  const [covers, setCovers] = useState<string[]>(person?.cover_branch_ids ?? []);
  const [signatureBranch, setSignatureBranch] = useState(
    person && 'branch_id' in person ? (person.branch_id ?? '') : '',
  );
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
        ...(personal ? { branch_id: signatureBranch || null } : { cover_branch_ids: covers }),
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
          {person ? <PersonPhoto person={person} /> : null}
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
          {personal ? (
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.personal.branch')}</span>
              <select className={INPUT} value={signatureBranch} onChange={(e) => setSignatureBranch(e.target.value)}>
                <option value="">{t('settings.branches.personal.noBranch')}</option>
                {personal.branches.map((b) => (
                  <option key={String(b.id)} value={String(b.id)}>
                    {String(b.name)}
                  </option>
                ))}
              </select>
              <span className="type-caption text-text-secondary">{t('settings.branches.personal.branchHelp')}</span>
            </label>
          ) : (
            <div className="flex flex-col gap-0.5">
              <Switch
                checked={form.is_manager}
                onChange={(v) => setForm((prev) => ({ ...prev, is_manager: v }))}
                label={t('settings.branches.person.manager')}
              />
              <p className="type-caption pl-[42px] text-text-secondary">{t('settings.branches.person.managerHelp')}</p>
            </div>
          )}
          {personal ? null : (
            <div className="flex flex-col gap-1">
              <span className="type-label text-text-primary">{t('settings.branches.person.covers')}</span>
              <ChipPicker
                label={t('settings.branches.person.covers')}
                options={branches
                  .filter((b) => String(b.id) !== branchId)
                  .map((b) => ({ id: String(b.id), label: String(b.name) }))}
                value={covers}
                onChange={setCovers}
              />
              <span className="type-caption text-text-secondary">{t('settings.branches.person.coversHelp')}</span>
            </div>
          )}
          <Switch
            checked={form.active}
            onChange={(v) => setForm((prev) => ({ ...prev, active: v }))}
            label={t('settings.branches.person.active')}
          />
        </div>
        <footer className="flex shrink-0 items-center gap-2 border-t border-border-default p-5">
          {person && !personal ? (
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

/** „Fotka“ (SETTINGS 11b): avatar + „Nahrať fotku“ / „Odstrániť fotku“; JPG/PNG, max 5 MB, cropped on the server. */
function PersonPhoto({ person }: { person: AdminPerson }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState(person.photo_url ?? null);
  const upload = useMutation({
    mutationFn: (file: File) => uploadPersonPhoto(person.id, file),
    onSuccess: (saved) => {
      setUrl(saved.photo_url);
      void qc.invalidateQueries({ queryKey: BRANCHES });
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const remove = useMutation({
    mutationFn: () => removePersonPhoto(person.id),
    onSuccess: () => {
      setUrl(null);
      void qc.invalidateQueries({ queryKey: BRANCHES });
    },
  });
  return (
    <div className="flex items-center gap-3" data-testid="person-photo">
      <PersonAvatar person={{ ...person, photo_url: url }} size={56} />
      <Button type="button" variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
        {t('settings.branches.person.photoUpload')}
      </Button>
      {url ? (
        <Button type="button" variant="secondary" onClick={() => remove.mutate()} disabled={remove.isPending}>
          {t('settings.branches.person.photoRemove')}
        </Button>
      ) : null}
      <input
        ref={input}
        type="file"
        hidden
        accept="image/png,image/jpeg"
        data-testid="person-photo-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (!file) return;
          if (file.size > 5 * 1024 * 1024) {
            toasts.error(t('settings.users.errors.image_too_large'));
            return;
          }
          upload.mutate(file);
        }}
      />
    </div>
  );
}
