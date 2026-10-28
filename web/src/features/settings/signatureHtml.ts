/** Signature HTML helpers (DECISIONS D22). Stored HTML keeps cid: and https://. The editor paints previews. */

export const SIGNATURE_LANGS = ['sk', 'cs', 'en', 'de'] as const;
export type SignatureLang = (typeof SIGNATURE_LANGS)[number];

export const SIGNATURE_VARIABLES = [
  'meno',
  'priezvisko',
  'funkcia',
  'telefon',
  'mobil',
  'email_osobny',
  'email_pobocky',
  'pobocka',
  'adresa_pobocky',
  'telefon_pobocky',
  'oteviracie_hodiny',
  'web',
  'fotka',
  'logo',
] as const;

const RAW_HTML = new Set(['fotka', 'logo']);
const VAR = /\{([a-z0-9_]+)\}/gi;
const SEP = /(?:[ \t]*[·|–][ \t]*|[ \t]+-[ \t]+|&nbsp;·&nbsp;|<br\s*\/?>)/gi;
const EMPTY = '\u0000';

const ALLOWED_TAGS = new Set([
  'a',
  'b',
  'blockquote',
  'br',
  'col',
  'colgroup',
  'div',
  'em',
  'font',
  'h1',
  'h2',
  'h3',
  'hr',
  'i',
  'img',
  'li',
  'ol',
  'p',
  'span',
  'strong',
  'table',
  'tbody',
  'td',
  'th',
  'thead',
  'tr',
  'u',
  'ul',
]);

const ALLOWED_ATTR = new Set([
  'align',
  'alt',
  'border',
  'cellpadding',
  'cellspacing',
  'class',
  'colspan',
  'data-cid',
  'data-remote',
  'data-sm-keep-src',
  'dir',
  'height',
  'href',
  'lang',
  'rowspan',
  'src',
  'style',
  'target',
  'title',
  'valign',
  'width',
]);

const ALLOWED_SRC =
  /^(https:\/\/|cid:|data:image\/(?:png|jpeg|gif|webp);|\/api\/settings\/signature-images\/|\/api\/mail\/image-proxy\?|\/logo-smart\.)/i;

export function isComplex(html: string): boolean {
  return /<\s*(table|img|div|span|font|hr)\b|style\s*=/i.test(html);
}

export function htmlBytes(html: string): number {
  return new TextEncoder().encode(html).length;
}

export function countCidImages(html: string): number {
  return html.match(/src\s*=\s*["']cid:/gi)?.length ?? 0;
}

export function httpsImageUrls(html: string): string[] {
  const urls: string[] = [];
  for (const match of html.matchAll(/src\s*=\s*["'](https:\/\/[^"']+)["']/gi)) {
    const url = match[1];
    if (url && !urls.includes(url)) urls.push(url);
  }
  return urls;
}

export function clientSanitize(html: string): string {
  if (!html) return '';
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
  const root = doc.body.firstElementChild;
  if (!root) return '';
  const clean = (node: Element) => {
    for (const child of [...node.children]) {
      const tag = child.tagName.toLowerCase();
      if (!ALLOWED_TAGS.has(tag)) {
        while (child.firstChild) node.insertBefore(child.firstChild, child);
        child.remove();
        continue;
      }
      for (const attr of [...child.attributes]) {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on') || !ALLOWED_ATTR.has(name)) child.removeAttribute(attr.name);
      }
      if (tag === 'a') {
        const href = child.getAttribute('href') ?? '';
        if (href && !/^(https?:|mailto:|#)/i.test(href)) child.removeAttribute('href');
      }
      if (tag === 'img') {
        const src = (child.getAttribute('src') ?? '').trim();
        if (src && !ALLOWED_SRC.test(src)) child.setAttribute('src', '');
      }
      const style = child.getAttribute('style');
      if (style && /expression|javascript|url\s*\(/i.test(style)) child.removeAttribute('style');
      clean(child);
    }
  };
  clean(root);
  return root.innerHTML;
}

function attrValue(tag: string, name: string): string | null {
  const match = new RegExp(`\\b${name}\\s*=\\s*(["'])(.*?)\\1`, 'i').exec(tag);
  return match?.[2] ?? null;
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

/** Map cid: and https src to a preview URL for the canvas. The stored string is unchanged. */
export function paintHtml(html: string, previews: Record<string, string>): string {
  const safe = clientSanitize(html);
  return safe.replace(/<img\b[^>]*>/gi, (tag) => {
    const src = attrValue(tag, 'src');
    if (!src) return tag;
    if (src.toLowerCase().startsWith('cid:')) {
      const cid = src.slice(4);
      const url = previews[cid] ?? previews[src];
      if (!url) return tag;
      return tag.replace(src, url).replace(/<img\b/i, `<img data-cid="${escapeAttr(cid)}"`);
    }
    if (src.toLowerCase().startsWith('https://')) {
      const url = previews[src];
      if (!url) return tag;
      return tag.replace(src, url).replace(/<img\b/i, `<img data-remote="${escapeAttr(src)}"`);
    }
    return tag;
  });
}

/** Turn a painted canvas back into stored HTML (cid: / https://). */
export function storeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
  const root = doc.body.firstElementChild;
  if (!root) return '';
  for (const img of root.querySelectorAll('img')) {
    const cid = img.getAttribute('data-cid');
    const remote = img.getAttribute('data-remote');
    if (cid) img.setAttribute('src', `cid:${cid}`);
    else if (remote) img.setAttribute('src', remote);
    img.removeAttribute('data-cid');
    img.removeAttribute('data-remote');
  }
  return root.innerHTML;
}

export function highlightHtml(source: string): string {
  const escaped = source.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped.replace(
    /(&lt;!--[\s\S]*?--&gt;)|(&lt;\/?[a-zA-Z][\s\S]*?&gt;)/g,
    (match, comment: string | undefined) => {
      if (comment) return `<span class="text-text-tertiary">${comment}</span>`;
      return `<span class="text-brand-primary-700">${match}</span>`;
    },
  );
}

export function fillSignature(template: string, values: Record<string, string>): string {
  const text = template.replace(VAR, (full, name: string) => {
    const key = name.toLowerCase();
    if (!SIGNATURE_VARIABLES.includes(key as (typeof SIGNATURE_VARIABLES)[number])) return full;
    const raw = values[key] ?? '';
    if (!raw) return EMPTY;
    if (RAW_HTML.has(key)) return raw;
    return raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  });
  return text
    .replace(new RegExp(`(?:${SEP.source})${EMPTY}`, 'gi'), '')
    .replace(new RegExp(`${EMPTY}(?:${SEP.source})`, 'gi'), '')
    .replace(new RegExp(`[ \\t]+${EMPTY}`, 'g'), '')
    .replace(new RegExp(`${EMPTY}[ \\t]+`, 'g'), '')
    .replaceAll(EMPTY, '');
}

export function formatSignatureSize(bytes: number): string {
  const kb = bytes / 1024;
  return `${kb.toLocaleString('sk-SK', { minimumFractionDigits: kb > 0 && kb < 10 ? 1 : 0, maximumFractionDigits: 1 })} kB`;
}

export async function svgFileToPng(file: File): Promise<File> {
  const text = await file.text();
  const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('image_type'));
      img.src = url;
    });
    const width = image.naturalWidth || 240;
    const height = image.naturalHeight || 80;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('image_type');
    ctx.drawImage(image, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!blob) throw new Error('image_type');
    const name = file.name.replace(/\.svg$/i, '.png') || 'obrazok.png';
    return new File([blob], name, { type: 'image/png' });
  } finally {
    URL.revokeObjectURL(url);
  }
}
