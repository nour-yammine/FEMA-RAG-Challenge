#!/usr/bin/env python3
"""
Build DESIGN.pdf from DESIGN.md.

Dependencies (backend venv recommended):
    pip install fpdf2 markdown

Fonts download once into scripts/.fonts/ (safe to delete to re-fetch).
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

import markdown
from fpdf import FPDF
from fpdf.fonts import FontFace, TextStyle
from fpdf.html import DEFAULT_TAG_STYLES

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "DESIGN.md"
PDF_PATH = ROOT / "DESIGN.pdf"
FONT_DIR = Path(__file__).resolve().parent / ".fonts"
FONT_BASE = "https://cdn.jsdelivr.net/npm/dejavu-fonts-ttf@2.37.3/ttf/"

FONT_FILES = [
    "DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans-Oblique.ttf",
    "DejaVuSans-BoldOblique.ttf",
    "DejaVuSansMono.ttf",
    "DejaVuSansMono-Bold.ttf",
]


def ensure_fonts() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for fname in FONT_FILES:
        dest = FONT_DIR / fname
        if dest.exists():
            continue
        print(f"Downloading font {fname} …", file=sys.stderr)
        urllib.request.urlretrieve(FONT_BASE + fname, dest)


def register_fonts(pdf: FPDF) -> None:
    pdf.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVu", "I", str(FONT_DIR / "DejaVuSans-Oblique.ttf"))
    pdf.add_font("DejaVu", "BI", str(FONT_DIR / "DejaVuSans-BoldOblique.ttf"))
    pdf.add_font("DejaVuMono", "", str(FONT_DIR / "DejaVuSansMono.ttf"))
    pdf.add_font("DejaVuMono", "B", str(FONT_DIR / "DejaVuSansMono-Bold.ttf"))


def build_tag_styles() -> dict:
    dejavu = FontFace(family="DejaVu")
    out: dict = {}
    for tag, st in DEFAULT_TAG_STYLES.items():
        if isinstance(st, TextStyle):
            out[tag] = st.replace(font_family="DejaVu")
        else:
            out[tag] = FontFace.combine(st, dejavu)
    out["code"] = FontFace(family="DejaVuMono")
    out["pre"] = DEFAULT_TAG_STYLES["pre"].replace(font_family="DejaVuMono")
    return out


def flatten_pipe_tables(text: str) -> str:
    """
    fpdf2 renders Markdown tables as HTML <table> using PDF core fonts (Times),
    which cannot represent most Unicode. Convert pipe tables to bullet lists first.
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            out.append("")
            out.append("**[Table — rows as bullets]**")
            while i < len(lines):
                row = lines[i].strip()
                if not row.startswith("|"):
                    break
                if re.match(r"^\|\s*[:-][\s|:-]*\|\s*$", row):
                    i += 1
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                out.append("- " + " · ".join(cells))
                i += 1
            out.append("")
            continue
        out.append(raw)
        i += 1
    return "\n".join(out)


def preprocess_md(raw: str) -> str:
    raw = re.sub(
        r"```mermaid\s*[\s\S]*?```",
        "\n\n**[Figure — architecture flowchart (Mermaid): open `DESIGN.md` in GitHub or an editor with Mermaid preview.]**\n\n",
        raw,
        flags=re.IGNORECASE,
    )
    return raw


# Smart quotes / dashes in DESIGN.md break fpdf2 when any path still uses core fonts.
_UNICODE_ASCII = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2014": "--",
        "\u2013": "-",
        "\u2192": "->",
        "\u2026": "...",
        "\u2265": ">=",
        "\u2264": "<=",
        "\u00a7": "Sec.",
        "\u00a0": " ",
        "\u202f": " ",
    }
)


def normalize_punctuation(text: str) -> str:
    return text.translate(_UNICODE_ASCII)


def main() -> None:
    if not MD_PATH.is_file():
        print(f"Missing {MD_PATH}", file=sys.stderr)
        sys.exit(1)

    ensure_fonts()

    body = preprocess_md(MD_PATH.read_text(encoding="utf-8"))
    body = normalize_punctuation(body)
    body = flatten_pipe_tables(body)
    html = markdown.markdown(
        body,
        extensions=["fenced_code", "nl2br", "sane_lists"],
    )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_left_margin(18)
    pdf.set_right_margin(18)

    register_fonts(pdf)

    pdf.add_page()
    pdf.set_font("DejaVu", "", 11)
    pdf.write_html(
        html,
        tag_styles=build_tag_styles(),
        table_line_separators=True,
    )

    pdf.output(str(PDF_PATH))
    print(f"Wrote {PDF_PATH} ({PDF_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
