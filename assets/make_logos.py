"""One-colour logos from assets/logo.svg and assets/gliph.svg: ink = the dark shapes, paper = the white ones (cut out as holes).

Writes assets/logo-for-{dark,light}.svg and assets/gliph-for-{dark,light}.svg, with the wordmark turned into outlines.
Run from the project root: `python assets/make_logos.py [path/to/BauhausRegular.ttf]` (needs `pip install fonttools`).
When logo.svg's text or position changes, update the three numbers marked below (they come from its text group).
"""
import os, re, sys
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

assets = Path("assets")
font = TTFont(sys.argv[1] if len(sys.argv) > 1 else os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\BauhausRegular.ttf"))
cmap, hmtx, upm, gs = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm, font.getGlyphSet()
kern = font["kern"].kernTables[0].kernTable if "kern" in font else {}
K, EX, EY = 5.661076, -1286.714902, 217.822 * 5.661076 - 800.866614  # the text group's scale, x and y offsets in logo.svg
k = 50 / upm * K

def adv(c): return hmtx[cmap[ord(c)]][0] * 50 / upm
x, pos = 271.287, []
for a, b in zip("ReeF", "eeFi"):
    pos.append(x)
    x += adv(a) + kern.get((cmap[ord(a)], cmap[ord(b)]), 0) * 50 / upm
pos += [368.337, 379.937]   # absolute x of the original tspans
pos.append(pos[5] + adv("n"))

def outline(color: str) -> str:
    parts = []
    for ch, cx in zip("ReeFind", pos):
        pen = SVGPathPen(gs)
        gs[cmap[ord(ch)]].draw(TransformPen(pen, (k, 0, 0, -k, cx * K + EX, EY)))
        parts.append(pen.getCommands())
    return f'<path d="{" ".join(parts)}" fill="{color}" fill-rule="nonzero"/>'

PATH = re.compile(r'<path d="([^"]+)" style="fill:rgb\((\d+),(\d+),(\d+)\);"/>')
GROUP = re.compile(r"(<g id=[^>]*>)(.*?)(</g>)", re.S)

def mono_symbol(svg: str, color: str) -> str:
    """Redraw the symbol in one colour: each dark shape is masked by the white shapes drawn after it."""
    def redo(m):
        items = [(d, "paper" if int(r) > 128 else "ink") for d, r, _, _ in PATH.findall(m.group(2))
                 if not d.startswith("M54.5,0L")]  # the white plate behind everything is dropped
        defs = body = ""
        for i, (d, kind) in enumerate(items):
            if kind == "ink":
                holes = "".join(f'<path d="{h}" fill="#000"/>' for h, kh in items[i + 1:] if kh == "paper")
                defs += (f'<mask id="m{i}" maskUnits="userSpaceOnUse" x="-100" y="-100" width="800" height="800">'
                         f'<rect x="-100" y="-100" width="800" height="800" fill="#fff"/>{holes}</mask>')
                body += f'<path d="{d}" fill="{color}" mask="url(#m{i})"/>'
        return f"{m.group(1)}<defs>{defs}</defs>{body}{m.group(3)}"
    return GROUP.sub(redo, svg, count=1)

logo = (assets / "logo.svg").read_text(encoding="utf-8")
logo = re.sub(r'<g transform="matrix\(5\.661076.*?</g>', "@@TEXT@@", logo, flags=re.S)
glyph = (assets / "gliph.svg").read_text(encoding="utf-8")
for theme, color in (("dark", "#FFFFFF"), ("light", "#1D3557")):
    (assets / f"logo-for-{theme}.svg").write_text(mono_symbol(logo, color).replace("@@TEXT@@", outline(color)), encoding="utf-8")
    (assets / f"gliph-for-{theme}.svg").write_text(mono_symbol(glyph, color), encoding="utf-8")
print("ok", sorted(p.name for p in assets.iterdir()))
