// Figma `Avatar`: initials on a colour (Peter green, Jana brand, Marek orange in the frames). Persons have no stored
// colour, so the tone follows the person's position in the branch list, which is the same on W1b, M0 and W2b. Only
// tokens with white text ≥ 3:1 at 16 px semibold (design/CONTRAST.md).
const TONES = [
  'bg-success-600',
  'bg-brand-primary-600',
  'bg-cat-inquiry',
  'bg-cat-supplier_document',
  'bg-cat-supplier_info',
] as const;

type Size = 32 | 56;

const SIZE: Record<Size, string> = {
  32: 'size-8 text-[13px] font-semibold leading-[18px]',
  56: 'size-14 type-heading',
};

export function Avatar({ initials, tone, size }: { initials: string; tone: number; size: Size }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full text-text-on-primary ${SIZE[size]} ${
        TONES[Math.abs(tone) % TONES.length]
      }`}
    >
      {initials}
    </span>
  );
}
