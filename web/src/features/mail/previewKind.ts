import type { AttachmentOut } from './mailApi';

export type PreviewKind = 'pdf' | 'image' | 'xml';

/** Which attachments open in W2l instead of downloading (#46): PDF, raster images (never SVG), XML / ISDOC. */
export function previewKind(att: Pick<AttachmentOut, 'content_type' | 'filename'>): PreviewKind | null {
  const type = (att.content_type || '').split(';')[0]?.trim().toLowerCase() ?? '';
  const name = att.filename.toLowerCase();
  if (type === 'application/pdf' || (type === 'application/octet-stream' && name.endsWith('.pdf'))) return 'pdf';
  if (type.startsWith('image/') && !type.includes('svg')) return 'image';
  if (type === 'text/xml' || type === 'application/xml' || name.endsWith('.isdoc') || name.endsWith('.xml')) {
    return 'xml';
  }
  return null;
}

export type XmlRow = { path: string; value: string };

/** ISDOC / XML as a table of leaf values (element path → text). DOMParser on XML never runs scripts. */
export function xmlRows(text: string, limit = 500): XmlRow[] | null {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) return null;
  const rows: XmlRow[] = [];
  const walk = (el: Element, path: string[]) => {
    if (rows.length >= limit) return;
    const here = [...path, el.localName];
    const children = Array.from(el.children);
    if (!children.length) {
      const value = (el.textContent ?? '').trim();
      if (value) rows.push({ path: here.slice(1).join(' › ') || el.localName, value });
      return;
    }
    for (const child of children) walk(child, here);
  };
  if (doc.documentElement) walk(doc.documentElement, []);
  return rows;
}
