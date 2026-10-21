#!/usr/bin/env python3
"""
Profile README builder.

    tools/content.json  ->  assets/*.svg  +  README.md

GitHub strips CSS from README markup, so every section is rendered as an SVG.
All text is converted to glyph outlines (Inter, tools/fonts) so it looks the
same in every browser and does not depend on fonts installed on the viewer's
machine. Edit content.json and run:

    pip install -r tools/requirements.txt
    python tools/build.py

Optional: put real screenshots into tools/screens/<project-key>.png (or .jpg)
and they replace the drawn mockups inside the project cards.
"""
from __future__ import annotations

import base64
import html
import json
import math
import pathlib
import sys

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
ASSETS = ROOT / "assets"
SCREENS = TOOLS / "screens"

# ----------------------------------------------------------------------------
# design tokens
# ----------------------------------------------------------------------------
W = 1000            # every row is 1000 units wide
GAP = 16            # gap between cards
R = 22              # card radius
SCALE = 0.996       # rows are rendered at 99.6% so inline images never wrap

INK = "#f3f2f7"          # primary text
INK_2 = "#c9c8d4"        # secondary
INK_3 = "#a3a2b2"        # body copy
INK_4 = "#8d8c9c"        # muted
OUTSIDE = "#8b8a99"      # text that sits on the GitHub page itself (light + dark)
LAV = "#b9a4f8"          # accent
LAV_HI = "#d9cbff"
GREEN = "#34d399"

FONT_FILES = {
    "dsb": "InterDisplay-SemiBold.otf",
    "dmd": "InterDisplay-Medium.otf",
    "drg": "InterDisplay-Regular.otf",
    "dlt": "InterDisplay-Light.otf",
    "lt": "Inter-Light.otf",
    "rg": "Inter-Regular.otf",
    "md": "Inter-Medium.otf",
    "sb": "Inter-SemiBold.otf",
}

BODY = "#b4b3c1"         # larger body copy in about / experience / education


def mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def brand(c: str | None) -> str:
    """Brand colour usable on a dark card: pure-black brands become white."""
    if not c:
        return "#ffffff"
    c = c if c.startswith("#") else "#" + c
    return "#ffffff" if c.lower() in ("#000", "#000000") else c


def fmt(v: float) -> str:
    if isinstance(v, int):
        return str(v)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ----------------------------------------------------------------------------
# fonts: shaping with HarfBuzz (kerning), outlines with fontTools
# ----------------------------------------------------------------------------
class Font:
    def __init__(self, key: str, path: pathlib.Path):
        self.key = key
        self.tt = TTFont(str(path))
        self.upm = self.tt["head"].unitsPerEm
        self.order = self.tt.getGlyphOrder()
        self.gs = self.tt.getGlyphSet()
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        self._d: dict[int, str] = {}

    def shape(self, text: str):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True, "calt": True})
        return [(i.codepoint, p.x_advance, p.x_offset, p.y_offset)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def outline(self, gid: int) -> str:
        if gid not in self._d:
            pen = SVGPathPen(self.gs, ntos=lambda v: "%d" % round(v))
            self.gs[self.order[gid]].draw(pen)
            self._d[gid] = pen.getCommands()
        return self._d[gid]

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        g = self.shape(text)
        if not g:
            return 0.0
        units = sum(a for _, a, _, _ in g) + tracking * self.upm * (len(g) - 1)
        return units * size / self.upm

    def wrap(self, text: str, size: float, max_w: float) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if cur and self.width(t, size) > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            lines.append(cur)
        return lines


F = {k: Font(k, TOOLS / "fonts" / v) for k, v in FONT_FILES.items()}


# ----------------------------------------------------------------------------
# tiny SVG document builder
# ----------------------------------------------------------------------------
class SVG:
    def __init__(self, w: float, h: float, title: str):
        self.w, self.h, self.title = w, h, title
        self.defs: list[str] = []
        self.body: list[str] = []
        self.css: list[str] = []
        self.glyphs: dict[str, str] = {}
        self.cache: dict[str, str] = {}
        self.n = 0

    def uid(self, p: str = "i") -> str:
        self.n += 1
        return f"{p}{self.n}"

    def add(self, s: str):
        self.body.append(s)

    # -- paint servers -------------------------------------------------------
    @staticmethod
    def _stops(stops):
        out = []
        for st in stops:
            o, c = st[0], st[1]
            a = st[2] if len(st) > 2 else 1
            op = f' stop-opacity="{fmt(a)}"' if a < 1 else ""
            out.append(f'<stop offset="{fmt(o)}" stop-color="{c}"{op}/>')
        return "".join(out)

    def lin(self, stops, x1=0, y1=0, x2=0, y2=1, units=None, key=None):
        if key and key in self.cache:
            return self.cache[key]
        gid = self.uid("g")
        u = f' gradientUnits="{units}"' if units else ""
        self.defs.append(
            f'<linearGradient id="{gid}" x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" '
            f'y2="{fmt(y2)}"{u}>{self._stops(stops)}</linearGradient>')
        ref = f"url(#{gid})"
        if key:
            self.cache[key] = ref
        return ref

    def rad(self, stops, cx=.5, cy=.5, r=.5, units=None, key=None):
        if key and key in self.cache:
            return self.cache[key]
        gid = self.uid("r")
        u = f' gradientUnits="{units}"' if units else ""
        self.defs.append(
            f'<radialGradient id="{gid}" cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r)}"{u}>'
            f'{self._stops(stops)}</radialGradient>')
        ref = f"url(#{gid})"
        if key:
            self.cache[key] = ref
        return ref

    def blur(self, sd: float) -> str:
        key = f"blur{sd}"
        if key not in self.cache:
            fid = self.uid("f")
            self.defs.append(
                f'<filter id="{fid}" x="-60%" y="-60%" width="220%" height="220%">'
                f'<feGaussianBlur stdDeviation="{fmt(sd)}"/></filter>')
            self.cache[key] = f"url(#{fid})"
        return self.cache[key]

    def clip_rect(self, x, y, w, h, r=0) -> str:
        cid = self.uid("c")
        self.defs.append(
            f'<clipPath id="{cid}"><rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" '
            f'height="{fmt(h)}" rx="{fmt(r)}"/></clipPath>')
        return f"url(#{cid})"

    # -- text ----------------------------------------------------------------
    def _ref(self, font: Font, gid: int) -> str | None:
        d = font.outline(gid)
        if not d:
            return None
        key = f"{font.key}{gid}"
        self.glyphs.setdefault(key, d)
        return key

    def text(self, x, y, s, font: Font, size, fill=INK, tracking=0.0,
             anchor="start", opacity=None, cls=None) -> float:
        g = font.shape(s)
        tr = tracking * font.upm
        width = font.width(s, size, tracking)
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        k = size / font.upm
        uses, pen = [], 0.0
        for gid, adv, dx, dy in g:
            ref = self._ref(font, gid)
            if ref:
                uses.append(f'<use href="#{ref}" x="{fmt(pen + dx)}"' +
                            (f' y="{fmt(dy)}"' if dy else "") + "/>")
            pen += adv + tr
        attrs = f' fill="{fill}"'
        if opacity is not None:
            attrs += f' fill-opacity="{fmt(opacity)}"'
        if cls:
            attrs += f' class="{cls}"'
        self.add(f'<g{attrs} transform="translate({fmt(x)} {fmt(y)}) '
                 f'scale({k:.5f} {-k:.5f})">{"".join(uses)}</g>')
        return width

    def text_grad(self, x, y, s, font: Font, size, stops, tracking=0.0) -> float:
        """Text filled with one continuous gradient (clip-path over a rect)."""
        g = font.shape(s)
        tr = tracking * font.upm
        width = font.width(s, size, tracking)
        k = size / font.upm
        uses, pen = [], 0.0
        for gid, adv, dx, dy in g:
            ref = self._ref(font, gid)
            if ref:
                gx = x + (pen + dx) * k
                uses.append(f'<use href="#{ref}" transform="matrix({k:.5f} 0 0 {-k:.5f} '
                            f'{fmt(gx)} {fmt(y)})"/>')
            pen += adv + tr
        cid = self.uid("c")
        self.defs.append(f'<clipPath id="{cid}">{"".join(uses)}</clipPath>')
        paint = self.lin(stops, x, y - size, x + width, y, units="userSpaceOnUse")
        self.add(f'<rect x="{fmt(x - 2)}" y="{fmt(y - size * 1.05)}" width="{fmt(width + 4)}" '
                 f'height="{fmt(size * 1.35)}" fill="{paint}" clip-path="url(#{cid})"/>')
        return width

    # -- output --------------------------------------------------------------
    def render(self) -> str:
        glyph_defs = "".join(f'<path id="{k}" d="{d}"/>' for k, d in self.glyphs.items())
        css = ("".join(self.css) +
               "@media (prefers-reduced-motion: reduce){*{animation:none!important}}")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(self.w)}" height="{fmt(self.h)}" '
            f'viewBox="0 0 {fmt(self.w)} {fmt(self.h)}" fill="none" role="img" '
            f'aria-label="{html.escape(self.title)}">'
            f'<title>{html.escape(self.title)}</title>'
            f'<style>{css}</style>'
            f'<defs>{glyph_defs}{"".join(self.defs)}</defs>'
            f'{"".join(self.body)}</svg>\n')


# ----------------------------------------------------------------------------
# shared components
# ----------------------------------------------------------------------------
ANIM_CSS = {
    "float": "@keyframes fl{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}"
             ".fa{animation:fl 7s ease-in-out infinite}.fb{animation:fl 8.5s ease-in-out -2.5s infinite}"
             ".fc{animation:fl 9.5s ease-in-out -5s infinite}.fd{animation:fl 6.5s ease-in-out -1s infinite}",
    "twinkle": "@keyframes tw{0%,100%{opacity:.45;transform:scale(.82)}50%{opacity:1;transform:scale(1)}}"
               ".tw{transform-box:fill-box;transform-origin:center;animation:tw 3.2s ease-in-out infinite}",
    "pulse": "@keyframes pu{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(2.8);opacity:0}}"
             ".pu{transform-box:fill-box;transform-origin:center;animation:pu 2.6s ease-out infinite}",
    "breathe": "@keyframes br{0%,100%{opacity:.75}50%{opacity:1}}.br{animation:br 6s ease-in-out infinite}",
    "glint": "@keyframes gl{0%{stroke-dashoffset:520}100%{stroke-dashoffset:-520}}"
             ".gl{stroke-dasharray:70 970;animation:gl 7s linear infinite}"
             ".gl2{stroke-dasharray:50 990;animation:gl 9s linear -3s infinite}",
}


def use_css(s: SVG, *names):
    for n in names:
        if ANIM_CSS[n] not in s.css:
            s.css.append(ANIM_CSS[n])


def card(s: SVG, x, y, w, h, r=R, glow=None):
    s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{fmt(r)}" fill="#0e0e13"/>')
    sheen = s.lin([(0, "#ffffff", .05), (.45, "#ffffff", .012), (1, "#ffffff", 0)], 0, 0, 1, 1, key="sheen")
    s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{fmt(r)}" fill="{sheen}"/>')
    if glow:
        gx, gy, gr, ga = glow
        clip = s.clip_rect(x, y, w, h, r)
        paint = s.rad([(0, "#9b86f0", ga), (1, "#9b86f0", 0)], gx, gy, gr, units="userSpaceOnUse")
        s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{paint}" clip-path="{clip}"/>')
    edge = s.lin([(0, "#ffffff", .17), (.5, "#ffffff", .07), (1, "#ffffff", .05)], 0, 0, 0, 1, key="edge")
    s.add(f'<rect x="{fmt(x + .5)}" y="{fmt(y + .5)}" width="{fmt(w - 1)}" height="{fmt(h - 1)}" '
          f'rx="{fmt(r - .5)}" stroke="{edge}" stroke-width="1"/>')


def label(s: SVG, x, y, t, color="#d9d8e2"):
    s.text(x, y, t.upper(), F["sb"], 13.5, color, tracking=.02)


def tech_tile(s: SVG, x, y, size, n, mono, color, idx):
    c = brand(color)
    light = mix(c, "#ffffff", .5)
    r = 12
    # coloured halo under the tile
    s.add(f'<rect x="{fmt(x + 5)}" y="{fmt(y + 9)}" width="{fmt(size - 10)}" height="{fmt(size - 10)}" rx="10" '
          f'fill="{c}" fill-opacity=".2" filter="{s.blur(7)}"/>')
    s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{size}" height="{size}" rx="{r}" fill="#131319"/>')
    glow = s.rad([(0, c, .5), (.55, c, .12), (1, c, 0)], .16, .06, 1)
    s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{size}" height="{size}" rx="{r}" fill="{glow}"/>')
    sheen = s.lin([(0, "#ffffff", .1), (.5, "#ffffff", .02), (1, "#ffffff", 0)], 0, 0, 0, 1, key="tsheen")
    s.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{size}" height="{size}" rx="{r}" fill="{sheen}"/>')
    rim = s.lin([(0, c, .95), (.45, c, .32), (1, "#ffffff", .07)], 0, 0, 1, 1)
    s.add(f'<rect x="{fmt(x + .55)}" y="{fmt(y + .55)}" width="{fmt(size - 1.1)}" height="{fmt(size - 1.1)}" '
          f'rx="{r - .5}" stroke="{rim}" stroke-width="1.1"/>')
    # specular highlight on the top-right corner (top-left is taken by the index number)
    s.add(f'<path d="M{fmt(x + size - 17)} {fmt(y + 5.5)}Q{fmt(x + size - 5.5)} {fmt(y + 5.5)} {fmt(x + size - 5.5)} {fmt(y + 17)}" '
          f'stroke="#ffffff" stroke-opacity=".6" stroke-width="1.4" stroke-linecap="round"/>')
    # moving glint
    clip = s.clip_rect(x, y, size, size, r)
    band = s.lin([(0, "#ffffff", 0), (.5, "#ffffff", .3), (1, "#ffffff", 0)], 0, 0, 1, 0, key="band")
    s.add(f'<g clip-path="{clip}"><g transform="rotate(22 {fmt(x + size / 2)} {fmt(y + size / 2)})">'
          f'<rect class="gs" style="animation-delay:{fmt(idx * .16)}s" x="{fmt(x - 34)}" y="{fmt(y - 14)}" '
          f'width="16" height="{size + 28}" fill="{band}"/></g></g>')
    s.text(x + 7, y + 12.5, str(n), F["md"], 7.5, light, opacity=.75)
    s.text(x + size / 2, y + 31, mono, F["dmd"], 17, light, anchor="middle")


def arrow(s: SVG, cx, cy, size=9, color=INK_2, sw=1.6):
    h = size / 2
    s.add(f'<path d="M{fmt(cx - h)} {fmt(cy + h)}L{fmt(cx + h)} {fmt(cy - h)}M{fmt(cx - h + 1.5)} {fmt(cy - h)}'
          f'H{fmt(cx + h)}V{fmt(cy + h - 1.5)}" stroke="{color}" stroke-width="{sw}" '
          f'stroke-linecap="round" stroke-linejoin="round"/>')


def arrow_button(s: SVG, cx, cy, r=16):
    s.add(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{r}" fill="#ffffff" fill-opacity=".045" '
          f'stroke="#ffffff" stroke-opacity=".12"/>')
    arrow(s, cx, cy, 9, INK_2)


def sparkle(s: SVG, cx, cy, r, fill=INK, cls=None):
    k = r * .16
    d = (f"M{fmt(cx)} {fmt(cy - r)}C{fmt(cx + k)} {fmt(cy - k)} {fmt(cx + k)} {fmt(cy - k)} {fmt(cx + r)} {fmt(cy)}"
         f"C{fmt(cx + k)} {fmt(cy + k)} {fmt(cx + k)} {fmt(cy + k)} {fmt(cx)} {fmt(cy + r)}"
         f"C{fmt(cx - k)} {fmt(cy + k)} {fmt(cx - k)} {fmt(cy + k)} {fmt(cx - r)} {fmt(cy)}"
         f"C{fmt(cx - k)} {fmt(cy - k)} {fmt(cx - k)} {fmt(cy - k)} {fmt(cx)} {fmt(cy - r)}Z")
    c = f' class="{cls}"' if cls else ""
    s.add(f'<path{c} d="{d}" fill="{fill}"/>')


def chip(s: SVG, x, y, t, h=34, size=14.5, font="rg", pad=17, color="#dddce5", fill_a=.035, stroke_a=.13, dot=None):
    lead = 13 if dot else 0
    w = F[font].width(t, size) + pad * 2 + lead
    s.add(f'<rect x="{fmt(x + .5)}" y="{fmt(y + .5)}" width="{fmt(w - 1)}" height="{fmt(h - 1)}" '
          f'rx="{fmt(h / 2)}" fill="#ffffff" fill-opacity="{fmt(fill_a)}" stroke="#ffffff" '
          f'stroke-opacity="{fmt(stroke_a)}"/>')
    s.add(f'<rect x="{fmt(x + h / 2)}" y="{fmt(y + .5)}" width="{fmt(w - h)}" height="1" fill="#ffffff" fill-opacity=".05"/>')
    if dot:
        s.add(f'<circle cx="{fmt(x + pad + 3.5)}" cy="{fmt(y + h / 2)}" r="6" fill="{dot}" fill-opacity=".25" filter="{s.blur(2.5)}"/>')
        s.add(f'<circle cx="{fmt(x + pad + 3.5)}" cy="{fmt(y + h / 2)}" r="3.5" fill="{dot}"/>')
    s.text(x + pad + lead, y + h / 2 + size * .36, t, F[font], size, color)
    return w


ICONS = {
    "send": '<path d="M21.5 2.5 10.6 13.4M21.5 2.5l-6.9 19-4-8.1-8.1-4z"/>',
    "mail": '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><path d="m3 6.5 9 6.5 9-6.5"/>',
    "globe": '<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19M12 2.5c2.6 2.7 4 6 4 9.5s-1.4 6.8-4 9.5c-2.6-2.7-4-6-4-9.5s1.4-6.8 4-9.5z"/>',
    "briefcase": '<rect x="2.5" y="7" width="19" height="13.5" rx="2.5"/><path d="M8.5 7V5a1.5 1.5 0 0 1 1.5-1.5h4A1.5 1.5 0 0 1 15.5 5v2M2.5 12.5h19"/>',
}


def icon(s: SVG, name, x, y, size=20, color=INK, sw=1.6):
    k = size / 24
    s.add(f'<g transform="translate({fmt(x)} {fmt(y)}) scale({fmt(k)})" stroke="{color}" '
          f'stroke-width="{fmt(sw / k)}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def screenshot(key: str) -> str | None:
    for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
        p = SCREENS / f"{key}{ext}"
        if p.exists():
            return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
    return None


# ----------------------------------------------------------------------------
# sections
# ----------------------------------------------------------------------------
def build_nav(C) -> SVG:
    s = SVG(W, 40, f"{C['name']} — " + " · ".join(C["nav"]))
    use_css(s, "twinkle")
    s.text(4, 25, C["name"].upper(), F["sb"], 13.5, OUTSIDE, tracking=.02)
    x = W - 46
    for item in reversed(C["nav"]):
        w = F["sb"].width("/ " + item.upper(), 13.5, .02)
        x -= w
        s.text(x, 25, "/ " + item.upper(), F["sb"], 13.5, OUTSIDE, tracking=.02)
        x -= 30
    sparkle(s, W - 16, 20.5, 9, OUTSIDE, cls="tw")
    return s


def glass_panel(s: SVG, m, w, h, cls, r=14, content=None, faint=False):
    T = "matrix(" + " ".join(fmt(v) for v in m) + ")"
    s.add(f'<g class="{cls}">')
    # soft shadow
    s.add(f'<g transform="{T}"><rect x="10" y="18" width="{w}" height="{h}" rx="{r}" fill="#000" '
          f'fill-opacity=".55" filter="{s.blur(14)}"/></g>')
    s.add(f'<g transform="{T}">')
    s.add(f'<rect width="{w}" height="{h}" rx="{r}" fill="#121219" fill-opacity="{".7" if faint else ".9"}"/>')
    glass = s.lin([(0, "#ffffff", .11), (.55, "#ffffff", .03), (1, "#ffffff", .015)], 0, 0, 1, 1, key="glass")
    s.add(f'<rect width="{w}" height="{h}" rx="{r}" fill="{glass}"/>')
    rim = s.lin([(0, "#ffffff", .42), (.4, "#ffffff", .12), (1, "#ffffff", .05)], 0, 0, 1, 1, key="rim")
    s.add(f'<rect x=".6" y=".6" width="{fmt(w - 1.2)}" height="{fmt(h - 1.2)}" rx="{r}" stroke="{rim}" stroke-width="1.2"/>')
    if content:
        content()
    s.add("</g></g>")


def petal(s: SVG, L, w, rot, base, bend=0.0, dark=False):
    """A long, slightly curved glass petal. Local axis: base (0,0) -> tip (b, -L)."""
    bx, by = base
    if dark:
        body = s.lin([(0, "#16151d"), (.45, "#3a3650"), (1, "#8e88a8")], 0, 1, 0, 0, key="petal_d")
    else:
        body = s.lin([(0, "#1f1d2a"), (.25, "#5d5878"), (.58, "#bdb4de"), (.86, "#ebe7f7"), (1, "#ffffff")],
                     0, 1, 0, 0, key="petal")
    shade = s.lin([(0, "#05040a", 0), (1, "#05040a", .55)], 1, 0, 0, 0, key="shade")
    b = bend * L
    tipx = b
    d = (f"M0 0C{fmt(w * .62)} {fmt(-L * .16)} {fmt(w * .62 + b * .55)} {fmt(-L * .6)} {fmt(tipx + w * .06)} {fmt(-L * .97)}"
         f"Q{fmt(tipx)} {fmt(-L)} {fmt(tipx - w * .06)} {fmt(-L * .97)}"
         f"C{fmt(-w * .62 + b * .55)} {fmt(-L * .6)} {fmt(-w * .62)} {fmt(-L * .16)} 0 0Z")
    half = (f"M0 0C{fmt(-w * .62)} {fmt(-L * .16)} {fmt(-w * .62 + b * .55)} {fmt(-L * .6)} {fmt(tipx - w * .06)} {fmt(-L * .97)}"
            f"Q{fmt(tipx)} {fmt(-L)} {fmt(tipx)} {fmt(-L * .975)}Q{fmt(b * .5 + w * .06)} {fmt(-L * .5)} 0 0Z")
    vein = f"M0 -8Q{fmt(b * .5 + w * .06)} {fmt(-L * .5)} {fmt(tipx)} {fmt(-L * .95)}"
    sheen = (f"M{fmt(w * .2)} {fmt(-L * .22)}C{fmt(w * .44 + b * .2)} {fmt(-L * .42)} "
             f"{fmt(w * .36 + b * .6)} {fmt(-L * .72)} {fmt(tipx + w * .03)} {fmt(-L * .93)}")
    s.add(f'<g transform="translate({fmt(bx)} {fmt(by)}) rotate({fmt(rot)})">')
    s.add(f'<path d="{d}" stroke="#08070c" stroke-opacity=".55" stroke-width="1.6"/>')
    s.add(f'<path d="{d}" fill="{body}" fill-opacity="{".9" if dark else ".96"}"/>')
    s.add(f'<path d="{half}" fill="{shade}"/>')
    if not dark:
        s.add(f'<path d="{vein}" stroke="#ffffff" stroke-opacity=".3" stroke-width=".8"/>')
        s.add(f'<path d="{sheen}" stroke="#ffffff" stroke-opacity=".7" stroke-width="1.3" stroke-linecap="round"/>')
    s.add("</g>")


def build_hero(C) -> SVG:
    H = 400
    h = C["hero"]
    title = f"{h['greeting']} {h['first_name']} — {h['role']}. {' '.join(h['tagline'])} {h['status']}"
    s = SVG(W, H, title)
    use_css(s, "float", "pulse", "breathe")
    s.css.append("@keyframes sw{0%,100%{transform:rotate(-1.3deg)}50%{transform:rotate(1.5deg)}}"
                 ".sw{transform-origin:932px 418px;animation:sw 10s ease-in-out infinite}")
    card(s, 0, 0, W, H)
    clip = s.clip_rect(0, 0, W, H, R)

    # ---- illustration ------------------------------------------------------
    s.add(f'<g clip-path="{clip}">')
    s.add(f'<circle class="br" cx="800" cy="215" r="300" fill="{s.rad([(0, "#9d88f2", .26), (.55, "#9d88f2", .07), (1, "#9d88f2", 0)])}"/>')
    s.add(f'<circle cx="60" cy="-60" r="340" fill="{s.rad([(0, "#ffffff", .05), (1, "#ffffff", 0)])}"/>')

    def back_right():
        s.add('<circle cx="17" cy="20" r="2.6" fill="#ffffff" fill-opacity=".5"/>')
        for i, word in enumerate(h["process"]):
            s.text(102, 46 + i * 17, word, F["rg"], 10.5, "#ffffff", anchor="end", opacity=.42)

    def left():
        s.text(54, 82, "</>", F["lt"], 27, "#e2dfee", anchor="middle")

    def main():
        s.text(24, 42, "A", F["md"], 19, "#ebe9f3")
        for i, word in enumerate(h["panel_words"]):
            s.text(24, 152 + i * 31, word.upper(), F["lt"], 19, "#ffffff", tracking=.12, opacity=.8)
        arrow(s, 30, 247, 9, "#ffffff", 1.4)

    glass_panel(s, (.92, .1, 0, 1, 860, 52), 118, 300, "fc", content=back_right)
    glass_panel(s, (.9, .16, 0, 1, 602, 156), 96, 150, "fd", faint=True)
    glass_panel(s, (.9, .16, 0, 1, 566, 116), 108, 138, "fb", content=left)
    glass_panel(s, (.86, .2, 0, 1, 648, 30), 280, 304, "fa", r=16, content=main)

    # flower
    s.add(f'<circle class="br" cx="860" cy="310" r="160" fill="{s.rad([(0, "#cbbcff", .26), (1, "#cbbcff", 0)])}"/>')
    s.add('<g class="sw">')
    base = (932, 418)
    # (angle, length, width, bend, dark) — drawn back to front
    petals = [
        (-46, 168, 40, -.06, True), (-4, 176, 40, .05, True),
        (17, 170, 36, .1, False), (-67, 172, 38, -.12, False),
        (5, 206, 42, .07, False), (-54, 200, 44, -.09, False),
        (-9, 226, 46, .04, False), (-40, 222, 48, -.06, False),
        (-24, 236, 50, -.02, False),
    ]
    for ang, L, w, bend, dark in petals:
        petal(s, L, w, ang, base, bend, dark)
    s.add("</g></g>")

    # ---- copy --------------------------------------------------------------
    x0 = 48
    w1 = s.text(x0, 106, h["greeting"] + " ", F["dsb"], 68, "#f5f4f8", tracking=-.02)
    s.text_grad(x0 + w1, 106, h["first_name"], F["dsb"], 68,
                [(0, "#d8c9ff"), (.55, "#b49af9"), (1, "#c7a8ff")], tracking=-.02)
    s.text(x0, 162, h["role"], F["drg"], 36, "#ebeaf1", tracking=-.01)
    for i, line in enumerate(h["tagline"]):
        s.text(x0, 210 + i * 25, line, F["lt"], 18, INK_3)
    cx = x0
    for c in h["chips"]:
        cx += chip(s, cx, 262, c, h=36, size=14.5) + 10
    # status pill (informational, not a link)
    st = h["status"]
    pw = F["rg"].width(st, 15) + 66
    s.add(f'<rect x="{x0 + .5}" y="316.5" width="{fmt(pw - 1)}" height="43" rx="21.5" fill="#ffffff" '
          f'fill-opacity=".03" stroke="#ffffff" stroke-opacity=".16"/>')
    s.add(f'<circle class="pu" cx="{x0 + 26}" cy="338" r="6" fill="{GREEN}"/>')
    s.add(f'<circle cx="{x0 + 26}" cy="338" r="6" fill="{GREEN}"/>')
    s.add(f'<circle cx="{x0 + 24.5}" cy="336.5" r="2" fill="#ffffff" fill-opacity=".5"/>')
    s.text(x0 + 44, 343.5, st, F["rg"], 15, "#e8e7ee")
    return s


def build_button(item) -> SVG:
    H, pad, gap_right = 52, 22, 12
    lw = F["md"].width(item["label"], 16)
    w = pad + 20 + 11 + lw + pad
    s = SVG(w + gap_right, H, item["label"])
    s.add(f'<rect x=".5" y=".5" width="{fmt(w - 1)}" height="{H - 1}" rx="14" fill="#0e0e13"/>')
    s.add(f'<rect x=".5" y=".5" width="{fmt(w - 1)}" height="{H - 1}" rx="14" fill="{s.lin([(0, "#ffffff", .07), (1, "#ffffff", .015)])}" '
          f'stroke="{s.lin([(0, "#ffffff", .22), (1, "#ffffff", .08)])}"/>')
    icon(s, item["icon"], pad, (H - 20) / 2, 20, INK)
    s.text(pad + 31, H / 2 + 5.8, item["label"], F["md"], 16, INK)
    return s


def build_about_stack(C) -> SVG:
    a = C["about"]
    cw = (W - GAP) / 2
    # ---- measure about
    size, lh = 17, 26.5
    lines = [F["rg"].wrap(p, size, cw - 56) for p in a["paragraphs"]]
    y = 92
    about_positions = []
    for para in lines:
        for ln in para:
            about_positions.append((y, ln))
            y += lh
        y += 14
    about_h = y + 8 + 112
    # ---- measure stack
    rows = C["stack"]
    also = [x if isinstance(x, list) else [x, None] for x in C.get("also", [])]
    stack_h = 74 + len(rows) * 86 + (46 if also else 0) + 18
    H = max(about_h, stack_h, 360)

    title = "About me: " + " ".join(a["paragraphs"]) + " Tech stack: " + ", ".join(
        it[0] for r in rows for it in r["items"]) + (", " + ", ".join(n for n, _ in also) if also else "")
    s = SVG(W, H, title)
    s.css.append("@keyframes gs{0%{transform:translateX(0)}22%,100%{transform:translateX(96px)}}"
                 ".gs{animation:gs 7s cubic-bezier(.5,0,.3,1) infinite}")

    # ---- about card
    card(s, 0, 0, cw, H, glow=(cw * .1, H * 1.05, 260, .1))
    label(s, 28, 46, "About me")
    for yy, ln in about_positions:
        s.text(28, yy, ln, F["rg"], size, BODY)
    sy = H - 108
    s.add(f'<rect x="28" y="{fmt(sy)}" width="{fmt(cw - 56)}" height="1" fill="#ffffff" fill-opacity=".08"/>')
    s.add(f'<rect x="28" y="{fmt(sy - .5)}" width="44" height="2" rx="1" fill="{LAV}" fill-opacity=".7"/>')
    colw = (cw - 56) / len(a["stats"])
    for i, (big, small) in enumerate(a["stats"]):
        x = 28 + i * colw + (0 if i == 0 else 18)
        if i:
            s.add(f'<rect x="{fmt(28 + i * colw)}" y="{fmt(sy + 26)}" width="1" height="56" fill="#ffffff" fill-opacity=".08"/>')
        s.text(x, sy + 54, big, F["dmd"], 24, INK)
        s.text(x, sy + 79, small, F["rg"], 14.5, INK_4)

    # ---- stack card
    x0 = cw + GAP
    card(s, x0, 0, cw, H, glow=(x0 + cw * .95, -20, 240, .12))
    label(s, x0 + 28, 46, "Tech stack")
    n = 0
    y = 70
    tile, step = 46, 72
    tx0 = x0 + cw - 28 - (tile + step * 4)
    row_step = max(86, (H - 70 - (46 if also else 0) - 18) / len(rows))
    for ri, row in enumerate(rows):
        if ri:
            s.add(f'<rect x="{fmt(x0 + 28)}" y="{fmt(y - (row_step - 68) / 2)}" width="{fmt(cw - 56)}" height="1" fill="#ffffff" fill-opacity=".06"/>')
        s.text(x0 + 28, y + 28, row["group"], F["rg"], 14, INK_2)
        for i, item in enumerate(row["items"]):
            name, mono = item[0], item[1]
            color = item[2] if len(item) > 2 else None
            n += 1
            tx = tx0 + i * step
            tech_tile(s, tx, y, tile, n, mono, color, n - 1)
            s.text(tx + tile / 2, y + tile + 17, name, F["rg"], 11, INK_4, anchor="middle")
        y += row_step
    if also:
        y = y - row_step + 68 + (row_step - 68) / 2 + 10
        s.add(f'<rect x="{fmt(x0 + 28)}" y="{fmt(y - 10)}" width="{fmt(cw - 56)}" height="1" fill="#ffffff" fill-opacity=".06"/>')
        y += 4
        lw = s.text(x0 + 28, y + 23, "Also working with", F["rg"], 14, INK_2)
        cx = max(tx0, x0 + 28 + lw + 14)
        for t, col in also:
            cx += chip(s, cx, y + 4, t, h=28, size=12.5, pad=12, dot=brand(col) if col else None) + 8
    return s


def build_projects_header(C) -> SVG:
    s = SVG(W, 30, "Selected projects — view all on GitHub")
    s.text(4, 20, "SELECTED PROJECTS", F["sb"], 13.5, OUTSIDE, tracking=.02)
    w = F["sb"].width("VIEW ALL ON GITHUB", 13.5, .02)
    s.text(W - 26 - w, 20, "VIEW ALL ON GITHUB", F["sb"], 13.5, OUTSIDE, tracking=.02)
    arrow(s, W - 11, 15.5, 8, OUTSIDE, 1.5)
    return s


# ---- project mockups (local coordinates of the device frame) ---------------
def tile_art(s: SVG, x, y, w, h, i):
    palettes = [
        ("#2c2540", "#8a76d6", "#e7defc"), ("#1d1f2b", "#6a7393", "#d6daea"),
        ("#2a2030", "#b07cc0", "#f4dcf0"), ("#191922", "#55526a", "#c8c4d8"),
        ("#241f36", "#7c68c8", "#c9bdf5"), ("#1b1b25", "#9a90b4", "#efeaf8"),
    ]
    a, b, c = palettes[i % len(palettes)]
    paint = s.lin([(0, c), (.55, b), (1, a)], 0, 0, 0, 1)
    clip = s.clip_rect(x, y, w, h, 5)
    s.add(f'<g clip-path="{clip}"><rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{paint}"/>')
    if i % 3 == 0:
        s.add(f'<circle cx="{fmt(x + w * .68)}" cy="{fmt(y + h * .32)}" r="{fmt(h * .16)}" fill="#ffffff" fill-opacity=".75"/>')
        s.add(f'<path d="M{fmt(x)} {fmt(y + h)}L{fmt(x + w * .35)} {fmt(y + h * .5)}L{fmt(x + w * .6)} {fmt(y + h * .78)}'
              f'L{fmt(x + w * .8)} {fmt(y + h * .58)}L{fmt(x + w)} {fmt(y + h * .8)}V{fmt(y + h)}Z" fill="{a}" fill-opacity=".85"/>')
    elif i % 3 == 1:
        for k in range(3):
            s.add(f'<ellipse cx="{fmt(x + w * (.3 + k * .2))}" cy="{fmt(y + h * (.55 - k * .08))}" rx="{fmt(w * .22)}" '
                  f'ry="{fmt(h * .3)}" fill="#ffffff" fill-opacity="{fmt(.12 + k * .08)}"/>')
    else:
        s.add(f'<path d="M{fmt(x + w * .5)} {fmt(y + h * .15)}C{fmt(x + w * .75)} {fmt(y + h * .35)} {fmt(x + w * .7)} '
              f'{fmt(y + h * .8)} {fmt(x + w * .5)} {fmt(y + h * .92)}C{fmt(x + w * .3)} {fmt(y + h * .8)} {fmt(x + w * .25)} '
              f'{fmt(y + h * .35)} {fmt(x + w * .5)} {fmt(y + h * .15)}Z" fill="#ffffff" fill-opacity=".55"/>')
    s.add("</g>")


def mock_brainstorming(s: SVG, fw, fh):
    s.add(f'<rect width="74" height="{fh}" fill="#ffffff" fill-opacity=".025"/>')
    s.add(f'<rect x="12" y="13" width="11" height="11" rx="3" fill="{s.lin([(0, "#e0d4ff"), (1, "#9f86f4")], 0, 0, 1, 1)}"/>')
    s.text(27, 21.5, "Brainstorming", F["md"], 7.6, "#ebe9f2")
    for i, t in enumerate(["Generate", "Library", "Favorites", "Styles", "History", "Settings"]):
        yy = 46 + i * 15
        if i == 0:
            s.add(f'<rect x="7" y="{yy - 8}" width="60" height="13" rx="4" fill="#ffffff" fill-opacity=".07"/>')
        s.add(f'<circle cx="15" cy="{yy - 1.5}" r="2.3" stroke="#ffffff" stroke-opacity=".45" stroke-width=".8"/>')
        s.text(22, yy + 1, t, F["rg"], 6.6, "#ffffff", opacity=.75 if i == 0 else .45)
    s.text(88, 22, "Generate", F["md"], 9.5, "#f1f0f6")
    s.add('<rect x="88.5" y="31.5" width="158" height="18" rx="9" fill="#ffffff" fill-opacity=".05" stroke="#ffffff" stroke-opacity=".12"/>')
    s.text(97, 43, "a glass flower in soft light…", F["rg"], 6.4, "#ffffff", opacity=.42)
    s.add(f'<rect x="252" y="31.5" width="48" height="18" rx="9" fill="{s.lin([(0, "#e2d3ff"), (1, "#b195f8")], 0, 0, 1, 0)}"/>')
    s.text(276, 43, "Create", F["md"], 6.6, "#1b1426", anchor="middle")
    tw, th, g = 66, 54, 8
    for r_ in range(3):
        for c in range(3):
            tile_art(s, 88 + c * (tw + g), 60 + r_ * (th + g), tw, th, r_ * 3 + c)


def mock_icon_ir(s: SVG, fw, fh):
    s.text(14, 19, "ICON IR", F["md"], 7.4, "#efedf5", tracking=.12)
    x = fw - 18
    for t in reversed(["About", "Services", "Cases", "Contact"]):
        x -= F["rg"].width(t, 6.2) + 12
        s.text(x, 19, t, F["rg"], 6.2, "#ffffff", opacity=.5)
    s.add(f'<rect x="14" y="27" width="{fw - 28}" height=".8" fill="#ffffff" fill-opacity=".08"/>')
    s.text(15, 66, "ICON", F["dlt"], 31, "#ffffff", tracking=.32, opacity=.9)
    s.text(16, 81, "Investor relations, made visible", F["rg"], 6.6, "#ffffff", opacity=.45)
    s.add(f'<rect x="{fw - 76}" y="56" width="58" height="17" rx="8.5" stroke="#c8b8ff" stroke-opacity=".6"/>')
    s.text(fw - 47, 67.2, "Get in touch", F["md"], 6.2, "#d9ccff", anchor="middle")
    # landscape panel
    px, py, pw, ph = 14, 94, fw - 28, 130
    clip = s.clip_rect(px, py, pw, ph, 8)
    s.add(f'<g clip-path="{clip}">')
    s.add(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{s.lin([(0, "#1c1830"), (.5, "#6a58b4"), (1, "#d7cbf7")], 0, 0, 0, 1)}"/>')
    s.add(f'<circle cx="{px + pw * .7}" cy="{py + 44}" r="15" fill="#f3eeff" fill-opacity=".85"/>')
    layers = [("#4c3e86", .9, [(0, 80), (.18, 52), (.34, 70), (.52, 40), (.7, 66), (.86, 50), (1, 72)]),
              ("#2c2453", 1, [(0, 98), (.2, 74), (.42, 92), (.6, 70), (.8, 90), (1, 80)]),
              ("#14111f", 1, [(0, 118), (.3, 100), (.55, 114), (.78, 98), (1, 112)])]
    for col, op, pts in layers:
        d = f"M{px} {py + ph}" + "".join(f"L{fmt(px + pw * t)} {fmt(py + yy)}" for t, yy in pts) + f"L{px + pw} {py + ph}Z"
        s.add(f'<path d="{d}" fill="{col}" fill-opacity="{op}"/>')
    s.add("</g>")


def mock_linkspace(s: SVG, fw, fh):
    s.add(f'<rect width="86" height="{fh}" fill="#ffffff" fill-opacity=".025"/>')
    s.add(f'<circle cx="17" cy="18" r="4.5" stroke="#d9ccff" stroke-width="1.3"/>')
    s.text(26, 21, "LinkSpace", F["md"], 8, "#efedf5")
    for i, t in enumerate(["Library", "Favorites", "Collections", "Settings"]):
        yy = 46 + i * 15
        if i == 0:
            s.add(f'<rect x="7" y="{yy - 8}" width="72" height="13" rx="4" fill="#ffffff" fill-opacity=".07"/>')
        s.add(f'<circle cx="15" cy="{yy - 1.5}" r="2.3" stroke="#ffffff" stroke-opacity=".45" stroke-width=".8"/>')
        s.text(22, yy + 1, t, F["rg"], 6.6, "#ffffff", opacity=.75 if i == 0 else .45)
    s.text(100, 25, "My links", F["md"], 10, "#f1f0f6")
    s.add(f'<rect x="{fw - 72}" y="14.5" width="58" height="16" rx="8" fill="#b9a4f8" fill-opacity=".2" stroke="#b9a4f8" stroke-opacity=".55"/>')
    s.text(fw - 43, 25.2, "+ Add link", F["md"], 6.4, "#e2d8ff", anchor="middle")
    for i, (t, n) in enumerate([("Work", 24), ("Inspiration", 57), ("AI", 18), ("To read", 31), ("Travel", 12), ("Archive", 40)]):
        yy = 40 + i * 24
        s.add(f'<rect x="100.5" y="{yy + .5}" width="{fw - 115}" height="19" rx="6" fill="#ffffff" fill-opacity=".03" stroke="#ffffff" stroke-opacity=".07"/>')
        s.add(f'<circle cx="112" cy="{yy + 10}" r="3.6" stroke="#ffffff" stroke-opacity=".45" stroke-width=".8"/>')
        s.text(121, yy + 12.4, t, F["rg"], 7, "#ffffff", opacity=.75)
        s.text(fw - 24, yy + 12.4, str(n), F["rg"], 6.4, "#ffffff", anchor="end", opacity=.35)


MOCKS = {"brainstorming": mock_brainstorming, "icon-ir": mock_icon_ir, "linkspace": mock_linkspace}


def build_project(C, p, idx, n) -> tuple[SVG, float]:
    H = 330
    cw = (W - GAP * (n - 1)) / n
    pad_l = GAP * idx / n
    pad_r = GAP * (n - 1 - idx) / n
    iw = cw + pad_l + pad_r
    s = SVG(iw, H, f"{p['title']} — {p['subtitle']}. " + ", ".join(p["tags"]))
    x0 = pad_l
    card(s, x0, 0, cw, H, glow=(x0 + cw * .5, H * 1.1, 230, .22))
    s.text(x0 + 24, 50, p["title"], F["dmd"], 23, INK, tracking=-.01)
    s.text(x0 + 24, 76, p["subtitle"], F["lt"], 14.5, INK_3)
    arrow_button(s, x0 + cw - 38, 42)
    cx = x0 + 24
    for t in p["tags"]:
        cx += chip(s, cx, 94, t, h=28, size=12.5, pad=12) + 7

    # device frame, tilted and cut by the card's bottom edge
    clip = s.clip_rect(x0, 0, cw, H, R)
    shot = screenshot(p["key"])
    fw, fh = (292, 214) if shot else (320, 230)
    m = (.97, -.07, 0, 1, x0 + 22, 152) if shot else (.97, -.075, 0, 1, x0 + 22, 166)
    T = "matrix(" + " ".join(fmt(v) for v in m) + ")"
    s.add(f'<g clip-path="{clip}"><g transform="{T}">')
    s.add(f'<rect x="8" y="16" width="{fw}" height="{fh}" rx="14" fill="#000" fill-opacity=".6" filter="{s.blur(12)}"/>')
    s.add(f'<rect width="{fw}" height="{fh}" rx="12" fill="#0b0b10"/>')
    inner = s.clip_rect(0, 0, fw, fh, 12)
    s.add(f'<g clip-path="{inner}">')
    if shot:
        bar = 17
        s.add(f'<rect width="{fw}" height="{bar}" fill="#17171e"/>')
        for k in range(3):
            s.add(f'<circle cx="{11 + k * 8}" cy="{bar / 2}" r="2.3" fill="#ffffff" fill-opacity=".22"/>')
        s.add(f'<rect x="{fw / 2 - 48}" y="4.5" width="96" height="8" rx="4" fill="#ffffff" fill-opacity=".07"/>')
        s.add(f'<image href="{shot}" y="{bar}" width="{fw}" height="{fh - bar}" preserveAspectRatio="xMidYMin meet"/>')
        s.add(f'<rect y="{bar}" width="{fw}" height="{fh - bar}" fill="{s.lin([(0, "#0b0b10", 0), (.7, "#0b0b10", 0), (1, "#0b0b10", .35)], 0, 0, 0, 1)}"/>')
    elif p["key"] in MOCKS:
        MOCKS[p["key"]](s, fw, fh)
    s.add("</g>")
    s.add(f'<rect x=".6" y=".6" width="{fw - 1.2}" height="{fh - 1.2}" rx="11.5" '
          f'stroke="{s.lin([(0, "#ffffff", .35), (1, "#ffffff", .08)], 0, 0, 1, 1)}" stroke-width="1.2"/>')
    s.add("</g></g>")
    return s, iw


def timeline(s: SVG, x, y_top, y_bottom):
    s.add(f'<rect x="{fmt(x - .5)}" y="{fmt(y_top)}" width="1" height="{fmt(y_bottom - y_top)}" '
          f'fill="{s.lin([(0, LAV, .5), (1, LAV, .05)], 0, 0, 0, 1, key="tl")}"/>')


def dot(s: SVG, x, y):
    s.add(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="7" fill="{LAV}" fill-opacity=".16"/>')
    s.add(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="4" fill="{LAV}"/>')


def layout_experience(C, w):
    out, y = [], 88
    tw = w - 50 - 26
    for e in C["experience"]:
        lines = F["rg"].wrap(e["text"], 15, tw)
        out.append((y, e, lines))
        y += 25 + 24 + len(lines) * 22 + 24
    return out, y


def layout_education(C, w):
    out, y = [], 88
    tw = w - 50 - 22
    for e in C["education"]:
        lines = []
        for k, ln in enumerate(e["lines"]):
            lines += [(k, t) for t in F["rg"].wrap(ln, 15 if k == 0 else 14, tw)]
        out.append((y, e, lines))
        y += 26 + len(lines) * 21 + 22 + 26
    return out, y


def build_bottom_row(C):
    exp_w, edu_w = 424, 304
    cta_w = W - exp_w - edu_w - GAP * 2
    exp_layout, exp_h = layout_experience(C, exp_w)
    edu_layout, edu_h = layout_education(C, edu_w)
    H = max(exp_h, edu_h, 330) + 8

    # ---- experience + education (one image)
    iw = exp_w + GAP + edu_w + GAP / 2
    alt = "Experience: " + "; ".join(f"{e['company']} — {e['role']}, {e['dates']}" for e in C["experience"]) + \
          ". Education: " + "; ".join(f"{e['title']}, {e['lines'][0]}, {e['dates']}" for e in C["education"])
    s = SVG(iw, H, alt)
    card(s, 0, 0, exp_w, H)
    label(s, 28, 46, "Experience")
    first_y, last_y = exp_layout[0][0], exp_layout[-1][0]
    timeline(s, 30, first_y - 5, last_y + 40)
    for y, e, lines in exp_layout:
        dot(s, 30, y - 5.5)
        s.text(50, y, e["company"], F["md"], 17.5, INK)
        s.text(exp_w - 26, y, e["dates"], F["rg"], 13.5, INK_4, anchor="end")
        s.text(50, y + 25, e["role"], F["rg"], 15.5, LAV)
        for k, ln in enumerate(lines):
            s.text(50, y + 49 + k * 22, ln, F["rg"], 15, BODY)

    x0 = exp_w + GAP
    card(s, x0, 0, edu_w, H)
    label(s, x0 + 28, 46, "Education")
    timeline(s, x0 + 30, edu_layout[0][0] - 5, edu_layout[-1][0] + 40)
    for y, e, lines in edu_layout:
        dot(s, x0 + 30, y - 5.5)
        s.text(x0 + 50, y, e["title"], F["md"], 17.5, INK)
        yy = y + 26
        for k, t in lines:
            s.text(x0 + 50, yy, t, F["rg"], 15 if k == 0 else 14, BODY if k == 0 else "#9e9dad")
            yy += 21
        s.text(x0 + 50, yy + 5, e["dates"], F["rg"], 14, LAV)

    # ---- CTA (separate image so it can be a link)
    c = C["cta"]
    cw_img = cta_w + GAP / 2
    t = SVG(cw_img, H, " ".join(c["title"]) + ". " + c["text"] + " " + c["button"])
    use_css(t, "twinkle", "glint")
    cx0 = GAP / 2
    card(t, cx0, 0, cta_w, H, glow=(cx0 + cta_w * .9, H * .2, 220, .28))
    clip = t.clip_rect(cx0, 0, cta_w, H, R)
    fade = t.lin([(0, "#000"), (1, "#fff")], cx0 + cta_w * .5, 0, cx0 + cta_w * .9, 0, units="userSpaceOnUse")
    mid = t.uid("m")
    t.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="{fmt(cw_img)}" height="{fmt(H)}">'
                  f'<rect width="{fmt(cw_img)}" height="{fmt(H)}" fill="{fade}"/></mask>')
    t.add(f'<g clip-path="{clip}"><g mask="url(#{mid})" fill="none">')
    for k in range(5):
        ox = k * 15
        d = (f"M{fmt(cx0 + cta_w * .38 + ox)} {fmt(H + 10)}C{fmt(cx0 + cta_w * .62 + ox)} {fmt(H * .62)} "
             f"{fmt(cx0 + cta_w * .55 + ox)} {fmt(H * .3)} {fmt(cx0 + cta_w + 30)} {fmt(-10 + k * 12)}")
        t.add(f'<path d="{d}" stroke="{t.lin([(0, "#ffffff", 0), (.5, "#d9cbff", .32 - k * .05), (1, "#ffffff", .05)], 0, 1, 1, 0, key="sw")}" stroke-width="{fmt(1.4 - k * .15)}"/>')
        if k in (0, 2):
            t.add(f'<path class="{"gl" if k == 0 else "gl2"}" d="{d}" stroke="#ffffff" stroke-opacity=".8" stroke-width="1.6" stroke-linecap="round"/>')
    t.add("</g></g>")
    sparkle(t, cx0 + 34, 50, 10, INK, cls="tw")
    t.text(cx0 + 26, 112, c["title"][0], F["dmd"], 28, INK, tracking=-.01)
    t.text(cx0 + 26, 145, c["title"][1], F["dmd"], 28, INK, tracking=-.01)
    for k, ln in enumerate(F["rg"].wrap(c["text"], 15, cta_w - 70)):
        t.text(cx0 + 26, 181 + k * 22, ln, F["rg"], 15, BODY)
    bw = F["md"].width(c["button"], 14.5) + 62
    by = H - 82
    t.add(f'<rect x="{fmt(cx0 + 26)}" y="{fmt(by)}" width="{fmt(bw)}" height="44" rx="22" '
          f'fill="{t.lin([(0, "#ead9ff"), (1, "#c3a2fb")], 0, 0, 1, 1)}"/>')
    t.add(f'<rect x="{fmt(cx0 + 26.5)}" y="{fmt(by + .5)}" width="{fmt(bw - 1)}" height="43" rx="21.5" '
          f'stroke="#ffffff" stroke-opacity=".55"/>')
    t.text(cx0 + 48, by + 27.2, c["button"], F["md"], 14.5, "#1a1324")
    arrow(t, cx0 + 26 + bw - 28, by + 22, 8.5, "#1a1324", 1.7)
    return s, iw, t, cw_img


# ----------------------------------------------------------------------------
# README
# ----------------------------------------------------------------------------
def pct(units: float) -> str:
    return fmt(round(units / W * 100 * SCALE, 2)) + "%"


def a(url, inner):
    return f'<a href="{html.escape(url, quote=True)}">{inner}</a>'


def still(inner):
    """An <a> without href: GitHub then skips wrapping the image in a link to the raw file."""
    return f"<a>{inner}</a>"


def img(src, width=None, height=None, alt=""):
    size = f' width="{width}"' if width else ""
    size += f' height="{height}"' if height else ""
    return f'<img src="{src}"{size} alt="{html.escape(alt, quote=True)}">'


def write(name: str, s: SVG) -> str:
    (ASSETS / name).write_text(s.render(), encoding="utf-8")
    return f"assets/{name}"


def text_version(C) -> str:
    h, out = C["hero"], []
    out.append(f"**{C['name']}** — {h['role']}. {' '.join(h['tagline'])}  ")
    out.append(f"{h['status']}\n")
    links = [f"[{c['label']}]({c['url']})" for c in C["contacts"] if c["url"]]
    out.append(" · ".join(links) + "\n")
    out.append("**About.** " + " ".join(C["about"]["paragraphs"]) + "\n")
    also = [x[0] if isinstance(x, list) else x for x in C.get("also", [])]
    out.append("**Stack.** " + "; ".join(f"{r['group']}: " + ", ".join(it[0] for it in r["items"]) for r in C["stack"]) +
               (("; Also: " + ", ".join(also)) if also else "") + "\n")
    out.append("**Projects.**\n")
    for p in C["projects"]:
        name = f"[{p['title']}]({p['url']})" if p["url"] else p["title"]
        out.append(f"- {name} — {p['subtitle']} ({', '.join(p['tags'])})")
    out.append("\n**Experience.**\n")
    for e in C["experience"]:
        out.append(f"- {e['company']} — {e['role']}, {e['dates']}. {e['text']}")
    out.append("\n**Education.**\n")
    for e in C["education"]:
        out.append(f"- {e['title']} — {'; '.join(e['lines'])}, {e['dates']}")
    return "\n".join(out)


def main():
    C = json.loads((TOOLS / "content.json").read_text(encoding="utf-8"))
    ASSETS.mkdir(exist_ok=True)
    for old in ASSETS.glob("*.svg"):
        old.unlink()
    warnings = []
    full = pct(W)

    rows = []
    rows.append(still(img(write("nav.svg", build_nav(C)), full, alt=f"{C['name']} — " + " · ".join(C["nav"]))))
    hero = build_hero(C)
    rows.append(still(img(write("hero.svg", hero), full, alt=hero.title)))

    btns = []
    for c in C["contacts"]:
        if not c["url"]:
            warnings.append(f"contact '{c['label']}' has no url — button skipped")
            continue
        slug = c["label"].lower().replace(" ", "-")
        btns.append(a(c["url"], img(write(f"btn-{slug}.svg", build_button(c)), height=46, alt=c["label"])))
    rows.append("".join(btns))

    ab = build_about_stack(C)
    rows.append(still(img(write("about-stack.svg", ab), full, alt=ab.title)))
    rows.append(a(C["projects_link"], img(write("projects-header.svg", build_projects_header(C)), full,
                                          alt="Selected projects — view all on GitHub")))
    cards = []
    n = len(C["projects"])
    for i, p in enumerate(C["projects"]):
        s, iw = build_project(C, p, i, n)
        url = p["url"] or C["projects_link"]
        if not p["url"]:
            warnings.append(f"project '{p['title']}' has no url — linked to {C['projects_link']}")
        cards.append(a(url, img(write(f"project-{p['key']}.svg", s), pct(iw), alt=s.title)))
    rows.append("".join(cards))

    s, iw, t, tw = build_bottom_row(C)
    rows.append(still(img(write("experience-education.svg", s), pct(iw), alt=s.title)) +
                a(C["cta"]["url"], img(write("cta.svg", t), pct(tw), alt=t.title)))

    readme = ["<!-- Generated by tools/build.py from tools/content.json — edit the JSON, not this file. -->", ""]
    for r in rows:
        readme += [f"<p>{r}</p>", ""]
    readme += ["<details>", "<summary>Text version</summary>", "", text_version(C), "", "</details>", ""]
    (ROOT / "README.md").write_text("\n".join(readme), encoding="utf-8")

    total = sum(p.stat().st_size for p in ASSETS.glob("*.svg"))
    print(f"built {len(list(ASSETS.glob('*.svg')))} svg files, {total / 1024:.0f} KB total")
    for w_ in warnings:
        print("warning:", w_, file=sys.stderr)


if __name__ == "__main__":
    main()
