import { avatarTone } from '../lib/avatarTone';

type Size = 20 | 32 | 56;

const SIZE: Record<Size, string> = {
  20: 'size-5 text-[11px] font-semibold leading-none',
  32: 'size-8 text-[13px] font-semibold leading-[18px]',
  56: 'size-14 type-heading',
};

/** Figma `Avatar`: initials on a colour derived from `seed` (the person id). */
export function Avatar({ initials, seed, size }: { initials: string; seed: string; size: Size }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full text-text-on-primary ${SIZE[size]} ${avatarTone(seed)}`}
    >
      {initials}
    </span>
  );
}
