import type { Editor } from '@tiptap/react';
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Image as ImageIcon,
  Italic,
  Link2,
  List,
  Quote,
  RemoveFormatting,
  Table,
  Underline as UnderlineIcon,
} from 'lucide-react';
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

const SWATCHES = [
  { token: '--text-primary', label: 'compose.swatchText' },
  { token: '--brand-primary-600', label: 'compose.swatchBrand' },
  { token: '--text-secondary', label: 'compose.swatchMuted' },
] as const;

function cssHex(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9A-Fa-f]{6}$/.test(value) ? value : '';
}

function IconButton({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`rounded-sm p-2 text-text-primary hover:bg-bg-canvas ${pressed ? 'bg-bg-canvas' : ''}`}
      aria-label={label}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

type Props = {
  editor: Editor | null;
  onInlineImage: (file: File) => void;
};

/** W4 editor toolbar. Marks round-trip through TipTap; the signature stays a separate atom. */
export function ComposeToolbar({ editor, onInlineImage }: Props) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState('https://');
  const [colorOpen, setColorOpen] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-border-default bg-bg-subtle px-2 py-1">
      <IconButton
        label={t('settings.signature.bold')}
        pressed={editor?.isActive('bold')}
        onClick={() => editor?.chain().focus().toggleBold().run()}
      >
        <Bold size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.italic')}
        pressed={editor?.isActive('italic')}
        onClick={() => editor?.chain().focus().toggleItalic().run()}
      >
        <Italic size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.underline')}
        pressed={editor?.isActive('underline')}
        onClick={() => editor?.chain().focus().toggleUnderline().run()}
      >
        <UnderlineIcon size={16} />
      </IconButton>
      <IconButton
        label={t('compose.blockquote')}
        pressed={editor?.isActive('blockquote')}
        onClick={() => editor?.chain().focus().toggleBlockquote().run()}
      >
        <Quote size={16} />
      </IconButton>
      <IconButton
        label={t('compose.bulletList')}
        pressed={editor?.isActive('bulletList')}
        onClick={() => editor?.chain().focus().toggleBulletList().run()}
      >
        <List size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.alignLeft')}
        onClick={() => editor?.chain().focus().setTextAlign('left').run()}
      >
        <AlignLeft size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.alignCenter')}
        onClick={() => editor?.chain().focus().setTextAlign('center').run()}
      >
        <AlignCenter size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.alignRight')}
        onClick={() => editor?.chain().focus().setTextAlign('right').run()}
      >
        <AlignRight size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.color')}
        pressed={colorOpen}
        onClick={() => setColorOpen((open) => !open)}
      >
        <Baseline size={16} />
      </IconButton>
      {colorOpen ? (
        <span className="flex items-center gap-1 px-1" role="group" aria-label={t('settings.signature.color')}>
          {SWATCHES.map((swatch) => (
            <button
              key={swatch.token}
              type="button"
              className="size-5 rounded-sm border border-border-default"
              style={{ background: `var(${swatch.token})` }}
              aria-label={t(swatch.label)}
              onClick={() => {
                const hex = cssHex(swatch.token);
                if (hex) editor?.chain().focus().setColor(hex).run();
                setColorOpen(false);
              }}
            />
          ))}
        </span>
      ) : null}
      <IconButton label={t('settings.signature.link')} pressed={linkOpen} onClick={() => setLinkOpen((open) => !open)}>
        <Link2 size={16} />
      </IconButton>
      <IconButton
        label={t('settings.signature.table')}
        onClick={() => editor?.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: false }).run()}
      >
        <Table size={16} />
      </IconButton>
      <IconButton label={t('settings.signature.image')} onClick={() => fileRef.current?.click()}>
        <ImageIcon size={16} />
      </IconButton>
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/gif"
        className="sr-only"
        aria-label={t('settings.signature.image')}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) onInlineImage(file);
        }}
      />
      <IconButton label={t('compose.clearFormat')} onClick={() => editor?.chain().focus().unsetAllMarks().run()}>
        <RemoveFormatting size={16} />
      </IconButton>
      {linkOpen ? (
        <form
          className="flex items-center gap-1 px-1"
          onSubmit={(event) => {
            event.preventDefault();
            const href = linkUrl.trim();
            if (href) editor?.chain().focus().extendMarkRange('link').setLink({ href }).run();
            setLinkOpen(false);
          }}
        >
          <input
            value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)}
            aria-label={t('settings.signature.linkUrl')}
            className="type-small h-8 w-48 rounded-sm border border-border-default bg-bg-canvas px-2 text-text-primary"
          />
          <button type="submit" className="type-small rounded-sm px-2 text-brand-primary-700">
            {t('settings.signature.insert')}
          </button>
        </form>
      ) : null}
    </div>
  );
}
