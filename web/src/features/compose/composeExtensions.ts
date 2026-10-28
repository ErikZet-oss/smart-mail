/** Compose editor nodes (issue #28). Signature and quote are atoms; the server rebuilds both on send. */

import { Node, type Editor } from '@tiptap/core';
import Color from '@tiptap/extension-color';
import Highlight from '@tiptap/extension-highlight';
import Image from '@tiptap/extension-image';
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table';
import TextAlign from '@tiptap/extension-text-align';
import { TextStyle } from '@tiptap/extension-text-style';
import StarterKit from '@tiptap/starter-kit';

import { clientSanitize, paintHtml } from '../settings/signatureHtml';

const LOGO_CID = 'logo@smartmail';

function paintSignature(html: string): string {
  return paintHtml(html, { [LOGO_CID]: '/logo-smart.svg' });
}

function atomView(tag: string, className: string, marker: string, html: string, paint: (value: string) => string) {
  const dom = document.createElement(tag);
  dom.className = className;
  dom.setAttribute(marker, '1');
  dom.setAttribute('contenteditable', 'false');
  dom.innerHTML = paint(html);
  return dom;
}

export const SignatureBlock = Node.create({
  name: 'signatureBlock',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,
  priority: 1000,
  addAttributes() {
    return {
      html: {
        default: '',
        parseHTML: (element) => element.innerHTML,
      },
    };
  },
  parseHTML() {
    return [{ tag: 'div[data-sm-signature="1"]' }];
  },
  renderHTML({ node }) {
    const dom = document.createElement('div');
    dom.setAttribute('data-sm-signature', '1');
    dom.innerHTML = String(node.attrs.html ?? '');
    return { dom };
  },
  addNodeView() {
    return ({ node }) => {
      let current = node;
      const dom = atomView(
        'div',
        'signature-block',
        'data-sm-signature',
        String(node.attrs.html ?? ''),
        paintSignature,
      );
      return {
        dom,
        ignoreMutation: () => true,
        stopEvent: () => true,
        update: (updated) => {
          if (updated.type.name !== 'signatureBlock') return false;
          current = updated;
          dom.innerHTML = paintSignature(String(current.attrs.html ?? ''));
          return true;
        },
      };
    };
  },
  addCommands() {
    return {
      setSignatureHtml:
        (html: string) =>
        ({ state, tr, dispatch }) => {
          let found: number | null = null;
          state.doc.descendants((child, pos) => {
            if (child.type.name === 'signatureBlock') {
              found = pos;
              return false;
            }
            return true;
          });
          if (found == null) {
            const created = state.schema.nodes.signatureBlock?.create({ html });
            if (!created) return false;
            tr.insert(state.doc.content.size, created);
          } else {
            const live = state.doc.nodeAt(found);
            if (!live) return false;
            tr.setNodeMarkup(found, undefined, { ...live.attrs, html });
          }
          if (dispatch) dispatch(tr);
          return true;
        },
    };
  },
});

export const QuotedMessage = Node.create({
  name: 'quotedMessage',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,
  priority: 1000,
  addAttributes() {
    return {
      html: {
        default: '',
        parseHTML: (element) => element.innerHTML,
      },
    };
  },
  parseHTML() {
    return [{ tag: 'blockquote[data-sm-quote="1"]' }];
  },
  renderHTML({ node }) {
    const dom = document.createElement('blockquote');
    dom.setAttribute('data-sm-quote', '1');
    dom.innerHTML = String(node.attrs.html ?? '');
    return { dom };
  },
  addNodeView() {
    return ({ node }) => {
      let current = node;
      const dom = atomView(
        'blockquote',
        'quoted-message',
        'data-sm-quote',
        String(node.attrs.html ?? ''),
        clientSanitize,
      );
      return {
        dom,
        ignoreMutation: () => true,
        stopEvent: () => true,
        update: (updated) => {
          if (updated.type.name !== 'quotedMessage') return false;
          current = updated;
          dom.innerHTML = clientSanitize(String(current.attrs.html ?? ''));
          return true;
        },
      };
    };
  },
});

export const composeExtensions = [
  StarterKit.configure({
    link: { openOnClick: false, autolink: false },
  }),
  TextStyle,
  Color.configure({ types: ['textStyle'] }),
  Highlight.configure({ multicolor: true }),
  TextAlign.configure({ types: ['heading', 'paragraph'] }),
  Table.configure({ resizable: false }),
  TableRow,
  TableHeader,
  TableCell,
  Image.configure({ inline: true, allowBase64: false }),
  SignatureBlock,
  QuotedMessage,
];

export function signatureHtmlOf(editor: Editor | null): string {
  if (!editor) return '';
  let html = '';
  editor.state.doc.descendants((node) => {
    if (node.type.name === 'signatureBlock') {
      html = String(node.attrs.html ?? '');
      return false;
    }
    return true;
  });
  return html;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    signatureBlock: {
      setSignatureHtml: (html: string) => ReturnType;
    };
  }
}
