"""Builds the living Jarvis document: docs/JARVIS_LIVING_DOC.md -> .pdf.

The Markdown file is shared by Claude and Codex (the rules are at its top);
this script, owned by Claude, only reads it. Run from the project root:

    .\\.venv\\Scripts\\python.exe docs\\claude\\build_living_doc.py            # docs\\JARVIS_LIVING_DOC.pdf
    .\\.venv\\Scripts\\python.exe docs\\claude\\build_living_doc.py --check    # format check only
    .\\.venv\\Scripts\\python.exe docs\\claude\\build_living_doc.py --html out.html

The PDF is printed by the project's own PySide6 (QtWebEngine), so nothing
extra is installed. Printing needs a normal desktop session, not
QT_QPA_PLATFORM=offscreen; --check needs no Qt at all.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "JARVIS_LIVING_DOC.md"
OUTPUT = ROOT / "docs" / "JARVIS_LIVING_DOC.pdf"

# {KEY} in the Markdown -> (label, colour class). Unknown keys fail --check.
TAGS = {
    "API": ("API", "violet"), "PR": ("ПРОМЯНА", "amber"), "UAC": ("UAC", "red"), "MIC": ("МИКРОФОН", "cyan"),
    "NEW": ("НОВО", "green"), "WAIT": ("ЧАКА", "slate"),
    "OK": ("РАБОТИ", "green"), "TEST": ("ЗА ТЕСТ", "cyan"), "PART": ("ЧАСТИЧНО", "amber"), "IDEA": ("ИДЕЯ", "slate"),
}
MONTHS = ("януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
          "ноември", "декември")
WEEKDAYS = ("понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя")
AGENTS = {"claude": "claude", "codex": "codex", "ти": "you", "ние": "you"}

_DATE = r"(\d{4}-\d{2}-\d{2})"
_LOG_HEADING = re.compile(rf"^{_DATE}(?:\s*(?:→|->|–)\s*{_DATE})?\s*(?:·\s*(.*))?$")
_TEST_HEADING = re.compile(r"^(\d{1,2})\s*·\s*(.+)$")
_CHECK = re.compile(r"^- \[([ xX!])\]\s+(.*)$")
_BULLET = re.compile(r"^[-*] (.*)$")
_NUMBERED = re.compile(r"^(\d+)\. (.*)$")
_TRAILING_TAGS = re.compile(r"\s*((?:\{[A-Z]+\}\s*)+)$")
_TAG = re.compile(r"\{([A-Z]+)\}")


@dataclass
class Block:
    kind: str
    line: int
    text: str = ""
    items: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class Document:
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def test_rows(self) -> list[dict]:
        return [row for block in self.blocks if block.kind == "tests" for row in block.items]

    @property
    def log_days(self) -> list[Block]:
        return [block for block in self.blocks if block.kind == "log_day"]

    @property
    def updated(self) -> date | None:
        days = [block.meta["end"] for block in self.log_days]
        return max(days) if days else None


# ------------------------------------------------------------------ parsing


def parse(text: str) -> Document:
    doc = Document()
    lines = text.splitlines()
    index = 0
    paragraph: list[str] = []
    paragraph_line = 0
    chapter = ""

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            doc.blocks.append(Block("para", paragraph_line, " ".join(part.strip() for part in paragraph)))
            paragraph = []

    def add_item(kind: str, number: int, item) -> None:
        if doc.blocks and doc.blocks[-1].kind == kind:
            doc.blocks[-1].items.append(item)
        else:
            doc.blocks.append(Block(kind, number, items=[item]))

    while index < len(lines):
        raw = lines[index]
        number = index + 1
        stripped = raw.strip()
        index += 1
        if stripped.startswith("<!--"):
            flush_paragraph()
            if "page-break" in stripped:
                doc.blocks.append(Block("page_break", number))
            while "-->" not in stripped and index < len(lines):
                stripped = lines[index].strip()
                index += 1
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            code = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            doc.blocks.append(Block("code", number, "\n".join(code)))
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush_paragraph()
            doc.title = stripped[2:].strip()
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            chapter = stripped[3:].strip()
            doc.blocks.append(Block("chapter", number, chapter))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            heading = stripped[4:].strip()
            log = _LOG_HEADING.match(heading)
            test = _TEST_HEADING.match(heading)
            if log:
                start, end = _date(log.group(1), number, doc), _date(log.group(2) or log.group(1), number, doc)
                doc.blocks.append(Block("log_day", number, (log.group(3) or "").strip(),
                                        meta={"start": start, "end": end}))
            elif test:
                name = test.group(2)
                tags = _TRAILING_TAGS.search(name)
                doc.blocks.append(Block("test_section", number, name[:tags.start()].strip() if tags else name,
                                        meta={"number": int(test.group(1)),
                                              "tags": _TAG.findall(tags.group(1)) if tags else []}))
            else:
                doc.blocks.append(Block("section", number, heading))
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote = [stripped.lstrip(">").strip()]
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            doc.blocks.append(Block("quote", number, " ".join(part for part in quote if part)))
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            rows = [stripped]
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
            if len(cells) < 2 or not all(set(cell) <= set("-: ") for cell in cells[1]):
                doc.errors.append(f"line {number}: a table needs a header row and a |---| row")
                continue
            doc.blocks.append(Block("table", number, items=cells[2:], meta={"header": cells[0]}))
            continue
        item = _CHECK.match(stripped) or _BULLET.match(stripped) or _NUMBERED.match(stripped)
        if item:
            flush_paragraph()
            body = item.group(item.lastindex)
            while index < len(lines) and lines[index].startswith(("  ", "\t")) and lines[index].strip() \
                    and not _BULLET.match(lines[index].strip()) and not _CHECK.match(lines[index].strip()):
                body += " " + lines[index].strip()
                index += 1
            if item.re is _CHECK:
                state = {" ": "todo", "x": "done", "X": "done", "!": "problem"}[item.group(1)]
                if " => " in body:
                    action, expected = body.split(" => ", 1)
                    tags = _TRAILING_TAGS.search(expected)
                    add_item("tests", number, {"state": state, "action": action.strip(), "line": number,
                                               "expected": expected[:tags.start()].strip() if tags else expected.strip(),
                                               "tags": _TAG.findall(tags.group(1)) if tags else []})
                else:
                    if chapter.lower().startswith("тест"):
                        doc.errors.append(f"line {number}: a test row needs ' => ' between action and result")
                    add_item("checklist", number, {"state": state, "text": body})
            elif item.re is _NUMBERED:
                add_item("olist", number, body)
            else:
                add_item("list", number, body)
            continue
        if not paragraph:
            paragraph_line = number
        paragraph.append(stripped)
    flush_paragraph()
    _validate(doc, text)
    return doc


def _date(value: str, line: int, doc: Document) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        doc.errors.append(f"line {line}: {value} is not a real date (YYYY-MM-DD)")
        return date(1970, 1, 1)


def _validate(doc: Document, text: str) -> None:
    if not doc.title:
        doc.errors.append("the document needs a '# title' line")
    for number, line in enumerate(text.splitlines(), start=1):
        if "`" in line:
            line = re.sub(r"`[^`]*`", "", line)  # tags inside code are just text
        for key in _TAG.findall(line):
            if key not in TAGS:
                doc.errors.append(f"line {number}: unknown tag {{{key}}} (known: {', '.join(TAGS)})")
    previous = 0
    for block in doc.blocks:
        if block.kind == "test_section":
            if block.meta["number"] <= previous:
                doc.errors.append(f"line {block.line}: test section {block.meta['number']:02d} must be "
                                  f"numbered after {previous:02d}")
            previous = block.meta["number"]
    newest = None
    for block in doc.log_days:
        start, end = block.meta["start"], block.meta["end"]
        if end < start:
            doc.errors.append(f"line {block.line}: a date range must end after it starts")
        if newest is not None and start > newest:
            doc.errors.append(f"line {block.line}: the log is newest first; {start} is newer than the day above it")
        newest = start


# ---------------------------------------------------------------- rendering


def _tag(key: str) -> str:
    label, colour = TAGS.get(key, (key, "slate"))
    return f'<span class="tag {colour}">{html.escape(label)}</span>'


def inline(text: str) -> str:
    codes: list[str] = []

    def keep(match: re.Match) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])_(.+?)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = _TAG.sub(lambda match: _tag(match.group(1)), text)
    text = re.sub(r"<strong>([^<:]+):</strong>",
                  lambda match: (f'<span class="who {AGENTS[match.group(1).strip().lower()]}">{match.group(1)}</span>'
                                 if match.group(1).strip().lower() in AGENTS else match.group(0)), text)
    return re.sub(r"\x00(\d+)\x00", lambda match: f"<code>{html.escape(codes[int(match.group(1))])}</code>", text)


def _long_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _day_label(block: Block) -> str:
    start, end = block.meta["start"], block.meta["end"]
    if start == end:
        return f"{_long_date(start)} · {WEEKDAYS[start.weekday()]}"
    same_year = start.year == end.year
    first = f"{start.day} {MONTHS[start.month - 1]}" + ("" if same_year else f" {start.year}")
    return f"{first} – {_long_date(end)}"


def _box(state: str) -> str:
    return {"todo": '<span class="box"></span>', "done": '<span class="box done">✓</span>',
            "problem": '<span class="box problem">!</span>'}[state]


def _slug(index: int) -> str:
    return f"ch{index}"


def render_html(doc: Document) -> str:
    updated = doc.updated or date.today()
    rows = doc.test_rows
    sections = [block for block in doc.blocks if block.kind == "test_section"]
    done = sum(row["state"] == "done" for row in rows)
    problems = sum(row["state"] == "problem" for row in rows)
    chapters = [block for block in doc.blocks if block.kind == "chapter"]
    out = [f'<section class="cover"><div class="brand">J.A.R.V.I.S</div>'
           f'<div class="doc-title">{inline(doc.title.split("—", 1)[-1].strip() if "—" in doc.title else doc.title)}</div>']
    stats = [(str(len(rows)), "теста за ръчна проверка"), (str(len(sections)), "раздела"),
             (f"{done}/{len(rows)}", "отметнати"), (str(len(doc.log_days)), "дни в дневника")]
    if problems:
        stats.insert(3, (str(problems), "с проблем"))
    out.append('<div class="meta">Обновено: ' + _long_date(updated) + "</div>")
    out.append('<div class="stats">' + "".join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>'
                                                for value, label in stats) + "</div>")
    out.append('<div class="toc"><div class="toc-title">Съдържание</div><ol>')
    for index, chapter in enumerate(chapters, start=1):
        out.append(f'<li><a href="#{_slug(index)}">{inline(chapter.text)}</a></li>')
    out.append("</ol></div></section>")

    chapter_index = 0
    section_number = 0
    row_number = 0
    open_log = False
    for block in doc.blocks:
        if open_log and block.kind in {"chapter", "log_day", "page_break"}:
            out.append("</div></div>")
            open_log = False
        if block.kind == "page_break":
            out.append('<div class="page-break"></div>')
        elif block.kind == "chapter":
            chapter_index += 1
            out.append(f'<h2 id="{_slug(chapter_index)}"><span class="num">{chapter_index:02d}</span>'
                       f"{inline(block.text)}</h2>")
        elif block.kind == "section":
            out.append(f"<h3>{inline(block.text)}</h3>")
        elif block.kind == "test_section":
            section_number = block.meta["number"]
            row_number = 0
            tags = " ".join(_tag(key) for key in block.meta["tags"])
            out.append(f'<h3 class="test"><span class="num">{section_number:02d}</span>{inline(block.text)}'
                       f'{" " + tags if tags else ""}</h3>')
        elif block.kind == "log_day":
            title = f'<span class="day-title">{inline(block.text)}</span>' if block.text else ""
            out.append(f'<div class="day"><div class="day-head"><span class="dot"></span>'
                       f'<span class="day-date">{_day_label(block)}</span>{title}</div><div class="day-body">')
            open_log = True
        elif block.kind == "tests":
            out.append('<table class="tests"><thead><tr><th class="c-box"></th><th class="c-num">#</th>'
                       "<th>Какво правиш / казваш</th><th>Какво трябва да стане</th></tr></thead><tbody>")
            for row in block.items:
                row_number += 1
                tags = "".join(_tag(key) for key in row["tags"])
                out.append(f'<tr class="{row["state"]}"><td class="c-box">{_box(row["state"])}</td>'
                           f'<td class="c-num">{section_number}.{row_number}</td>'
                           f'<td>{inline(row["action"])}{"<div class=tags>" + tags + "</div>" if tags else ""}</td>'
                           f'<td>{inline(row["expected"])}</td></tr>')
            out.append("</tbody></table>")
        elif block.kind == "checklist":
            out.append('<ul class="checklist">' + "".join(
                f'<li class="{item["state"]}">{_box(item["state"])}<span>{inline(item["text"])}</span></li>'
                for item in block.items) + "</ul>")
        elif block.kind == "list":
            out.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in block.items) + "</ul>")
        elif block.kind == "olist":
            out.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in block.items) + "</ol>")
        elif block.kind == "table":
            header = block.meta["header"]
            out.append(f'<table class="grid cols-{len(header)}"><thead><tr>'
                       + "".join(f"<th>{inline(cell)}</th>" for cell in header)
                       + "</tr></thead><tbody>")
            for cells in block.items:
                out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in cells) + "</tr>")
            out.append("</tbody></table>")
        elif block.kind == "quote":
            out.append(f'<div class="callout">{inline(block.text)}</div>')
        elif block.kind == "code":
            out.append(f"<pre>{html.escape(block.text)}</pre>")
        elif block.kind == "para":
            out.append(f"<p>{inline(block.text)}</p>")
    if open_log:
        out.append("</div></div>")
    footer = f"J.A.R.V.I.S · жив документ · обновен на {updated:%d.%m.%Y}"
    return (f'<!doctype html><html lang="bg"><head><meta charset="utf-8"><title>{html.escape(doc.title)}</title>'
            f"<style>{_CSS.replace('@@FOOTER@@', footer)}</style></head><body>{''.join(out)}</body></html>")


_CSS = """
@page { size: A4;
  @bottom-left { content: "@@FOOTER@@"; font: 7.5pt 'Segoe UI'; color: #6B7280; }
  @bottom-right { content: "стр. " counter(page) " / " counter(pages); font: 7.5pt 'Segoe UI'; color: #6B7280; } }
* { box-sizing: border-box; }
body { margin: 0; font: 9.2pt/1.42 'Segoe UI', sans-serif; color: #111827; }
a { color: #0891B2; text-decoration: none; }
strong { font-weight: 600; }
code { font: 8.4pt Consolas, monospace; background: #F3F4F6; padding: 0 3px; border-radius: 3px; }
pre { font: 8.3pt/1.45 Consolas, monospace; background: #F3F4F6; padding: 7px 9px; border-radius: 6px;
  white-space: pre-wrap; margin: 4px 0 10px; }
p { margin: 0 0 7px; }
ul, ol { margin: 0 0 9px; padding-left: 18px; }
li { margin: 0 0 3px; }
.cover { padding: 6mm 0 2mm; }
.brand { font-weight: 700; font-size: 30pt; letter-spacing: 3px; color: #0891B2; line-height: 1.1; }
.doc-title { font-size: 13pt; color: #4B5563; margin-top: 2px; }
.meta { font-size: 8pt; color: #6B7280; margin-top: 6px; }
.stats { display: flex; gap: 8px; margin: 14px 0 12px; }
.stat { flex: 1; border: 1px solid #E5E7EB; border-radius: 8px; padding: 7px 10px; background: #FAFAFA; }
.stat b { display: block; font-size: 15pt; font-weight: 600; color: #111827; line-height: 1.2; }
.stat span { font-size: 7.8pt; color: #6B7280; }
.toc { border: 1px solid #E5E7EB; border-radius: 8px; padding: 8px 12px 4px; margin-bottom: 8px; }
.toc-title { font-weight: 600; font-size: 8pt; color: #6B7280; letter-spacing: 1px; text-transform: uppercase; }
.toc ol { columns: 2; margin: 4px 0 4px; padding-left: 20px; }
.toc a { color: #111827; }
h2 { font-weight: 600; font-size: 15pt; margin: 16px 0 8px; padding-left: 9px; border-left: 3px solid #0891B2;
  break-after: avoid; }
h2 .num { color: #0891B2; margin-right: 9px; }
h3 { font-weight: 600; font-size: 11pt; margin: 12px 0 5px; break-after: avoid; }
h3.test { padding-left: 8px; border-left: 3px solid #0891B2; margin-top: 14px; }
h3.test .num { color: #0891B2; margin-right: 8px; }
h3 + p { color: #4B5563; font-size: 8.6pt; }
.page-break { break-after: page; }
.callout { border: 1px solid #BAE6FD; background: #F0F9FF; border-radius: 8px; padding: 8px 11px; margin: 6px 0 10px; }
.tag { display: inline-block; font-weight: 700; font-size: 6.4pt; letter-spacing: .4px; padding: 0 5px;
  border-radius: 3px; border: 1px solid; margin: 1px 3px 1px 0; line-height: 1.55; vertical-align: 1px; }
.tag.violet { color: #7C3AED; border-color: #DDD6FE; background: #F5F3FF; }
.tag.amber { color: #B45309; border-color: #FDE68A; background: #FFFBEB; }
.tag.red { color: #DC2626; border-color: #FECACA; background: #FEF2F2; }
.tag.cyan { color: #0E7490; border-color: #A5F3FC; background: #ECFEFF; }
.tag.green { color: #047857; border-color: #A7F3D0; background: #ECFDF5; }
.tag.slate { color: #475569; border-color: #CBD5E1; background: #F8FAFC; }
table { width: 100%; border-collapse: collapse; margin: 4px 0 12px; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #F3F4F6; font-weight: 600; font-size: 7.6pt; color: #4B5563; text-align: left; padding: 4px 5px;
  letter-spacing: .3px; }
td { padding: 4px 5px 5px; border-bottom: .5pt solid #E5E7EB; vertical-align: top; font-size: 8.8pt; }
table.tests th:nth-child(3), table.tests td:nth-child(3) { width: 43%; }
table.tests .c-box { width: 18px; padding-top: 6px; }
table.tests .c-num { width: 34px; color: #6B7280; }
table.tests tr.done td { color: #4B5563; }
table.tests tr.problem td { background: #FEF2F2; }
.tags { margin-top: 2px; }
table.grid.cols-3 td:first-child { width: 68%; }
table.grid.cols-4 td:nth-child(1) { width: 21%; }
table.grid.cols-4 td:nth-child(2) { width: 45%; }
table.grid.cols-4 td:nth-child(4) { width: 13%; }
.box { display: inline-block; width: 10px; height: 10px; border: .8pt solid #9CA3AF; border-radius: 2px;
  font-size: 7pt; line-height: 9px; text-align: center; font-weight: 700; color: #fff; vertical-align: -1px; }
.box.done { background: #047857; border-color: #047857; }
.box.problem { background: #DC2626; border-color: #DC2626; }
ul.checklist { list-style: none; padding-left: 2px; }
ul.checklist li { display: flex; gap: 7px; align-items: baseline; }
ul.checklist li.done span { color: #6B7280; text-decoration: line-through; }
.day { position: relative; padding: 0 0 6px 16px; border-left: 1.5px solid #E5E7EB; margin-left: 4px; }
.day-head { break-after: avoid; margin-bottom: 2px; }
.day .dot { position: absolute; left: -5px; top: 4px; width: 8px; height: 8px; border-radius: 50%;
  background: #0891B2; }
.day-date { font-weight: 600; font-size: 10.5pt; }
.day-title { color: #4B5563; margin-left: 8px; }
.day-body ul { margin-bottom: 4px; list-style: none; padding-left: 0; }
.who { display: inline-block; font-weight: 700; font-size: 7pt; padding: 0 6px; border-radius: 3px; margin-right: 4px;
  line-height: 1.6; vertical-align: 1px; }
.who.claude { color: #6D28D9; background: #F5F3FF; }
.who.codex { color: #047857; background: #ECFDF5; }
.who.you { color: #B45309; background: #FFFBEB; }
"""


# ----------------------------------------------------------------- printing


def print_pdf(html_text: str, output: Path, timeout_ms: int = 90_000) -> bool:
    from PySide6.QtCore import QCoreApplication, QMarginsF, Qt, QTimer, QUrl
    from PySide6.QtGui import QPageLayout, QPageSize

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0]])
    page = QWebEnginePage()
    result = {"ok": False}
    layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                         QMarginsF(17, 15, 17, 16), QPageLayout.Unit.Millimeter)

    def loaded(ok: bool) -> None:
        if ok:
            page.printToPdf(str(output), layout)
        else:
            app.quit()

    def printed(_path: str, ok: bool) -> None:
        result["ok"] = ok
        app.quit()

    page.loadFinished.connect(loaded)
    page.pdfPrintingFinished.connect(printed)
    page.setHtml(html_text, QUrl.fromLocalFile(str(ROOT) + "/"))
    QTimer.singleShot(timeout_ms, app.quit)
    app.exec()
    return result["ok"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check the Markdown format")
    parser.add_argument("--html", type=Path, help="also save the rendered HTML here")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    doc = parse(args.source.read_text(encoding="utf-8"))
    rows = doc.test_rows
    print(f"{len(rows)} tests ({sum(row['state'] == 'done' for row in rows)} ticked, "
          f"{sum(row['state'] == 'problem' for row in rows)} with problems), {len(doc.log_days)} log days")
    for error in doc.errors:
        print("ERROR", error)
    if doc.errors:
        return 1
    if args.check:
        return 0
    rendered = render_html(doc)
    if args.html:
        args.html.write_text(rendered, encoding="utf-8")
    if not print_pdf(rendered, args.output):
        print("ERROR printing failed (a desktop session is needed; unset QT_QPA_PLATFORM=offscreen)")
        return 1
    print("saved", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
