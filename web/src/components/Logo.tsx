/** Blue SMART logo (design/brand/logo-smart.svg, DECISIONS D16). Width in px as in the Figma frame; `className`
 * overrides it for responsive widths. */
export function Logo({ width, className }: { width: number; className?: string }) {
  return (
    <img
      src="/logo-smart.svg"
      alt="SMART"
      width={width}
      className={`h-auto ${className ?? ''}`}
      style={className ? undefined : { width }}
    />
  );
}
