import { describe, expect, it } from 'vitest';

import { fileTypeOf } from './fileType';

describe('fileTypeOf (#205)', () => {
  it.each([
    ['Faktura.pdf', null, 'pdf'],
    ['FAKTURA.PDF', null, 'pdf'],
    ['cennik.xlsx', null, 'xls'],
    ['export.csv', null, 'xls'],
    ['tabulka.ods', null, 'xls'],
    ['zmluva.docx', null, 'doc'],
    ['list.rtf', null, 'doc'],
    ['foto.HEIC', null, 'img'],
    ['sken.tiff', null, 'img'],
    ['zaloha.tar.gz', null, 'zip'],
    ['data.7z', null, 'zip'],
    ['FA-2026.isdoc', null, 'xml'],
    ['dodaci.xml', 'application/octet-stream', 'xml'],
    ['Faktura.pdf', 'application/octet-stream', 'pdf'],
    ['scan', 'image/png', 'img'],
    ['bez-pripony', 'application/pdf', 'pdf'],
    ['bez-pripony', 'application/octet-stream', 'other'],
    ['readme.txt', 'text/plain', 'other'],
    ['.pdf', null, 'other'],
    [null, null, 'other'],
  ] as const)('%s / %s → %s', (name, mime, type) => {
    expect(fileTypeOf(name, mime)).toBe(type);
  });
});
