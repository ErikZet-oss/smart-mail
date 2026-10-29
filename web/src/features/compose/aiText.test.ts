import { Editor } from '@tiptap/core';
import { describe, expect, it } from 'vitest';

import { replaceUserText, textToHtml, userTextOf, wordDiff } from './aiText';
import { composeExtensions } from './composeExtensions';

const QUOTE = '<blockquote data-sm-quote="1"><p>Koľko stoja skrutky M8?</p></blockquote>';
const SIGNATURE = '<div data-sm-signature="1"><p>Jana Testová · Smart s.r.o.</p></div>';

const editorWith = (user: string) =>
  new Editor({ extensions: composeExtensions, content: `${user}${QUOTE}${SIGNATURE}` });

describe('2d compose AI text', () => {
  it('reads only the person’s own text — never the quote or the signature', () => {
    const editor = editorWith('<p>Dobrý deň,</p><p>posielam <b>ponuku</b>.<br>Riadok 2</p>');
    expect(userTextOf(editor)).toBe('Dobrý deň,\n\nposielam ponuku.\nRiadok 2');
  });

  it('Použiť replaces only the person’s text; quote and signature stay', () => {
    const editor = editorWith('<p>ahoj</p>');
    replaceUserText(editor, 'Dobrý deň,\n\nposielame ponuku <M8>.');
    const html = editor.getHTML();
    expect(html.startsWith('<p>Dobrý deň,</p><p>posielame ponuku &lt;M8&gt;.</p>')).toBe(true);
    expect(html).toContain('Koľko stoja skrutky M8?');
    expect(html).toContain('Jana Testová · Smart s.r.o.');
    expect(userTextOf(editor)).toBe('Dobrý deň,\n\nposielame ponuku <M8>.');
  });

  it('escapes the model text', () => {
    expect(textToHtml('<script>x</script>')).toBe('<p>&lt;script&gt;x&lt;/script&gt;</p>');
    expect(textToHtml('  ')).toBe('<p></p>');
  });

  it('word diff marks removed and added words', () => {
    expect(wordDiff('ahoj posielam ponuku', 'Dobrý deň, posielame ponuku')).toEqual([
      { kind: 'removed', text: 'ahoj posielam ' },
      { kind: 'added', text: 'Dobrý deň, posielame ' },
      { kind: 'same', text: 'ponuku' },
    ]);
  });
});
