"""Render README.md to a print-ready PDF (Rationale_AI_README.pdf).

Run: python make_readme_pdf.py
"""
import io
import re

import markdown
from xhtml2pdf import pisa

SRC, OUT = "README.md", "Rationale_AI_README.pdf"

CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm;
        @frame footer { -pdf-frame-content: footer; bottom: 8mm; height: 8mm; } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.4pt; line-height: 1.45;
       color: #1a1a1a; }
h1 { font-size: 21pt; color: #6a00b0; margin: 0 0 2mm 0; border-bottom: 2px solid #a100ff;
     padding-bottom: 2mm; }
h2 { font-size: 13pt; color: #6a00b0; margin: 7mm 0 2mm 0; border-bottom: 1px solid #ddd4ea;
     padding-bottom: 1.2mm; }
h3 { font-size: 10.5pt; color: #1a1a1a; margin: 5mm 0 1.5mm 0; }
p  { margin: 0 0 2.4mm 0; }
ul, ol { margin: 0 0 2.4mm 5mm; padding: 0; }
li { margin-bottom: 1mm; }
strong { color: #111; }
code { font-family: Courier, monospace; font-size: 8.4pt; background: #f4f0f8;
       color: #4a007a; padding: 0 1px; }
pre { font-family: Courier, monospace; font-size: 6.6pt; line-height: 1.18;
      background: #faf7fd; border: 1px solid #e4dcf0; border-left: 3px solid #a100ff;
      padding: 2.5mm 3mm; margin: 0 0 3mm 0; }
pre code { background: transparent; color: #222; font-size: 6.6pt; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 0 0 3.5mm 0; font-size: 8.2pt; }
th { background: #6a00b0; color: #fff; text-align: left; padding: 1.6mm 2mm;
     font-size: 8.2pt; }
td { border-bottom: 1px solid #e6e0ee; padding: 1.5mm 2mm; vertical-align: top; }
blockquote { background: #f7f2fc; border-left: 3px solid #a100ff; margin: 0 0 3mm 0;
             padding: 2mm 3mm; }
hr { border: none; border-top: 1px solid #e0d8ea; margin: 4mm 0; }
a { color: #6a00b0; text-decoration: none; }
.footer { color: #999; font-size: 7pt; text-align: center; }
"""


def main():
    md = io.open(SRC, encoding="utf-8").read()
    # the fenced ASCII diagram uses box-drawing glyphs Helvetica lacks; keep them
    # in the monospace <pre> where they render, and swap the few that don't
    md = md.translate(str.maketrans({"╔": "+", "╗": "+", "╚": "+", "╝": "+",
                                     "║": "|", "═": "=", "╤": "+", "╧": "+"}))
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    # xhtml2pdf ignores <br> inside <pre>; keep newlines literal
    html = f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{body}
<div id="footer" class="footer">Rationale.AI &middot; Team Rational.ai &middot;
Accenture Innovation Challenge 2026 &middot; page <pdf:pagenumber> of <pdf:pagecount>
</div></body></html>"""
    with open(OUT, "wb") as f:
        result = pisa.CreatePDF(io.StringIO(html), dest=f, encoding="utf-8")
    print("errors:" if result.err else "written:", OUT)


if __name__ == "__main__":
    main()
