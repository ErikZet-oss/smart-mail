import { describe, expect, it } from 'vitest';

import {
  clientSanitize,
  countCidImages,
  fillSignature,
  highlightHtml,
  isComplex,
  paintHtml,
  storeHtml,
} from './signatureHtml';

describe('signature HTML (D22)', () => {
  it('keeps a table and an https image, drops script', () => {
    const html =
      '<table style="border-collapse:collapse"><tr><td>Peter Hudák</td></tr></table><script>alert(1)</script>';
    const clean = clientSanitize(html);
    expect(clean.toLowerCase()).not.toContain('script');
    expect(clean).toContain('Peter Hudák');
    expect(clean).toContain('<table');
    expect(isComplex(html)).toBe(true);
    expect(isComplex('<p><strong>Jana Testová</strong></p>')).toBe(false);
  });

  it('paints cid images and stores them back as cid', () => {
    const painted = paintHtml('<img src="cid:sig-1@smartmail" alt="Peter Hudák">', {
      'sig-1@smartmail': '/api/settings/signature-images/abc',
    });
    expect(painted).toContain('/api/settings/signature-images/abc');
    expect(painted).toContain('data-cid="sig-1@smartmail"');
    expect(storeHtml(painted)).toContain('cid:sig-1@smartmail');
    expect(countCidImages('<img src="cid:a@smartmail"><img src="https://example.com/a.png">')).toBe(1);
  });

  it('drops an empty value together with the separator', () => {
    expect(fillSignature('{telefon} · {mobil}', { telefon: '0900 000 000', mobil: '' })).toBe('0900 000 000');
    expect(fillSignature('Ahoj {meno} z {pobocka}', { meno: 'Jana', pobocka: 'Senica' })).toBe('Ahoj Jana z Senica');
  });

  it('highlights tags without changing the text', () => {
    const source = '<p>Jana</p>';
    const highlighted = highlightHtml(source);
    expect(highlighted).toContain('text-brand-primary-700');
    const visible = highlighted
      .replace(/<[^>]+>/g, '')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&');
    expect(visible).toBe(source);
  });
});
