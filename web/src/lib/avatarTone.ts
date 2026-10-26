// Persons have no stored colour, so it is derived from the person's id (stable across screens, sessions and list
// order). Only tokens with white text ≥ 3:1 at 16 px semibold (design/CONTRAST.md).
export const AVATAR_TONES = [
  'bg-success-600',
  'bg-brand-primary-600',
  'bg-cat-inquiry',
  'bg-cat-supplier_document',
  'bg-cat-supplier_info',
] as const;

/** FNV-1a 32-bit hash of the id → one of AVATAR_TONES. */
export function avatarTone(id: string): (typeof AVATAR_TONES)[number] {
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length] ?? AVATAR_TONES[0];
}
