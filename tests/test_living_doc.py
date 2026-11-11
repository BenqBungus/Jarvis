"""The shared living document (docs/JARVIS_LIVING_DOC.md) must stay in the
format docs/claude/build_living_doc.py can turn into the PDF."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("build_living_doc", ROOT / "docs" / "claude" / "build_living_doc.py")
builder = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = builder  # dataclasses look their module up while the class is built
_SPEC.loader.exec_module(builder)


def test_the_living_document_parses_without_errors():
    doc = builder.parse((ROOT / "docs" / "JARVIS_LIVING_DOC.md").read_text(encoding="utf-8"))
    assert doc.errors == []
    assert len(doc.test_rows) > 100
    assert doc.log_days and doc.updated is not None


def test_test_rows_tags_and_states():
    doc = builder.parse(
        "# J — doc\n## Тестове\n### 01 · Start {API}\n"
        "- [ ] Say **„hi“** => Answers `ok` {NEW} {MIC}\n- [x] Done => Yes\n- [!] Broken => No\n")
    rows = doc.test_rows
    assert [row["state"] for row in rows] == ["todo", "done", "problem"]
    assert rows[0]["tags"] == ["NEW", "MIC"] and rows[0]["expected"] == "Answers `ok`"
    section = next(block for block in doc.blocks if block.kind == "test_section")
    assert section.meta == {"number": 1, "tags": ["API"]} and section.text == "Start"
    html = builder.render_html(doc)
    assert "<strong>„hi“</strong>" in html and "<code>ok</code>" in html
    assert 'class="c-num">1.3<' in html and "box problem" in html


def test_format_mistakes_are_reported_with_line_numbers():
    doc = builder.parse(
        "# J — doc\n## Тестове\n### 02 · B\n### 01 · A\n- [ ] no arrow here\n- [ ] x => y {NOPE}\n"
        "## Дневник\n### 2026-09-20\n### 2026-09-24\n### 2026-02-30\n")
    text = "\n".join(doc.errors)
    assert "line 4: test section 01" in text
    assert "line 5: a test row needs ' => '" in text
    assert "line 6: unknown tag {NOPE}" in text
    assert "line 9: the log is newest first" in text
    assert "line 10: 2026-02-30 is not a real date" in text


def test_log_days_get_bulgarian_dates_and_agent_labels():
    doc = builder.parse("# J — doc\n## Дневник\n### 2026-09-25 · Title\n- **Claude:** built it\n"
                        "### 2026-09-08 → 2026-09-11\n- **Codex:** things\n")
    assert doc.updated == date(2026, 9, 25)
    html = builder.render_html(doc)
    assert "25 септември 2026 · петък" in html and "8 септември – 11 септември 2026" in html
    assert '<span class="who claude">Claude</span>' in html and '<span class="who codex">Codex</span>' in html


def test_markup_is_escaped():
    assert builder.inline("отвори <alias> & **bold**") == "отвори &lt;alias&gt; &amp; <strong>bold</strong>"
    assert builder.inline("`test_ai_client_traces.py` and file_name_here") == (
        "<code>test_ai_client_traces.py</code> and file_name_here")
