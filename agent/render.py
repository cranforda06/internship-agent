import html
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


def parse(markdown):
    blocks = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# "):
            blocks.append(("name", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(("section", line[3:].strip()))
        elif line.startswith("### "):
            text = line[4:].strip()
            left, _, right = text.rpartition(" | ")
            blocks.append(("entry", (left, right) if left else (text, "")))
        elif re.match(r"^\s*[-*] ", line):
            blocks.append(("bullet", re.sub(r"^\s*[-*] ", "", line).strip()))
        elif blocks and blocks[-1][0] in ("name", "contact") and not any(b[0] == "section" for b in blocks):
            blocks.append(("contact", line.strip()))
        else:
            blocks.append(("line", line.strip()))
    return blocks


CSS = """
@page { size: Letter; margin: 0.5in 0.6in; }
body { font-family: Calibri, Carlito, "Helvetica Neue", Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.25; color: #111; margin: 0; }
h1 { font-size: 18pt; text-align: center; margin: 0 0 2px; letter-spacing: .5px; }
.contact { text-align: center; font-size: 9.5pt; margin: 0 0 4px; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: .6px;
     border-bottom: 1px solid #333; margin: 9px 0 3px; padding-bottom: 1px; }
.entry { display: flex; justify-content: space-between; font-weight: bold; margin-top: 4px; }
.entry .right { font-weight: normal; font-style: italic; white-space: nowrap; padding-left: 12px; }
.line { margin: 1px 0; }
ul { margin: 1px 0 2px 0; padding-left: 16px; }
li { margin: 1px 0; }
"""


def _inline_html(text):
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def to_html(markdown):
    parts, in_list = [], False
    for kind, text in parse(markdown):
        if kind == "bullet" and not in_list:
            parts.append("<ul>")
            in_list = True
        elif kind != "bullet" and in_list:
            parts.append("</ul>")
            in_list = False
        if kind == "name":
            parts.append(f"<h1>{_inline_html(text)}</h1>")
        elif kind == "contact":
            parts.append(f'<div class="contact">{_inline_html(text)}</div>')
        elif kind == "section":
            parts.append(f"<h2>{_inline_html(text)}</h2>")
        elif kind == "entry":
            left, right = text
            parts.append(f'<div class="entry"><span>{_inline_html(left)}</span>'
                         f'<span class="right">{_inline_html(right)}</span></div>')
        elif kind == "bullet":
            parts.append(f"<li>{_inline_html(text)}</li>")
        else:
            parts.append(f'<div class="line">{_inline_html(text)}</div>')
    if in_list:
        parts.append("</ul>")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"


def to_pdf(markdown, out_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(to_html(markdown), wait_until="load")
        page.pdf(path=str(out_path), format="Letter", print_background=True,
                 prefer_css_page_size=True)
        browser.close()
    return len(re.findall(rb"/Type\s*/Page[^s]", Path(out_path).read_bytes()))


def _add_runs(paragraph, text):
    for i, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if chunk:
            paragraph.add_run(chunk).bold = (i % 2 == 1)


def _bottom_border(paragraph):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in {"w:val": "single", "w:sz": "6", "w:space": "1", "w:color": "333333"}.items():
        bottom.set(qn(key), value)
    borders.append(bottom)
    p_pr.append(borders)


def to_docx(markdown, out_path):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.5)
    section.left_margin = section.right_margin = Inches(0.6)
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Calibri", Pt(10.5)
    style.paragraph_format.space_after = Pt(0)
    usable_width = section.page_width - section.left_margin - section.right_margin

    for kind, text in parse(markdown):
        if kind == "name":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(text)
            run.bold, run.font.size = True, Pt(18)
        elif kind == "contact":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_runs(p, text)
        elif kind == "section":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            run = p.add_run(text.upper())
            run.bold = True
            _bottom_border(p)
        elif kind == "entry":
            left, right = text
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.tab_stops.add_tab_stop(usable_width, WD_TAB_ALIGNMENT.RIGHT)
            p.add_run(left).bold = True
            if right:
                p.add_run("\t" + right).italic = True
        elif kind == "bullet":
            p = doc.add_paragraph(style="List Bullet")
            _add_runs(p, text)
        else:
            _add_runs(doc.add_paragraph(), text)
    doc.save(str(out_path))
