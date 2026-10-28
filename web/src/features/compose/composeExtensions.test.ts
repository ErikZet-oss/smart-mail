import { Editor } from '@tiptap/core';
import { describe, expect, it } from 'vitest';

import { composeExtensions } from './composeExtensions';

const CARD = [
  '<div data-sm-signature="1">',
  '<table style="border-collapse:collapse"><tr><td style="color:#0f75bc">Jana Testová</td></tr></table>',
  '<img src="cid:logo@smartmail" alt="SMART">',
  '<img src="https://cdn.example/jana.png" alt="Jana Testová">',
  '</div>',
].join('');

const QUOTE = '<blockquote data-sm-quote="1"><table><tr><td>M10×30</td><td>5 000 ks</td></tr></table></blockquote>';

describe('compose editor keeps signature and quote HTML', () => {
  it('does not flatten a Karta signature or a quoted table', () => {
    const editor = new Editor({
      extensions: composeExtensions,
      content:
        '<p>Ďakujeme. <u>podčiarknuté</u> <span style="color:#0f75bc">modré</span></p>' +
        '<table><tr><td>riadok</td></tr></table>' +
        '<img src="cid:img-1@smartmail" alt="foto">' +
        QUOTE +
        CARD,
    });
    const json = editor.getJSON();
    const types = (json.content ?? []).map((node) => node.type);
    expect(types).toContain('signatureBlock');
    expect(types).toContain('quotedMessage');
    const signature = json.content?.find((node) => node.type === 'signatureBlock');
    const quote = json.content?.find((node) => node.type === 'quotedMessage');
    expect(String(signature?.attrs?.html)).toContain('<table');
    expect(String(signature?.attrs?.html)).toContain('style=');
    expect(String(signature?.attrs?.html)).toContain('cid:logo@smartmail');
    expect(String(signature?.attrs?.html)).toContain('https://cdn.example/jana.png');
    expect(String(quote?.attrs?.html)).toContain('<table');
    expect(String(quote?.attrs?.html)).toContain('M10×30');

    const html = editor.getHTML();
    expect(html).toContain('<u>podčiarknuté</u>');
    expect(html).toContain('0f75bc');
    expect(html).toContain('cid:img-1@smartmail');
    expect(html).toContain('data-sm-signature="1"');
    expect(html).toContain('data-sm-quote="1"');
    expect(html).toContain('https://cdn.example/jana.png');
    editor.destroy();
  });
});
