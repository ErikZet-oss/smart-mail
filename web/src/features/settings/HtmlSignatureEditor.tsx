import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Code,
  Image as ImageIcon,
  Italic,
  Link2,
  Minus,
  Omega,
  Palette,
  Table,
  Underline,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import {
  RawBlock,
  SigImage,
  SignatureMark,
  TextAlign,
  TextStyle,
  docIsRaw,
  exportSignatureHtml,
  loadSignatureHtml,
  repaintRaw,
  signatureStorage,
} from './signatureExtensions';
import {
  SIGNATURE_LANGS,
  SIGNATURE_VARIABLES,
  clientSanitize,
  countCidImages,
  formatSignatureSize,
  highlightHtml,
  htmlBytes,
  httpsImageUrls,
  isComplex,
  svgFileToPng,
  type SignatureLang,
} from './signatureHtml';

const MAX_IMAGE_BYTES = 200 * 1024;
const FONTS = ['Arial', 'Calibri', 'Georgia', 'Tahoma', 'Times New Roman', 'Verdana', 'Courier New'];
const SIZES = ['10', '11', '12', '13', '14', '16', '18', '20', '24'];
const SPECIAL = [
  'á',
  'ä',
  'č',
  'ď',
  'é',
  'í',
  'ĺ',
  'ľ',
  'ň',
  'ó',
  'ô',
  'ŕ',
  'š',
  'ť',
  'ú',
  'ý',
  'ž',
  'Á',
  'Č',
  'Ď',
  'É',
  'Í',
  'Ľ',
  'Ň',
  'Ó',
  'Ô',
  'Š',
  'Ť',
  'Ú',
  'Ý',
  'Ž',
  '€',
  '§',
  '–',
  '—',
  '„',
  '“',
  '…',
  '•',
  '·',
];

const LANG_KEY: Record<SignatureLang, string> = {
  sk: 'settings.signature.langSk',
  cs: 'settings.signature.langCz',
  en: 'settings.signature.langEn',
  de: 'settings.signature.langDe',
};

export type SignatureImageRecord = {
  id: string;
  cid: string;
  preview_url: string;
};

type Props = {
  value: string;
  onChange: (html: string) => void;
  label?: string;
  languages?: boolean;
  language?: SignatureLang;
  onLanguage?: (lang: SignatureLang) => void;
  variables?: boolean;
  presets?: { karta?: string; text?: string };
  uploadImage?: (file: File) => Promise<SignatureImageRecord>;
  imagePreviews?: Record<string, string>;
  onRemoteUrls?: (urls: string[]) => void;
  stripped?: string[];
  maxBytes?: number;
  footer?: 'signature' | 'plain';
  disabled?: boolean;
};

/** D22 signature editor: TipTap for simple HTML, a raw block when the HTML has tables or inline styles. */
export function HtmlSignatureEditor({
  value,
  onChange,
  label,
  languages = false,
  language = 'sk',
  onLanguage,
  variables = false,
  presets,
  uploadImage,
  imagePreviews,
  onRemoteUrls,
  stripped,
  maxBytes = 64 * 1024,
  footer = 'signature',
  disabled = false,
}: Props) {
  const { t } = useTranslation();
  const echo = useRef(value);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  const savedRange = useRef<Range | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [sourceDraft, setSourceDraft] = useState('');
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState('https://');
  const [imageOpen, setImageOpen] = useState(false);
  const [imageTab, setImageTab] = useState<'file' | 'url'>('file');
  const [imageUrl, setImageUrl] = useState('https://');
  const [imageAlt, setImageAlt] = useState('');
  const [imageWidth, setImageWidth] = useState('');
  const [imageError, setImageError] = useState('');
  const [specialOpen, setSpecialOpen] = useState(false);
  const [colorOpen, setColorOpen] = useState(false);
  const [textColor, setTextColor] = useState(() => cssHex('--text-primary'));
  const [backColor, setBackColor] = useState(() => cssHex('--bg-muted'));
  const [confirmPreset, setConfirmPreset] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        code: false,
        codeBlock: false,
        blockquote: false,
        strike: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        link: { openOnClick: false, autolink: false },
      }),
      SignatureMark,
      TextStyle,
      TextAlign,
      SigImage,
      RawBlock,
    ],
    content: isComplex(value)
      ? { type: 'doc', content: [{ type: 'rawBlock', attrs: { html: value } }] }
      : value || '<p></p>',
    editable: !disabled,
    immediatelyRender: true,
    editorProps: {
      attributes: {
        class: 'type-body text-text-primary',
        'aria-label': label ?? t('settings.signature.editor'),
      },
    },
    onUpdate: ({ editor: current }) => {
      if (signatureStorage(current).silent || docIsRaw(current)) return;
      const html = current.getHTML();
      if (html === echo.current) return;
      echo.current = html;
      onChangeRef.current(html);
    },
  });

  useEffect(() => {
    if (!editor) return;
    const dom = editor.view.dom;
    const onDraft = (event: Event) => {
      const html = (event as CustomEvent<string>).detail;
      if (typeof html !== 'string' || html === echo.current) return;
      echo.current = html;
      onChangeRef.current(html);
    };
    dom.addEventListener('signature-draft', onDraft);
    return () => dom.removeEventListener('signature-draft', onDraft);
  }, [editor]);

  useEffect(() => {
    if (!editor || value === echo.current) return;
    echo.current = value;
    loadSignatureHtml(editor, value);
  }, [editor, value]);

  useEffect(() => {
    if (!editor) return;
    signatureStorage(editor).previews = imagePreviews ?? {};
    repaintRaw(editor);
  }, [editor, imagePreviews]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [editor, disabled]);

  useEffect(() => {
    if (!onRemoteUrls) return;
    const missing = httpsImageUrls(value).filter((url) => !imagePreviews?.[url]);
    if (missing.length) onRemoteUrls(missing);
  }, [value, imagePreviews, onRemoteUrls]);

  function remember() {
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) savedRange.current = sel.getRangeAt(0).cloneRange();
  }

  function restore() {
    const sel = window.getSelection();
    if (!savedRange.current || !sel) return;
    sel.removeAllRanges();
    sel.addRange(savedRange.current);
  }

  function rawElement(): HTMLElement | null {
    return editor?.view.dom.querySelector<HTMLElement>('[data-signature-raw]') ?? null;
  }

  function runRaw(fn: () => void): boolean {
    const el = rawElement();
    if (!el) return false;
    el.focus();
    restore();
    document.execCommand('styleWithCSS', false, 'true');
    fn();
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }

  function forceRaw(then: () => void) {
    if (!editor) return;
    if (docIsRaw(editor)) {
      runRaw(then);
      return;
    }
    const html = exportSignatureHtml(editor) || '<p></p>';
    const storage = signatureStorage(editor);
    storage.silent = true;
    storage.draft = html;
    editor.commands.setContent(
      { type: 'doc', content: [{ type: 'rawBlock', attrs: { html } }] },
      { emitUpdate: false },
    );
    storage.silent = false;
    echo.current = html;
    onChange(html);
    requestAnimationFrame(() => runRaw(then));
  }

  function onBold() {
    if (!editor) return;
    if (docIsRaw(editor)) runRaw(() => document.execCommand('bold'));
    else editor.chain().focus().toggleBold().run();
  }
  function onItalic() {
    if (!editor) return;
    if (docIsRaw(editor)) runRaw(() => document.execCommand('italic'));
    else editor.chain().focus().toggleItalic().run();
  }
  function onUnderline() {
    if (!editor) return;
    if (docIsRaw(editor)) runRaw(() => document.execCommand('underline'));
    else editor.chain().focus().toggleUnderline().run();
  }
  function onAlign(align: 'left' | 'center' | 'right') {
    if (!editor) return;
    const cmd = align === 'left' ? 'justifyLeft' : align === 'center' ? 'justifyCenter' : 'justifyRight';
    if (docIsRaw(editor)) runRaw(() => document.execCommand(cmd));
    else editor.chain().focus().updateAttributes('paragraph', { textAlign: align }).run();
  }
  function onFont(family: string) {
    if (!editor) return;
    restore();
    if (docIsRaw(editor)) runRaw(() => document.execCommand('fontName', false, family));
    else {
      const current = editor.getAttributes('textStyle') as Record<string, string | null>;
      editor
        .chain()
        .focus()
        .setMark('textStyle', { ...current, fontFamily: family })
        .run();
    }
  }
  function onSize(px: string) {
    if (!editor) return;
    restore();
    if (docIsRaw(editor)) {
      runRaw(() => {
        document.execCommand('fontSize', false, '3');
        rawElement()
          ?.querySelectorAll('font[size]')
          .forEach((node) => {
            const span = document.createElement('span');
            span.style.fontSize = `${px}px`;
            span.innerHTML = node.innerHTML;
            node.replaceWith(span);
          });
      });
      return;
    }
    const current = editor.getAttributes('textStyle') as Record<string, string | null>;
    editor
      .chain()
      .focus()
      .setMark('textStyle', { ...current, fontSize: `${px}px` })
      .run();
  }
  function onColor(kind: 'color' | 'backgroundColor', color: string) {
    if (!editor || !color) return;
    if (docIsRaw(editor)) {
      runRaw(() => document.execCommand(kind === 'color' ? 'foreColor' : 'hiliteColor', false, color));
      return;
    }
    const current = editor.getAttributes('textStyle') as Record<string, string | null>;
    editor
      .chain()
      .focus()
      .setMark('textStyle', { ...current, [kind]: color })
      .run();
  }
  function insertText(text: string) {
    if (!editor) return;
    if (docIsRaw(editor)) runRaw(() => document.execCommand('insertText', false, text));
    else editor.chain().focus().insertContent(text).run();
  }
  function insertHtml(html: string) {
    forceRaw(() => document.execCommand('insertHTML', false, html));
  }
  function applyLink() {
    const url = linkUrl.trim();
    if (!/^https?:\/\//i.test(url) && !/^mailto:/i.test(url)) return;
    if (!editor) return;
    if (docIsRaw(editor)) runRaw(() => document.execCommand('createLink', false, url));
    else editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
    setLinkOpen(false);
  }
  function insertImage(src: string) {
    const alt = imageAlt.replace(/"/g, '');
    const width = imageWidth.replace(/[^\d]/g, '');
    const tag = `<img src="${src.replace(/"/g, '&quot;')}" alt="${alt}"${width ? ` width="${width}"` : ''}>`;
    if (editor && !docIsRaw(editor) && !isComplex(exportSignatureHtml(editor))) {
      editor
        .chain()
        .focus()
        .insertContent({ type: 'sigImage', attrs: { src, alt, width: width || null } })
        .run();
    } else {
      insertHtml(tag);
    }
    setImageOpen(false);
  }

  async function onPickFile(file: File | undefined) {
    if (!file || !uploadImage) return;
    setImageError('');
    if (countCidImages(editor ? exportSignatureHtml(editor) : value) >= 5) {
      setImageError(t('settings.signature.imageLimit'));
      return;
    }
    let payload = file;
    const svg = file.type === 'image/svg+xml' || file.name.toLowerCase().endsWith('.svg');
    try {
      if (svg) payload = await svgFileToPng(file);
    } catch {
      setImageError(t('settings.signature.imageType'));
      return;
    }
    if (!svg && !['image/png', 'image/jpeg', 'image/gif'].includes(file.type)) {
      setImageError(t('settings.signature.imageType'));
      return;
    }
    if (payload.size > MAX_IMAGE_BYTES) {
      setImageError(t('settings.signature.imageTooLarge'));
      return;
    }
    try {
      const saved = await uploadImage(payload);
      insertImage(`cid:${saved.cid}`);
    } catch {
      setImageError(t('settings.signature.imageType'));
    }
  }

  function openSource() {
    setSourceDraft(editor ? exportSignatureHtml(editor) : value);
    setSourceOpen(true);
  }

  function commitSource() {
    echo.current = sourceDraft;
    if (editor) loadSignatureHtml(editor, sourceDraft);
    onChange(sourceDraft);
    setSourceOpen(false);
  }

  function askPreset(html: string | undefined) {
    if (!html) return;
    if (value.trim() && value !== html) setConfirmPreset(html);
    else {
      echo.current = html;
      if (editor) loadSignatureHtml(editor, html);
      onChange(html);
    }
  }

  const bytes = htmlBytes(value);
  const images = countCidImages(value);
  const imagePhrase =
    images === 1
      ? t('settings.signature.imagesOne', { count: images })
      : images >= 2 && images <= 4
        ? t('settings.signature.imagesFew', { count: images })
        : t('settings.signature.imagesMany', { count: images });

  return (
    <div className="flex flex-col gap-2">
      {label ? <span className="type-label text-text-secondary">{label}</span> : null}
      {languages ? (
        <div className="flex gap-1" role="tablist" aria-label={t('settings.signature.editor')}>
          {SIGNATURE_LANGS.map((lang) => (
            <button
              key={lang}
              type="button"
              role="tab"
              aria-selected={language === lang}
              className={`type-label h-8 rounded-sm px-3 ${
                language === lang
                  ? 'bg-brand-primary-600 text-text-on-primary'
                  : 'bg-bg-subtle text-text-secondary hover:bg-bg-muted'
              }`}
              onClick={() => onLanguage?.(lang)}
            >
              {t(LANG_KEY[lang])}
            </button>
          ))}
        </div>
      ) : null}
      {presets ? (
        <div className="flex w-fit rounded-md border border-border-default p-0.5">
          {(
            [
              ['karta', presets.karta, 'settings.signature.presetCard'],
              ['text', presets.text, 'settings.signature.presetText'],
            ] as const
          ).map(([key, html, labelKey]) => (
            <button
              key={key}
              type="button"
              className={`type-label h-8 rounded-sm px-3 ${
                html && value === html
                  ? 'bg-brand-primary-50 text-brand-primary-700'
                  : 'text-text-secondary hover:bg-bg-subtle'
              }`}
              onClick={() => askPreset(html)}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
      ) : null}
      <div className="signature-editor overflow-hidden rounded-md border border-border-default bg-bg-canvas">
        <div
          className="flex h-10 items-center gap-0.5 border-b border-border-default bg-bg-subtle px-1.5"
          onMouseDown={(event) => {
            const target = event.target as HTMLElement;
            if (target.closest('select, input, textarea, option')) return;
            event.preventDefault();
          }}
        >
          <IconButton label={t('settings.signature.bold')} onClick={onBold}>
            <Bold size={16} />
          </IconButton>
          <IconButton label={t('settings.signature.italic')} onClick={onItalic}>
            <Italic size={16} />
          </IconButton>
          <IconButton label={t('settings.signature.underline')} onClick={onUnderline}>
            <Underline size={16} />
          </IconButton>
          <span className="mx-1 h-5 w-px bg-border-default" />
          <IconButton label={t('settings.signature.alignLeft')} onClick={() => onAlign('left')}>
            <AlignLeft size={16} />
          </IconButton>
          <IconButton label={t('settings.signature.alignCenter')} onClick={() => onAlign('center')}>
            <AlignCenter size={16} />
          </IconButton>
          <IconButton label={t('settings.signature.alignRight')} onClick={() => onAlign('right')}>
            <AlignRight size={16} />
          </IconButton>
          <span className="mx-1 h-5 w-px bg-border-default" />
          <select
            aria-label={t('settings.signature.font')}
            className="type-label h-8 w-[110px] rounded-sm border border-border-default bg-bg-canvas px-1"
            defaultValue="Arial"
            onMouseDown={remember}
            onChange={(event) => onFont(event.target.value)}
          >
            {FONTS.map((font) => (
              <option key={font} value={font}>
                {font}
              </option>
            ))}
          </select>
          <select
            aria-label={t('settings.signature.size')}
            className="type-label h-8 w-16 rounded-sm border border-border-default bg-bg-canvas px-1"
            defaultValue="13"
            onMouseDown={remember}
            onChange={(event) => onSize(event.target.value)}
          >
            {SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
          <span className="relative">
            <IconButton label={t('settings.signature.color')} onClick={() => setColorOpen((open) => !open)}>
              <Palette size={16} />
            </IconButton>
            {colorOpen ? (
              <div className="absolute left-0 top-8 z-10 flex flex-col gap-2 rounded-md border border-border-default bg-bg-canvas p-2 shadow-e2">
                <label className="type-caption flex items-center gap-2 text-text-secondary">
                  <Baseline size={14} />
                  {t('settings.signature.color')}
                  <input
                    type="color"
                    aria-label={t('settings.signature.color')}
                    value={textColor || undefined}
                    onChange={(event) => {
                      setTextColor(event.target.value);
                      onColor('color', event.target.value);
                    }}
                  />
                </label>
                <label className="type-caption flex items-center gap-2 text-text-secondary">
                  {t('settings.signature.background')}
                  <input
                    type="color"
                    aria-label={t('settings.signature.background')}
                    value={backColor || undefined}
                    onChange={(event) => {
                      setBackColor(event.target.value);
                      onColor('backgroundColor', event.target.value);
                    }}
                  />
                </label>
              </div>
            ) : null}
          </span>
          <IconButton label={t('settings.signature.link')} onClick={() => setLinkOpen(true)}>
            <Link2 size={16} />
          </IconButton>
          <IconButton
            label={t('settings.signature.table')}
            onClick={() =>
              insertHtml(
                '<table style="border-collapse:collapse"><tr><td style="padding:6px;border:1px solid var(--border-strong)">&nbsp;</td><td style="padding:6px;border:1px solid var(--border-strong)">&nbsp;</td></tr></table>',
              )
            }
          >
            <Table size={16} />
          </IconButton>
          <IconButton
            label={t('settings.signature.image')}
            onClick={() => {
              setImageError('');
              setImageOpen(true);
            }}
          >
            <ImageIcon size={16} />
          </IconButton>
          <IconButton
            label={t('settings.signature.rule')}
            onClick={() => {
              if (editor && docIsRaw(editor)) runRaw(() => document.execCommand('insertHorizontalRule'));
              else editor?.chain().focus().setHorizontalRule().run();
            }}
          >
            <Minus size={16} />
          </IconButton>
          <span className="relative">
            <IconButton label={t('settings.signature.special')} onClick={() => setSpecialOpen((open) => !open)}>
              <Omega size={16} />
            </IconButton>
            {specialOpen ? (
              <div className="absolute left-0 top-8 z-10 grid w-56 grid-cols-8 gap-1 rounded-md border border-border-default bg-bg-canvas p-2 shadow-e2">
                {SPECIAL.map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    className="type-body flex h-7 items-center justify-center rounded-sm hover:bg-bg-subtle"
                    onClick={() => {
                      insertText(ch);
                      setSpecialOpen(false);
                    }}
                  >
                    {ch}
                  </button>
                ))}
              </div>
            ) : null}
          </span>
          <button
            type="button"
            className="type-label ml-auto inline-flex h-8 items-center gap-1 px-2 text-brand-primary-600"
            onClick={openSource}
          >
            <Code size={16} />
            {t('settings.signature.source')}
          </button>
        </div>
        <EditorContent editor={editor} />
      </div>
      {footer === 'signature' ? (
        <p className={`type-caption ${bytes > maxBytes ? 'text-danger-600' : 'text-text-tertiary'}`}>
          {t('settings.signature.footer', { size: formatSignatureSize(bytes), images: imagePhrase })}
        </p>
      ) : (
        <p className="type-caption text-text-tertiary">{t('settings.signature.responseHint')}</p>
      )}
      {stripped && stripped.length > 0 ? (
        <Banner kind="warning" message={t('settings.signature.stripped', { parts: stripped.join(', ') })} />
      ) : null}
      {variables ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1">
            {SIGNATURE_VARIABLES.map((name) => (
              <button
                key={name}
                type="button"
                className="type-caption rounded-full border border-border-default bg-bg-subtle px-2 py-1 text-text-secondary hover:bg-bg-muted"
                onClick={() => insertText(`{${name}}`)}
              >
                {`{${name}}`}
              </button>
            ))}
          </div>
          <p className="type-caption text-text-tertiary">{t('settings.signature.emptyVars')}</p>
        </div>
      ) : null}

      {sourceOpen ? (
        <Dialog
          title={t('settings.signature.source')}
          width={640}
          onClose={() => setSourceOpen(false)}
          onSubmit={commitSource}
          footer={
            <>
              <Button variant="secondary" onClick={() => setSourceOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit">{t('settings.signature.insert')}</Button>
            </>
          }
        >
          <div className="relative max-h-[360px] overflow-auto rounded-md border border-border-default bg-bg-subtle">
            <pre
              aria-hidden
              className="pointer-events-none m-0 min-h-[280px] whitespace-pre-wrap break-words p-3 font-mono text-[13px] leading-5"
              dangerouslySetInnerHTML={{ __html: `${highlightHtml(sourceDraft)}\n` }}
            />
            <textarea
              value={sourceDraft}
              onChange={(event) => setSourceDraft(event.target.value)}
              aria-label={t('settings.signature.source')}
              spellCheck={false}
              data-autofocus
              className="absolute inset-0 h-full min-h-[280px] w-full resize-none bg-transparent p-3 font-mono text-[13px] leading-5 text-transparent caret-[var(--text-primary)] outline-none"
            />
          </div>
        </Dialog>
      ) : null}

      {linkOpen ? (
        <Dialog
          title={t('settings.signature.link')}
          width={420}
          onClose={() => setLinkOpen(false)}
          onSubmit={applyLink}
          footer={
            <>
              <Button variant="secondary" onClick={() => setLinkOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit">{t('settings.signature.insert')}</Button>
            </>
          }
        >
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.signature.linkUrl')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={linkUrl}
              data-autofocus
              onChange={(event) => setLinkUrl(event.target.value)}
            />
          </label>
        </Dialog>
      ) : null}

      {imageOpen ? (
        <Dialog
          title={t('settings.signature.image')}
          width={440}
          onClose={() => setImageOpen(false)}
          onSubmit={() => {
            if (imageTab === 'url' && imageUrl.startsWith('https://')) insertImage(imageUrl.trim());
          }}
          footer={
            <>
              <Button variant="secondary" onClick={() => setImageOpen(false)}>
                {t('common.cancel')}
              </Button>
              {imageTab === 'url' ? <Button type="submit">{t('settings.signature.insert')}</Button> : null}
            </>
          }
        >
          <div className="flex gap-1">
            <button
              type="button"
              className={`type-label h-8 rounded-sm px-3 ${imageTab === 'file' ? 'bg-brand-primary-50 text-brand-primary-700' : ''}`}
              onClick={() => setImageTab('file')}
            >
              {t('settings.signature.uploadTab')}
            </button>
            <button
              type="button"
              className={`type-label h-8 rounded-sm px-3 ${imageTab === 'url' ? 'bg-brand-primary-50 text-brand-primary-700' : ''}`}
              onClick={() => setImageTab('url')}
            >
              {t('settings.signature.urlTab')}
            </button>
          </div>
          {imageTab === 'file' ? (
            <div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/svg+xml,.svg"
                className="type-small"
                onChange={(event) => void onPickFile(event.target.files?.[0])}
              />
              <p className="type-caption mt-1 text-text-tertiary">{t('settings.signature.imageType')}</p>
            </div>
          ) : (
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-secondary">{t('settings.signature.imageUrl')}</span>
              <input
                className="type-body h-9 rounded-sm border border-border-default px-3"
                value={imageUrl}
                onChange={(event) => setImageUrl(event.target.value)}
              />
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.signature.alt')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={imageAlt}
              onChange={(event) => setImageAlt(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.signature.width')}</span>
            <input
              className="type-body h-9 w-24 rounded-sm border border-border-default px-3"
              value={imageWidth}
              onChange={(event) => setImageWidth(event.target.value)}
            />
          </label>
          {imageError ? <Banner kind="warning" message={imageError} /> : null}
        </Dialog>
      ) : null}

      {confirmPreset ? (
        <ConfirmDialog
          title={t('settings.signature.restoreTitle')}
          body={t('settings.signature.restoreBody')}
          confirmLabel={t('settings.signature.restore')}
          onClose={() => setConfirmPreset(null)}
          onConfirm={() => {
            const html = confirmPreset;
            setConfirmPreset(null);
            echo.current = html;
            if (editor) loadSignatureHtml(editor, html);
            onChange(html);
          }}
        />
      ) : null}
    </div>
  );
}

export function SanitizedHtml({ html, className }: { html: string; className?: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: clientSanitize(html) }} />;
}

function cssHex(name: string): string {
  if (typeof document === 'undefined') return '';
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9A-Fa-f]{6}$/.test(value) ? value : '';
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-sm text-text-primary hover:bg-bg-muted"
    >
      {children}
    </button>
  );
}
