import { avatarTone } from '../lib/avatarTone';

type Size = 20 | 32 | 56;

const SIZE: Record<Size, string> = {
  20: 'size-5 text-[11px] font-semibold leading-none',
  32: 'size-8 text-[13px] font-semibold leading-[18px]',
  56: 'size-14 type-heading',
};

const PHOTO: Record<Size, string> = { 20: 'size-5', 32: 'size-8', 56: 'size-14' };

/** Figma `Avatar`: the person's photo when there is one, else initials on a colour derived from `seed` (the person id). */
export function Avatar({
  initials,
  seed,
  size,
  photoUrl,
}: {
  initials: string;
  seed: string;
  size: Size;
  photoUrl?: string | null;
}) {
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt=""
        aria-hidden="true"
        className={`shrink-0 rounded-full object-cover ${PHOTO[size]}`}
        data-testid="avatar-photo"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full text-text-on-primary ${SIZE[size]} ${avatarTone(seed)}`}
    >
      {initials}
    </span>
  );
}
