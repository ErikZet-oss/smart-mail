"""Single source of the Smart Mail design tokens.

Run:  python design/build_tokens.py
Writes design/tokens.json (W3C design-tokens format, importable into Figma with Tokens Studio or a variables-import
plugin), design/tokens.css (CSS custom properties for web/src/styles/tokens.css, light + dark) and design/CONTRAST.md
(WCAG contrast of every text/background pair that the UI uses). UX_SPEC.md §2 shows the same values; change them here
and copy the printed tables into UX_SPEC (the script fails when a required contrast is not met).
"""
from __future__ import annotations

import colorsys
import json
from pathlib import Path

HERE = Path(__file__).parent

# ------------------------------------------------------------------ colours: (light, dark, use)
COLOR: dict[str, tuple[str, str, str]] = {
    "bg/canvas": ("#FFFFFF", "#0F141B", "reading pane, cards, inputs"),
    "bg/subtle": ("#F6F8FA", "#151B24", "folder column, list header, read-only fields"),
    "bg/muted": ("#EEF1F5", "#1C2430", "hover rows, neutral chips"),
    "bg/rail": ("#1F2937", "#0B0F15", "left rail (dark, like Roundcube Elastic)"),
    "bg/rail-active": ("#2B3A50", "#1A2433", "active rail item"),
    "bg/overlay": ("#0F141B7A", "#000000A0", "scrim behind dialogs, drawers, lightbox"),
    "border/default": ("#DFE3EA", "#2A3442", "dividers, inputs"),
    "border/strong": ("#C6CEDA", "#3A4656", "focused containers, table header lines"),
    "text/primary": ("#1B2430", "#E6EAF0", "body text"),
    "text/secondary": ("#5B6576", "#A7B1C2", "meta, labels, placeholders"),
    "text/tertiary": ("#6E7787", "#8590A2", "disabled text, hints (still AA)"),
    "text/on-rail": ("#C9D2E0", "#A7B1C2", "rail labels"),
    "text/on-rail-active": ("#FFFFFF", "#FFFFFF", "active rail label"),
    "text/on-primary": ("#FFFFFF", "#0B1220", "text on primary buttons"),
    "brand/logo": ("#0F75BC", "#0F75BC", "logo colour (DECISIONS D16) — logo only"),
    "brand/primary-700": ("#0B5E98", "#7DBEF5", "primary hover / pressed"),
    "brand/primary-600": ("#0F75BC", "#4AA3F0", "primary buttons, links (= logo blue)"),
    "brand/primary-500": ("#2A8FDB", "#3B95E3", "focus ring (≥ 3:1 on canvas)"),
    "brand/primary-400": ("#5AB0EC", "#2E7FC4", "selection bar, decorative accents"),
    "brand/primary-100": ("#D4E8F7", "#16324C", "selected chips, progress track"),
    "brand/primary-50": ("#EAF4FB", "#12263A", "selected row background, info banner"),
    "ai/600": ("#5B4CDB", "#A99CFF", "AI text and icons — only for AI"),
    "ai/200": ("#CFC7FA", "#3B3470", "AI borders"),
    "ai/50": ("#F3F1FE", "#1D1A33", "AI card background"),
    "success/600": ("#237A35", "#51CF66", "checks ok, success text and icons"),
    "success/50": ("#EBF7EE", "#0F2A17", "success background"),
    "warning/700": ("#8A5A00", "#FFC34D", "warning text"),
    "warning/600": ("#B57800", "#F0B030", "warning icons (≥ 3:1)"),
    "warning/400": ("#E0A020", "#8A6510", "warning borders, decorative"),
    "warning/50": ("#FFF8E6", "#2B2210", "warning background"),
    "danger/600": ("#C92A2A", "#FF6B6B", "blocking, destructive, errors"),
    "danger/50": ("#FFF1F1", "#2E1416", "danger background"),
    "money/band": ("#D6E3F2", "#D6E3F2", "print documents only: band and table header (DOCUMENTS_SPEC §4.2)"),
    "money/box-border": ("#CECECE", "#CECECE", "print documents only: rounded boxes"),
}
CATEGORIES: dict[str, tuple[str, str]] = {  # key: (light, SK label); dark = +10 % lightness
    "inquiry": ("#E8590C", "Dopyty"),
    "order": ("#2B8A3E", "Objednávky"),
    "invoice_request": ("#1C7ED6", "Žiadosti o faktúru"),
    "supplier_document": ("#C2255C", "Doklady dodávateľov"),
    "complaint": ("#E03131", "Reklamácie"),
    "shipping": ("#0C8599", "Doprava"),
    "payment": ("#66A80F", "Platby"),
    "document_request": ("#F08C00", "Žiadosti o dokument"),
    "supplier_info": ("#364FC7", "Dodávatelia – info (indigo, deliberately not violet = AI)"),
    "feed": ("#868E96", "Feed"),
}

# ------------------------------------------------------------------ typography (Inter; tabular numbers for amounts)
FONT = {"ui": "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        "mono": "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace",
        "print": "'Arial Narrow', 'Liberation Sans Narrow', Arial, sans-serif",
        "email": "Arial, Helvetica, sans-serif"}
TYPE = {  # name: (size, line height, weight, letter spacing em, use)
    "display": (28, 34, 700, 0, "Dnes greeting"),
    "title": (20, 26, 700, 0, "page and message subject"),
    "heading": (16, 22, 600, 0, "section and card titles, PersonTile name"),
    "body-lg": (15, 23, 400, 0, "message body"),
    "body": (14, 20, 400, 0, "default UI"),
    "body-strong": (14, 20, 600, 0, "sender (unread), emphasis"),
    "label": (13, 18, 600, 0, "form labels, table headers"),
    "small": (13, 18, 400, 0, "list secondary lines, table cells"),
    "caption": (12, 16, 500, 0, "meta, timestamps, chip text, help text"),
    "micro": (11, 14, 600, 0.06, "toolbar labels under icons, uppercase section labels"),
}
SPACE = [2, 4, 8, 12, 16, 20, 24, 32, 40, 48]
RADIUS = {"xs": 4, "sm": 6, "md": 8, "lg": 12, "full": 9999}
ELEVATION = {"e1": "0 1px 2px rgba(16,24,40,.06)", "e2": "0 8px 24px rgba(16,24,40,.12)",
             "e3": "0 20px 48px rgba(16,24,40,.20)"}
LAYOUT = {"rail": 72, "folders": 232, "list": 360, "list-min": 300, "list-max": 520, "reading-min": 560,
          "assistant": 380, "compose-ai": 320, "topbar": 56, "appbar": 56, "bottomnav": 64, "settings-nav": 248,
          "settings-list": 280, "settings-form-max": 760, "drawer": 480, "today-max": 1100}
SIZE = {  # component sizes (px) — UX_SPEC §2.6
    "button-sm": 28, "button-md": 32, "button-lg": 40, "input": 36, "input-sm": 32, "toolbar": 56,
    "toolbar-button-w": 56, "rail-item": 56, "compose-fab": 44, "row-compact": 52, "row-comfortable": 84,
    "row-mobile": 72, "folder-item": 32, "category-item": 30, "tab": 40, "chip": 24, "chip-sm": 20, "badge": 18,
    "table-header": 36, "table-row": 40, "money-field": 28, "money-row": 24, "menu-item": 32, "check-row": 28,
    "dialog-sm": 400, "dialog-md": 560, "dialog-lg": 720, "toast-max": 360, "popover-min": 240,
    "fab-mobile": 56, "touch-min": 44, "focus-ring": 2, "focus-offset": 2,
}
MOTION = {"hover": "120ms", "panel": "180ms ease-out", "toast": "200ms", "row-remove": "160ms"}

# ------------------------------------------------------------------ contrast requirements (fg, bg, min, why)
PAIRS = [
    ("text/primary", "bg/canvas", 4.5, "body text"),
    ("text/secondary", "bg/canvas", 4.5, "meta text"),
    ("text/secondary", "bg/subtle", 4.5, "meta text on folder column"),
    ("text/tertiary", "bg/canvas", 4.5, "hints"),
    ("text/on-rail", "bg/rail", 4.5, "rail labels"),
    ("text/on-rail-active", "bg/rail-active", 4.5, "active rail label"),
    ("brand/primary-600", "bg/canvas", 4.5, "links"),
    ("text/on-primary", "brand/primary-600", 4.5, "primary button label"),
    ("text/on-primary", "brand/primary-700", 4.5, "primary button hover"),
    ("brand/primary-500", "bg/canvas", 3.0, "focus ring"),
    ("text/primary", "brand/primary-50", 4.5, "selected row"),
    ("ai/600", "bg/canvas", 4.5, "AI text"),
    ("ai/600", "ai/50", 4.5, "AI text on AI card"),
    ("success/600", "bg/canvas", 4.5, "ok text"),
    ("success/600", "success/50", 4.5, "ok chip"),
    ("warning/700", "warning/50", 4.5, "warning text"),
    ("warning/600", "bg/canvas", 3.0, "warning icon"),
    ("danger/600", "bg/canvas", 4.5, "error text"),
    ("danger/600", "danger/50", 4.5, "error chip"),
]


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")[:6]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def lum(h: str) -> float:
    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def lighten(h: str, d: float = 0.10) -> str:
    r, g, b = _rgb(h)
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(hh, min(1.0, ll + d), ss)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def build() -> None:
    light = {k: v[0] for k, v in COLOR.items()}
    dark = {k: v[1] for k, v in COLOR.items()}
    for k, (c, _) in CATEGORIES.items():
        light[f"cat/{k}"] = c
        dark[f"cat/{k}"] = lighten(c)

    # contrast report (fails the build when a requirement is not met)
    rows, bad = [], []
    for mode, pal in (("light", light), ("dark", dark)):
        for fg, bg, need, why in PAIRS:
            r = contrast(pal[fg], pal[bg])
            ok = r >= need
            rows.append(f"| {mode} | `{fg}` {pal[fg]} | `{bg}` {pal[bg][:7]} | {r:.2f} | {need} | {'✓' if ok else '✗'} | {why} |")
            if not ok:
                bad.append(f"{mode} {fg} on {bg}: {r:.2f} < {need}")
    (HERE / "CONTRAST.md").write_text(
        "# CONTRAST.md — WCAG 2.2 contrast of the token pairs (generated by build_tokens.py)\n\n"
        "| Mode | Foreground | Background | Ratio | Min | OK | Use |\n|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    if bad:
        raise SystemExit("contrast failures:\n" + "\n".join(bad))

    def tok(v, t, d=None):
        o = {"$value": v, "$type": t}
        if d:
            o["$description"] = d
        return o

    doc: dict = {"$description": "Smart Mail design tokens v2.7 — generated by design/build_tokens.py; UX_SPEC §2",
                 "color": {"light": {}, "dark": {}}, "font": {}, "type": {}, "space": {}, "radius": {},
                 "shadow": {}, "layout": {}, "size": {}, "motion": {}}
    for mode, pal in (("light", light), ("dark", dark)):
        for k, v in pal.items():
            grp, name = k.split("/")
            use = COLOR[k][2] if k in COLOR else CATEGORIES[name][1]
            doc["color"][mode].setdefault(grp, {})[name] = tok(v, "color", use)
    for k, v in FONT.items():
        doc["font"][k] = tok(v, "fontFamily")
    for k, (sz, lh, w, ls, use) in TYPE.items():
        doc["type"][k] = tok({"fontFamily": "{font.ui}", "fontSize": f"{sz}px", "lineHeight": f"{lh}px",
                              "fontWeight": w, "letterSpacing": f"{ls}em"}, "typography", use)
    for v in SPACE:
        doc["space"][str(v)] = tok(f"{v}px", "dimension")
    for k, v in RADIUS.items():
        doc["radius"][k] = tok(f"{v}px", "dimension")
    for k, v in ELEVATION.items():
        doc["shadow"][k] = tok(v, "shadow")
    for k, v in LAYOUT.items():
        doc["layout"][k] = tok(f"{v}px", "dimension")
    for k, v in SIZE.items():
        doc["size"][k] = tok(f"{v}px", "dimension")
    for k, v in MOTION.items():
        doc["motion"][k] = tok(v, "duration")
    (HERE / "tokens.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def var(k: str) -> str:
        return "--" + k.replace("/", "-")

    css = ["/* Smart Mail design tokens v2.7 — generated by design/build_tokens.py (do not edit by hand) */", ":root {"]
    css += [f"  {var(k)}: {v};" for k, v in light.items()]
    css += [f"  --font-{k}: {v};" for k, v in FONT.items()]
    for k, (sz, lh, w, ls, _) in TYPE.items():
        css.append(f"  --type-{k}: {w} {sz}px/{lh}px var(--font-ui);")
        if ls:
            css.append(f"  --type-{k}-tracking: {ls}em;")
    css += [f"  --space-{v}: {v}px;" for v in SPACE]
    css += [f"  --radius-{k}: {v}px;" for k, v in RADIUS.items()]
    css += [f"  --shadow-{k}: {v};" for k, v in ELEVATION.items()]
    css += [f"  --layout-{k}: {v}px;" for k, v in LAYOUT.items()]
    css += [f"  --size-{k}: {v}px;" for k, v in SIZE.items()]
    css += [f"  --motion-{k}: {v};" for k, v in MOTION.items()]
    css += ["}", "", "[data-theme='dark'] {"]
    css += [f"  {var(k)}: {v};" for k, v in dark.items()]
    css += ["}", "", "@media (prefers-color-scheme: dark) {", "  :root:not([data-theme='light']) {"]
    css += [f"    {var(k)}: {v};" for k, v in dark.items()]
    css += ["  }", "}", "", "@media (prefers-reduced-motion: reduce) {", "  :root { --motion-panel: 0ms; --motion-row-remove: 0ms; }", "}", ""]
    (HERE / "tokens.css").write_text("\n".join(css), encoding="utf-8")

    # markdown tables for UX_SPEC §2.1/2.2 (printed)
    print("| Token | Light | Dark | Use |\n|---|---|---|---|")
    for k in light:
        use = COLOR[k][2] if k in COLOR else CATEGORIES[k.split('/')[1]][1]
        print(f"| `{k}` | {light[k]} | {dark[k]} | {use} |")


if __name__ == "__main__":
    build()
