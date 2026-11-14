#!/usr/bin/env python3
"""Write the static SVGs under assets/: the header (light and dark) and the tech badges.

These files are committed to main. Run this script again after changing a
color, a label or a size, then commit the result.

Standard library only. Runs on Python 3.10 or later.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from profile_cards import FONT_STACK, THEMES, Theme

ROOT = Path(__file__).resolve().parent.parent

NAME = "Yuichi Tanaka"
ROLE = "Product manager · AWS infrastructure"
TAGLINE = "Simple designs, clear trade-offs, and things you can measure."

# (label, file name, fill). Same order and colors as the shields.io badges they replace.
BADGES = (
    ("AWS", "aws", "#232F3E"),
    ("Terraform", "terraform", "#844FBA"),
    ("Go", "go", "#00ADD8"),
    ("Python", "python", "#3776AB"),
    ("TypeScript", "typescript", "#3178C6"),
    ("FastAPI", "fastapi", "#009688"),
    ("Next.js", "nextjs", "#000000"),
    ("PostgreSQL", "postgresql", "#4169E1"),
    ("Docker", "docker", "#2496ED"),
    ("OpenTelemetry", "opentelemetry", "#000000"),
)

# Advance widths of Arial Bold in 1/1000 em. Used only to size the badge and to
# set textLength, so the text keeps its box even when the viewer's font differs.
_BOLD_WIDTHS = {
    " ": 278, ".": 278, "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611,
    "G": 778, "H": 722, "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667,
    "W": 944, "X": 667, "Y": 667, "Z": 611, "a": 556, "b": 611, "c": 556, "d": 611,
    "e": 556, "f": 333, "g": 611, "h": 611, "i": 278, "j": 278, "k": 556, "l": 278,
    "m": 889, "n": 611, "o": 611, "p": 611, "q": 611, "r": 389, "s": 556, "t": 333,
    "u": 611, "v": 556, "w": 778, "x": 556, "y": 556, "z": 500, "·": 333,
    "-": 333, ",": 278,
}
_REGULAR_FACTOR = 0.92  # regular weight is about 8% narrower than bold


def _xml(text: str) -> str:
    """Escape for XML and keep the file ASCII-only (the middle dot becomes &#183;)."""
    return html.escape(text).encode("ascii", "xmlcharrefreplace").decode("ascii")


def text_width(text: str, size: float, *, bold: bool = True) -> float:
    em = sum(_BOLD_WIDTHS.get(ch, 556) for ch in text) / 1000
    return round(em * size * (1.0 if bold else _REGULAR_FACTOR), 1)


# --------------------------------------------------------------------------
# Badges
# --------------------------------------------------------------------------

BADGE_HEIGHT = 28
BADGE_FONT_SIZE = 13
BADGE_PAD = 12


def render_badge(label: str, fill: str) -> str:
    """One pill: brand color, white bold text, and a thin gray ring.

    The ring keeps black and near-black badges visible on a dark page.
    """
    text_len = text_width(label, BADGE_FONT_SIZE)
    width = round(text_len + 2 * BADGE_PAD)
    esc = _xml(label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{BADGE_HEIGHT}" '
        f'viewBox="0 0 {width} {BADGE_HEIGHT}" role="img" aria-label="{esc}">\n'
        f"<title>{esc}</title>\n"
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{BADGE_HEIGHT - 1}" rx="6" '
        f'fill="{fill}" stroke="#8b949e" stroke-opacity="0.6"/>\n'
        f'<text x="{width / 2:g}" y="18.5" text-anchor="middle" fill="#ffffff" '
        f"font-family='{FONT_STACK}' font-size=\"{BADGE_FONT_SIZE}\" font-weight=\"700\" "
        f'textLength="{text_len:g}" lengthAdjust="spacingAndGlyphs">{esc}</text>\n'
        "</svg>\n"
    )


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------

HEADER_WIDTH, HEADER_HEIGHT = 900, 200
DECOR_COLS, DECOR_ROWS = 13, 7
DECOR_CELL, DECOR_PITCH = 13, 16

# Background gradient end colors per theme (top-left, bottom-right).
_HEADER_GRADIENT = {"light": ("#ffffff", "#f6f8fa"), "dark": ("#0d1117", "#161b22")}


def _decor_level(col: int, row: int) -> int:
    """A fixed pattern of grass levels that gets denser toward the right."""
    score = ((col * 7 + row * 11 + col * row * 3) % 10) / 10 + col / (DECOR_COLS - 1)
    for level, limit in enumerate((0.55, 0.9, 1.2, 1.5)):
        if score < limit:
            return level
    return 4


def render_header(theme: Theme) -> str:
    start, end = _HEADER_GRADIENT[theme.name]
    accent = theme.levels[4]
    x0 = HEADER_WIDTH - 40 - (DECOR_COLS * DECOR_PITCH - (DECOR_PITCH - DECOR_CELL))
    y0 = (HEADER_HEIGHT - (DECOR_ROWS * DECOR_PITCH - (DECOR_PITCH - DECOR_CELL))) / 2

    cells = []
    for col in range(DECOR_COLS):
        for row in range(DECOR_ROWS):
            cells.append(
                f'<rect class="l{_decor_level(col, row)}" x="{x0 + col * DECOR_PITCH}" '
                f'y="{y0 + row * DECOR_PITCH:g}" width="{DECOR_CELL}" height="{DECOR_CELL}" rx="2"/>'
            )

    css = "\n".join(
        [f"text{{font-family:{FONT_STACK}}}"]
        + [f".l{i}{{fill:{color}}}" for i, color in enumerate(theme.levels)]
    )
    name_len = text_width(NAME, 48)
    role_len = text_width(ROLE, 20)
    tag_len = text_width(TAGLINE, 15, bold=False)
    alt = f"{NAME}. {ROLE}. {TAGLINE}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{HEADER_WIDTH}" height="{HEADER_HEIGHT}" '
        f'viewBox="0 0 {HEADER_WIDTH} {HEADER_HEIGHT}" role="img" aria-labelledby="title">\n'
        f'<title id="title">{_xml(alt)}</title>\n'
        f"<style>\n{css}\n</style>\n"
        f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{start}"/><stop offset="1" stop-color="{end}"/>'
        f"</linearGradient></defs>\n"
        f'<rect x="0.5" y="0.5" width="{HEADER_WIDTH - 1}" height="{HEADER_HEIGHT - 1}" rx="16" '
        f'fill="url(#bg)" stroke="{theme.border}"/>\n'
        + "\n".join(cells)
        + "\n"
        f'<rect x="40" y="46" width="44" height="5" rx="2.5" fill="{theme.levels[3]}"/>\n'
        f'<text x="40" y="102" font-size="48" font-weight="700" fill="{theme.text}" '
        f'textLength="{name_len:g}" lengthAdjust="spacingAndGlyphs">{_xml(NAME)}</text>\n'
        f'<text x="40" y="138" font-size="20" font-weight="600" fill="{accent}" '
        f'textLength="{role_len:g}" lengthAdjust="spacingAndGlyphs">{_xml(ROLE)}</text>\n'
        f'<text x="40" y="168" font-size="15" fill="{theme.muted}" '
        f'textLength="{tag_len:g}" lengthAdjust="spacingAndGlyphs">{_xml(TAGLINE)}</text>\n'
        "</svg>\n"
    )


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def build_all() -> dict[str, str]:
    """Relative path under assets/ -> SVG text."""
    files = {f"header-{theme.name}.svg": render_header(theme) for theme in THEMES.values()}
    for label, slug, fill in BADGES:
        files[f"badges/{slug}.svg"] = render_badge(label, fill)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the static SVGs under assets/.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "assets",
                        help="output directory (default: assets/ in this repo)")
    args = parser.parse_args(argv)
    for rel, svg in build_all().items():
        path = args.out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
