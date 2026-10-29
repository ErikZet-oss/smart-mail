import type { Editor } from '@tiptap/core';

// The compose AI panel (2d) works on the person's own text only: everything before the first protected block.
// The quote and the signature are separate nodes the model never sees and a proposal can never replace.
const PROTECTED = new Set(['signatureBlock', 'quotedMessage']);

/** End position of the person's own text (start of the first quote / signature block). */
function userEnd(editor: Editor): number {
  let end: number | null = null;
  editor.state.doc.forEach((node, offset) => {
    if (end === null && PROTECTED.has(node.type.name)) end = offset;
  });
  return end ?? editor.state.doc.content.size;
}

/** Plain text of the person's own part, paragraphs separated by a blank line. */
export function userTextOf(editor: Editor | null): string {
  if (!editor) return '';
  const end = userEnd(editor);
  const blocks: string[] = [];
  editor.state.doc.forEach((node, offset) => {
    if (offset >= end || PROTECTED.has(node.type.name)) return;
    blocks.push(node.textBetween(0, node.content.size, '\n', '\n'));
  });
  return blocks
    .join('\n\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** Model text → paragraphs (escaped: the proposal is never HTML). */
export function textToHtml(text: string): string {
  const paragraphs = text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  return paragraphs.map((p) => `<p>${escapeHtml(p).replace(/\n/g, '<br>')}</p>`).join('') || '<p></p>';
}

/** „Použiť“: replace only the person's own text; quote and signature stay as they are. */
export function replaceUserText(editor: Editor, text: string): void {
  editor
    .chain()
    .insertContentAt({ from: 0, to: userEnd(editor) }, textToHtml(text))
    .run();
}

export type DiffPart = { kind: 'same' | 'added' | 'removed'; text: string };

/** Word diff for the preview (LCS on words; drafts are short). */
export function wordDiff(before: string, after: string): DiffPart[] {
  // words with their trailing whitespace, so spaces never match on their own
  const a = before.match(/\S+\s*|\s+/g) ?? [];
  const b = after.match(/\S+\s*|\s+/g) ?? [];
  const width = b.length + 1;
  const lcs = new Int32Array((a.length + 1) * width);
  const at = (i: number, j: number) => lcs[i * width + j] ?? 0;
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i * width + j] = a[i] === b[j] ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
    }
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart['kind'], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    const wa = a[i] ?? '';
    const wb = b[j] ?? '';
    if (i < a.length && j < b.length && wa === wb) {
      push('same', wa);
      i += 1;
      j += 1;
    } else if (j >= b.length || (i < a.length && at(i + 1, j) >= at(i, j + 1))) {
      push('removed', wa);
      i += 1;
    } else {
      push('added', wb);
      j += 1;
    }
  }
  return out;
}
