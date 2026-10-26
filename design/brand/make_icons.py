"""Generate logo PNGs and the PWA/app icon set from the vector logo (DECISIONS D16)."""
import re, sys
from pathlib import Path
import cairosvg

src = Path(sys.argv[1]); out = Path(sys.argv[2])
svg = src.read_text()
d = re.search(r' d="([^"]+)"', svg).group(1)
vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
BLUE = "#0F75BC"

def logo_svg(color):
    return f'<path fill="{color}" fill-rule="evenodd" d="{d}"/>'

def square(size, bg, logo_w_ratio, radius_ratio, color="#FFFFFF"):
    # place the logo centred in a square canvas of 1000 units
    lw = 1000 * logo_w_ratio
    sc = lw / vb[2]
    lh = vb[3] * sc
    tx = (1000 - lw) / 2 - vb[0] * sc
    ty = (1000 - lh) / 2 - vb[1] * sc
    r = 1000 * radius_ratio
    bgel = f'<rect width="1000" height="1000" rx="{r}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="{size}" height="{size}">{bgel}'
            f'<g transform="translate({tx:.2f} {ty:.2f}) scale({sc:.5f})">{logo_svg(color)}</g></svg>')

def s_mark(size, bg, radius_ratio):
    # only the first letter "S" (with the start of the top bar) for very small sizes (favicon)
    cx0, cy0, cw, ch = 58.0, 173.0, 97.0, 187.0   # bounds of the letter S measured from the vector
    sc = 720 / max(cw, ch)
    w, h = cw * sc, ch * sc
    ox, oy = (1000 - w) / 2, (1000 - h) / 2
    tx, ty = ox - cx0 * sc, oy - cy0 * sc
    r = 1000 * radius_ratio
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="{size}" height="{size}">'
            f'<rect width="1000" height="1000" rx="{r}" fill="{bg}"/><clipPath id="c"><rect x="{ox:.1f}" y="{oy:.1f}" width="{w:.1f}" height="{h:.1f}"/></clipPath>'
            f'<g clip-path="url(#c)"><g transform="translate({tx:.2f} {ty:.2f}) scale({sc:.5f})">{logo_svg("#FFFFFF")}</g></g></svg>')


files = {
    "app-icon/icon-512.png": (square(512, BLUE, 0.78, 0.22), 512),
    "app-icon/icon-192.png": (square(192, BLUE, 0.78, 0.22), 192),
    "app-icon/icon-maskable-512.png": (square(512, BLUE, 0.64, 0.0), 512),
    "app-icon/apple-touch-icon-180.png": (square(180, BLUE, 0.78, 0.0), 180),
    "app-icon/favicon-32.png": (s_mark(32, BLUE, 0.2), 32),
    "app-icon/favicon-16.png": (s_mark(16, BLUE, 0.2), 16),
}
for name, (sv, size) in files.items():
    cairosvg.svg2png(bytestring=sv.encode(), write_to=str(out / name), output_width=size, output_height=size)
(out / "app-icon/icon.svg").write_text(square(512, BLUE, 0.78, 0.22))
(out / "app-icon/favicon.svg").write_text(s_mark(32, BLUE, 0.2))
# logo PNGs from the vector (2× of the old raster)
for color, name in [(BLUE, "logo-smart.png"), ("#FFFFFF", "logo-smart-white.png")]:
    w = 1200; h = round(w * vb[3] / vb[2])
    sv = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(map(str, vb))}" width="{w}" height="{h}">{logo_svg(color)}</svg>'
    cairosvg.svg2png(bytestring=sv.encode(), write_to=str(out / name), output_width=w, output_height=h)
print("ok")
