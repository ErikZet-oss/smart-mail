type Props = { width: number; className?: string; tone?: 'blue' | 'white' };

/** SMART logo (design/brand/logo-smart*.svg, DECISIONS D16): blue on light pages, white on the rail. Width in px as
 * in the Figma frame; `className` overrides it for responsive widths. */
export function Logo({ width, className, tone = 'blue' }: Props) {
  return (
    <img
      src={tone === 'white' ? '/logo-smart-white.svg' : '/logo-smart.svg'}
      alt="SMART"
      width={width}
      className={`h-auto ${className ?? ''}`}
      style={className ? undefined : { width }}
    />
  );
}
