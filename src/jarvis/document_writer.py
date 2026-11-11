"""Restrained Word formatting for generated source-based drafts."""
from __future__ import annotations

import re


def build_draft(title: str, body: str, source_name: str, coverage: str, digest: str):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor

    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(1)
    section.left_margin = section.right_margin = Inches(1)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor(0, 0, 0)
    normal = document.styles["Normal"]
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15
    document.add_paragraph(title.strip(), "Title")
    document.add_paragraph("Source-based working draft for review. Claims, citations and suitability for submission must be checked.")
    for block in re.split(r"\n\s*\n", body.strip()):
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            heading = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading:
                document.add_heading(heading[2], level=len(heading[1]))
            elif line.startswith(("- ", "* ")):
                document.add_paragraph(line[2:], "List Bullet")
            else:
                document.add_paragraph(line)
    document.add_heading("Source and coverage", level=1)
    document.add_paragraph(source_name)
    document.add_paragraph(coverage)
    document.add_paragraph(f"Source snapshot SHA256: {digest}")
    return document
