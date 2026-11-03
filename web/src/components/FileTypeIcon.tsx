import { FILE_TYPE_LABEL, type FileType } from './fileType';

type Size = 'sm' | 'md' | 'lg';
const DIM: Record<Size, { w: number; h: number; band: number; font: number }> = {
  sm: { w: 16, h: 20, band: 7, font: 5 },
  md: { w: 26, h: 32, band: 11, font: 8 },
  lg: { w: 32, h: 40, band: 13, font: 10 },
};
const FILL: Record<Exclude<FileType, 'other'>, string> = {
  pdf: 'var(--filetype-pdf)',
  xls: 'var(--filetype-xls)',
  doc: 'var(--filetype-doc)',
  img: 'var(--filetype-img)',
  zip: 'var(--filetype-zip)',
  xml: 'var(--filetype-xml)',
};

/**
 * Figma `FileTypeIcon` (`199:94925`, #205): a sheet with a folded corner and a coloured band with the type label.
 * Decorative (`aria-hidden`); the type is spelled out in the attachment's own label. Colours only from tokens.
 */
export function FileTypeIcon({ type, size = 'sm' }: { type: FileType; size?: Size }) {
  const { w, h, band, font } = DIM[size];
  const fold = Math.round(w * 0.3);
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-hidden="true"
      className="shrink-0"
      data-file-type={type}
      data-testid="file-type-icon"
    >
      <path
        d={`M0.5 1.5a1 1 0 0 1 1-1H${w - fold - 0.5}L${w - 0.5} ${fold + 0.5}V${h - 1.5}a1 1 0 0 1-1 1H1.5a1 1 0 0 1-1-1Z`}
        fill="var(--bg-canvas)"
        stroke="var(--border-strong)"
      />
      <path
        d={`M${w - fold - 0.5} 0.5V${fold - 0.5}a1 1 0 0 0 1 1H${w - 0.5}`}
        fill="none"
        stroke="var(--border-strong)"
      />
      {type === 'other' ? (
        <path
          d={`M${w * 0.3} ${h * 0.5}H${w * 0.7}M${w * 0.3} ${h * 0.65}H${w * 0.7}M${w * 0.3} ${h * 0.8}H${w * 0.55}`}
          stroke="var(--text-secondary)"
          strokeWidth={size === 'sm' ? 1 : 1.5}
          strokeLinecap="round"
        />
      ) : (
        <>
          <rect
            x={0}
            y={h - band - Math.round(h * 0.2)}
            width={w - Math.round(w * 0.12)}
            height={band}
            rx={1}
            fill={FILL[type]}
          />
          <text
            x={(w - Math.round(w * 0.12)) / 2}
            y={h - Math.round(h * 0.2) - band / 2}
            dominantBaseline="central"
            textAnchor="middle"
            fontFamily="var(--font-ui)"
            fontWeight={700}
            fontSize={font}
            fill="var(--text-on-primary)"
          >
            {FILE_TYPE_LABEL[type]}
          </text>
        </>
      )}
    </svg>
  );
}
