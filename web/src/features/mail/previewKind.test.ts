import { describe, expect, it } from 'vitest';

import { previewKind, xmlRows } from './previewKind';

describe('#46 W2l previewKind', () => {
  it.each([
    ['application/pdf', 'a.pdf', 'pdf'],
    ['application/octet-stream', 'Faktura.PDF', 'pdf'],
    ['image/png', 'a.png', 'image'],
    ['image/jpeg; name=a.jpg', 'a.jpg', 'image'],
    ['image/svg+xml', 'logo.svg', null],
    ['text/xml', 'a.xml', 'xml'],
    ['application/octet-stream', 'faktura.isdoc', 'xml'],
    ['application/zip', 'podklady.zip', null],
  ])('%s %s → %s', (content_type, filename, kind) => {
    expect(previewKind({ content_type, filename })).toBe(kind);
  });
});

describe('#46 W2l xmlRows', () => {
  it('lists leaf values with their path and never keeps markup', () => {
    const rows = xmlRows('<Invoice><ID>2611452</ID><Total><Amount>373.20</Amount></Total><script>x</script></Invoice>');
    expect(rows).toEqual([
      { path: 'ID', value: '2611452' },
      { path: 'Total › Amount', value: '373.20' },
      { path: 'script', value: 'x' },
    ]);
  });

  it('returns null for broken XML', () => {
    expect(xmlRows('<Invoice><ID>')).toBeNull();
  });
});
