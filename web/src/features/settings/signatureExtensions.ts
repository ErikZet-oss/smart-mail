/** TipTap nodes for the signature editor. Complex HTML (tables, inline styles) stays a raw block so a paste round-trips. */

import { Extension, Mark, Node, mergeAttributes, type Editor } from '@tiptap/core';

import { isComplex, paintHtml, storeHtml } from './signatureHtml';

export type SignatureStorage = {
  silent: boolean;
  previews: Record<string, string>;
  draft: string | null;
};

export function signatureStorage(editor: Editor): SignatureStorage {
  const bag = editor.storage as unknown as { signature: SignatureStorage };
  return bag.signature;
}

export const SignatureMark = Extension.create({
  name: 'signature',
  addStorage() {
    return { silent: false, previews: {}, draft: null } satisfies SignatureStorage;
  },
});

export const TextStyle = Mark.create({
  name: 'textStyle',
  addAttributes() {
    return {
      fontFamily: {
        default: null,
        parseHTML: (element) => element.style.fontFamily || null,
        renderHTML: () => ({}),
      },
      fontSize: {
        default: null,
        parseHTML: (element) => element.style.fontSize || null,
        renderHTML: () => ({}),
      },
      color: {
        default: null,
        parseHTML: (element) => element.style.color || null,
        renderHTML: () => ({}),
      },
      backgroundColor: {
        default: null,
        parseHTML: (element) => element.style.backgroundColor || null,
        renderHTML: () => ({}),
      },
    };
  },
  parseHTML() {
    return [
      {
        tag: 'span',
        getAttrs: (element) => {
          if (!(element instanceof HTMLElement)) return false;
          const { fontFamily, fontSize, color, backgroundColor } = element.style;
          if (!fontFamily && !fontSize && !color && !backgroundColor) return false;
          return {};
        },
      },
    ];
  },
  renderHTML({ mark }) {
    const style = [
      mark.attrs.fontFamily ? `font-family: ${mark.attrs.fontFamily}` : '',
      mark.attrs.fontSize ? `font-size: ${mark.attrs.fontSize}` : '',
      mark.attrs.color ? `color: ${mark.attrs.color}` : '',
      mark.attrs.backgroundColor ? `background-color: ${mark.attrs.backgroundColor}` : '',
    ]
      .filter(Boolean)
      .join('; ');
    return ['span', { style }, 0];
  },
});

export const TextAlign = Extension.create({
  name: 'textAlign',
  addGlobalAttributes() {
    return [
      {
        types: ['paragraph'],
        attributes: {
          textAlign: {
            default: null,
            parseHTML: (element) => element.style.textAlign || null,
            renderHTML: (attributes) => {
              const align = attributes.textAlign as string | null;
              if (!align) return {};
              return { style: `text-align: ${align}` };
            },
          },
        },
      },
    ];
  },
});

export const SigImage = Node.create({
  name: 'sigImage',
  inline: true,
  group: 'inline',
  atom: true,
  addAttributes() {
    return {
      src: { default: null },
      alt: { default: '' },
      width: { default: null },
      height: { default: null },
    };
  },
  parseHTML: () => [{ tag: 'img[src]' }],
  renderHTML: ({ HTMLAttributes }) => ['img', mergeAttributes(HTMLAttributes)],
});

export const RawBlock = Node.create({
  name: 'rawBlock',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      html: { default: '' },
    };
  },
  parseHTML: () => [{ tag: 'div[data-signature-raw]' }],
  renderHTML: () => ['div', { 'data-signature-raw': '' }],
  addNodeView() {
    return ({ node, editor, getPos }) => {
      let current = node;
      let focused = false;
      const dom = document.createElement('div');
      dom.setAttribute('data-signature-raw', '');
      dom.className = 'signature-raw min-h-[200px] outline-none';
      dom.contentEditable = editor.isEditable ? 'true' : 'false';

      const paint = () => {
        if (focused) return;
        const storage = signatureStorage(editor);
        const html = storage.draft ?? String(current.attrs.html ?? '');
        dom.innerHTML = paintHtml(html, storage.previews);
      };
      paint();

      const publish = () => {
        const next = storeHtml(dom.innerHTML);
        signatureStorage(editor).draft = next;
        editor.view.dom.dispatchEvent(new CustomEvent('signature-draft', { detail: next }));
      };

      dom.addEventListener('focus', () => {
        focused = true;
      });
      dom.addEventListener('blur', () => {
        focused = false;
        const next = storeHtml(dom.innerHTML);
        signatureStorage(editor).draft = next;
        const pos = getPos();
        if (typeof pos !== 'number') return;
        const live = editor.state.doc.nodeAt(pos);
        if (!live || live.type.name !== 'rawBlock' || live.attrs.html === next) return;
        editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, undefined, { ...live.attrs, html: next }));
      });
      dom.addEventListener('input', publish);

      return {
        dom,
        update: (updated) => {
          if (updated.type.name !== 'rawBlock') return false;
          current = updated;
          paint();
          return true;
        },
        ignoreMutation: () => true,
        stopEvent: () => true,
      };
    };
  },
});

export function docIsRaw(editor: Editor): boolean {
  const content = editor.getJSON().content ?? [];
  return content.length === 1 && content[0]?.type === 'rawBlock';
}

export function exportSignatureHtml(editor: Editor): string {
  if (docIsRaw(editor)) {
    const draft = signatureStorage(editor).draft;
    if (typeof draft === 'string') return draft;
    const html = editor.getJSON().content?.[0]?.attrs?.html;
    return typeof html === 'string' ? html : '';
  }
  return editor.getHTML();
}

export function loadSignatureHtml(editor: Editor, html: string): void {
  const storage = signatureStorage(editor);
  storage.silent = true;
  storage.draft = isComplex(html) ? html : null;
  if (isComplex(html)) {
    editor.commands.setContent(
      { type: 'doc', content: [{ type: 'rawBlock', attrs: { html } }] },
      { emitUpdate: false },
    );
  } else {
    editor.commands.setContent(html || '<p></p>', { emitUpdate: false });
  }
  storage.silent = false;
}

export function repaintRaw(editor: Editor): void {
  const dom = editor.view.dom.querySelector<HTMLElement>('[data-signature-raw]');
  if (!dom || dom === document.activeElement) return;
  const storage = signatureStorage(editor);
  const html = storage.draft ?? '';
  if (!html && !docIsRaw(editor)) return;
  const source = storage.draft ?? String(editor.getJSON().content?.[0]?.attrs?.html ?? '');
  dom.innerHTML = paintHtml(source, storage.previews);
}
