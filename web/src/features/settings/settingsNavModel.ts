import {
  Building2,
  Circle,
  CircleUserRound,
  Clock,
  Folder,
  ListFilter,
  Mails,
  MessageSquare,
  Settings,
  Shield,
  Sparkles,
  User,
  Users,
  type LucideIcon,
} from 'lucide-react';

import type { NavSection } from './settingsApi';

/** Lucide icon per settings section — same glyphs as the Figma `SettingsNav` (W12, node 62:51682). */
const SECTION_ICONS: Record<string, LucideIcon> = {
  preferences: ListFilter,
  folders: Folder,
  'identity/list': CircleUserRound,
  'identity/profile': User,
  identity: CircleUserRound,
  responses: MessageSquare,
  filters: ListFilter,
  vacation: Clock,
  provider: Settings,
  ai: Sparkles,
  security: Shield,
  users: Users,
  branches: Building2,
  mailboxes: Mails,
};

/** Figma order of the personal group (Identity and Môj profil are separate rows around Odpovede). */
const PERSONAL_ORDER = [
  'preferences',
  'folders',
  'identity/list',
  'identity',
  'responses',
  'identity/profile',
  'filters',
  'vacation',
  'provider',
  'ai',
  'security',
];

/** Sections listed under the „SPRÁVA 🔒“ group header (SETTINGS_SPEC 10–20; Phase 1 has 10–12). */
const ADMIN_SECTIONS = new Set(['users', 'branches', 'mailboxes']);

/** Sections whose subsections are shown as tabs inside the content area instead of the middle list (Figma W12-11). */
export const TABBED_SECTIONS = new Set(['branches']);

export type SettingsNavItem = {
  key: string;
  title: string;
  to: string;
  section: string;
  sub?: string;
  admin: boolean;
  icon: LucideIcon;
};

/** Flattens the backend nav into the Figma rows (identity split into Identity + Môj profil). */
export function buildNavItems(sections: NavSection[]): SettingsNavItem[] {
  const items: SettingsNavItem[] = [];
  for (const s of sections) {
    if (s.path === 'identity' && s.subs.length > 0) {
      for (const sub of s.subs) {
        const key = `identity/${sub.path}`;
        items.push({
          key,
          title: sub.title,
          to: `/settings/identity/${sub.path}`,
          section: 'identity',
          sub: sub.path,
          admin: false,
          icon: SECTION_ICONS[key] ?? CircleUserRound,
        });
      }
      continue;
    }
    items.push({
      key: s.path,
      title: s.title,
      to: `/settings/${s.path}${s.subs[0] ? `/${s.subs[0].path}` : ''}`,
      section: s.path,
      admin: ADMIN_SECTIONS.has(s.path),
      icon: SECTION_ICONS[s.path] ?? Circle,
    });
  }
  const rank = (key: string) => {
    const i = PERSONAL_ORDER.indexOf(key);
    return i === -1 ? PERSONAL_ORDER.length : i;
  };
  const personal = items.filter((i) => !i.admin).sort((a, b) => rank(a.key) - rank(b.key));
  return [...personal, ...items.filter((i) => i.admin)];
}

export function isItemActive(item: SettingsNavItem, section: string, sub?: string) {
  if (item.section !== section) return false;
  if (item.section !== 'identity' || !item.sub) return true;
  return item.sub === 'profile' ? sub === 'profile' : sub !== 'profile';
}
