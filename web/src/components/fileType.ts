/** #205 file type of an attachment for FileTypeIcon. The extension wins over the MIME type (mail clients often send
 * `application/octet-stream`). */
export type FileType = 'pdf' | 'xls' | 'doc' | 'img' | 'zip' | 'xml' | 'other';

const BY_EXT: Record<string, FileType> = {
  pdf: 'pdf',
  xls: 'xls',
  xlsx: 'xls',
  xlsm: 'xls',
  csv: 'xls',
  ods: 'xls',
  doc: 'doc',
  docx: 'doc',
  odt: 'doc',
  rtf: 'doc',
  jpg: 'img',
  jpeg: 'img',
  png: 'img',
  gif: 'img',
  webp: 'img',
  heic: 'img',
  bmp: 'img',
  tif: 'img',
  tiff: 'img',
  zip: 'zip',
  rar: 'zip',
  '7z': 'zip',
  gz: 'zip',
  xml: 'xml',
  isdoc: 'xml',
  isdocx: 'xml',
};

export const FILE_TYPE_LABEL: Record<FileType, string> = {
  pdf: 'PDF',
  xls: 'XLS',
  doc: 'DOC',
  img: 'IMG',
  zip: 'ZIP',
  xml: 'XML',
  other: '',
};

export function fileTypeOf(filename: string | null | undefined, mime?: string | null): FileType {
  const name = (filename ?? '').trim().toLowerCase();
  const dot = name.lastIndexOf('.');
  if (dot > 0 && dot < name.length - 1) {
    const byExt = BY_EXT[name.slice(dot + 1)];
    if (byExt) return byExt;
  }
  const m = (mime ?? '').toLowerCase().split(';')[0]?.trim() ?? '';
  if (m === 'application/pdf') return 'pdf';
  if (m.startsWith('image/')) return 'img';
  if (m === 'application/xml' || m === 'text/xml') return 'xml';
  if (m === 'application/zip' || m === 'application/x-zip-compressed') return 'zip';
  if (m.includes('spreadsheet') || m === 'application/vnd.ms-excel' || m === 'text/csv') return 'xls';
  if (m.includes('wordprocessing') || m === 'application/msword') return 'doc';
  return 'other';
}

/** Accessible name of an attachment: „PDF, Faktura.pdf, 84 kB“ (the icon itself is aria-hidden). */
export function attachmentLabel(filename: string, mime: string | null | undefined, size: string): string {
  const type = FILE_TYPE_LABEL[fileTypeOf(filename, mime)];
  return [type, filename, size].filter(Boolean).join(', ');
}
