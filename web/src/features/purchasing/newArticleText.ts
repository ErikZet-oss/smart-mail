/** D32 (#239) helpers of the „Nový artikel v Money“ form (same size rule as `app/purchasing/new_article.py`). */
const SIZE = /(?<![A-Za-z0-9])M\s?(\d{1,3})(?!\d)/i;

/** „Šroub ISO 7380 M6x16 A2“ → „Šroub ISO 7380 A2“: the main card name has no size (Figma 256:90550). */
export function withoutSize(text: string): string {
  return text
    .replace(/(?<![A-Za-z0-9])M\s?\d{1,3}(?:[x×]\s?\d+)?(?![\d])/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export function sizeOf(text: string): number | null {
  const m = SIZE.exec(text);
  return m ? Number(m[1]) : null;
}
