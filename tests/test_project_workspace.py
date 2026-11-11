import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.project_workspace import ProjectReader, ProjectWorkspace
from jarvis.vision.project_analysis import PROJECT_TOOLS, analyze_project


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("from helper import run\nrun()\n", encoding="utf-8")
    (root / "src" / "helper.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
    return ProjectWorkspace(root)


def test_lists_structure_and_reads_numbered_source(project):
    reader = ProjectReader(project)
    assert {row["path"] for row in reader.list_files()["entries"]} == {"src", "package.json"}
    result = reader.read_file("src/main.py", 2)
    assert result["text"] == "2: run()"
    assert result["next_line"] is None


@pytest.mark.parametrize("path", ["../outside.py", "C:/Windows/win.ini", "src/main.py:stream", "/outside.py", "src/../../x.py"])
def test_rejects_scope_escape(project, path):
    assert "error" in ProjectReader(project).execute("read_project_file", {"path": path})


def test_private_generated_and_sensitive_files_are_excluded(project):
    (project.root / ".env").write_text("private")
    (project.root / "settings.json").write_text("private")
    (project.root / "build").mkdir()
    (project.root / "build" / "source.py").write_text("generated")
    (project.root / "leak.py").write_text("password = fictional-password")
    reader = ProjectReader(project)
    results = reader.search_files()["results"]
    assert not any(row["path"].startswith((".env", "settings", "build")) for row in results)
    assert "error" in reader.execute("read_project_file", {"path": "leak.py"})
    assert not reader.search_files(content="fictional-password")["results"]


def test_literal_search_with_type_size_and_date_filters(project):
    reader = ProjectReader(project)
    result = reader.search_files(query="MAIN", extension="py", content="helper", min_bytes=1,
                                 max_bytes=100, modified_after="2000-01-01", modified_before="2099-01-01")
    assert [row["path"] for row in result["results"]] == ["src/main.py"]
    assert result["results"][0]["matches"][0]["line"] == 1
    assert not reader.search_files(content=".*")["results"]
    assert not reader.search_files(min_bytes=10000)["results"]


@pytest.mark.parametrize("args", [{"min_bytes": True}, {"content": 12}, {"modified_after": "yesterday"}, {"extra": "bad"}])
def test_invalid_search_arguments_do_not_escape(project, args):
    assert "error" in ProjectReader(project).execute("search_project_files", args)


def test_no_write_or_shell_dispatch(project):
    reader = ProjectReader(project)
    original = (project.root / "src/main.py").read_bytes()
    assert "error" in reader.execute("run_shell", {"command": "anything"})
    assert "error" in reader.execute("delete_file", {"path": "src/main.py"})
    assert (project.root / "src/main.py").read_bytes() == original
    assert reader.audit[-1]["tool"] == "unsupported_tool"


def test_read_and_walk_budgets(project):
    reader = ProjectReader(project)
    reader.MAX_TOTAL_BYTES = 1
    assert "error" in reader.execute("read_project_file", {"path": "src/main.py"})
    assert reader.limited
    reader = ProjectReader(project)
    reader.MAX_ENTRIES = 1
    assert reader.search_files()["limited"]


def test_cancelled_reader_does_not_open_source(project, monkeypatch):
    reader = ProjectReader(project, cancelled=lambda: True)
    opened = Mock(side_effect=AssertionError("must not open"))
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="cancelled"):
        reader.execute("read_project_file", {"path": "src/main.py"})
    opened.assert_not_called()


def test_rejects_changed_root_identity(project, monkeypatch):
    project.identity = (-1, -1)
    with pytest.raises(ValueError, match="changed"):
        project.path("src/main.py")


def test_rejects_hardlinked_source(project, tmp_path):
    source = tmp_path / "external.py"
    source.write_text("outside")
    try:
        os.link(source, project.root / "linked.py")
    except OSError:
        pytest.skip("hard links unavailable")
    assert "error" in ProjectReader(project).execute("read_project_file", {"path": "linked.py"})


def test_rejects_symbolic_links(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.py").write_text("outside")
    try:
        (project.root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links unavailable")
    assert "error" in ProjectReader(project).execute("read_project_file", {"path": "linked/other.py"})


def test_reparse_point_is_rejected_before_open(project, monkeypatch):
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == project.root / "src":
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    reader = ProjectReader(project)
    assert "error" in reader.execute("read_project_file", {"path": "src/main.py"})
    assert reader.bytes_read == 0


def test_long_files_paginate(project):
    (project.root / "long.py").write_text("pass\n" * 250)
    reader = ProjectReader(project)
    first = reader.read_file("long.py")
    assert first["next_line"] == 201
    assert reader.read_file("long.py", 201)["next_line"] is None


def response(*items, text="", status="completed"):
    return SimpleNamespace(output=list(items), output_text=text, status=status)


def call(name, arguments, call_id="one"):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(arguments), call_id=call_id)


def test_model_inspects_actual_files_then_answers_with_stateless_continuation(project):
    client = Mock()
    reasoning = SimpleNamespace(type="reasoning", encrypted_content="opaque")
    client.responses.create.side_effect = [
        response(reasoning, call("list_project_files", {"path": "."})),
        response(call("read_project_file", {"path": "src/main.py", "start_line": 1})),
        response(text="src/main.py:1 imports helper."),
    ]
    reader = ProjectReader(project)
    result = analyze_project(client, model="gpt-5.6-sol", content=[{"type": "input_text", "text": "Diagnose"}],
                             instructions="", reader=reader)
    assert result.output_text.startswith("src/main.py:1")
    requests = [item.kwargs for item in client.responses.create.call_args_list]
    assert all(item["store"] is False and item["parallel_tool_calls"] is False for item in requests)
    assert reasoning in requests[-1]["input"]
    outputs = [item for item in requests[-1]["input"] if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert "from helper import run" in outputs[-1]["output"]
    assert [item["tool"] for item in reader.audit] == ["list_project_files", "read_project_file"]
    assert {item["name"] for item in PROJECT_TOOLS} == {"list_project_files", "read_project_file", "search_project_files"}


def test_model_request_budget_and_no_automatic_retries(project):
    client = Mock()
    client.responses.create.return_value = response(call("list_project_files", {"path": "."}))
    with pytest.raises(ValueError, match="limit"):
        analyze_project(client, model="test", content=[], instructions="", reader=ProjectReader(project))
    assert client.responses.create.call_count == 6
    assert client.responses.create.call_args.kwargs["tool_choice"] == "none"


def test_stop_between_model_response_and_tool_prevents_read(project):
    state = {"stopped": False}
    client = Mock()
    def create(**kwargs):
        state["stopped"] = True
        return response(call("read_project_file", {"path": "src/main.py", "start_line": 1}))
    client.responses.create.side_effect = create
    reader = ProjectReader(project, cancelled=lambda: state["stopped"])
    with pytest.raises(ValueError, match="cancelled"):
        analyze_project(client, model="test", content=[], instructions="", reader=reader)
    assert reader.bytes_read == 0
    assert not reader.audit


def test_invalid_tool_arguments_become_error_without_execution(project):
    item = call("read_project_file", {})
    item.arguments = "not-json"
    client = Mock()
    client.responses.create.side_effect = [response(item), response(text="Need more context")]
    reader = ProjectReader(project)
    analyze_project(client, model="test", content=[], instructions="", reader=reader)
    assert not reader.audit[0]["ok"]
    assert reader.bytes_read == 0


def test_real_ai_adapter_uses_project_tools_and_closes_client(project, monkeypatch):
    from jarvis.ai_client import JarvisAI
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    client = Mock()
    client.responses.create.side_effect = [
        response(call("read_project_file", {"path": "src/main.py", "start_line": 1})),
        response(text="The import is at src/main.py:1."),
    ]
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    ai = JarvisAI()
    ai.model = "gpt-5.6-sol"
    result = ai.describe_image_bytes(b"fixture", "Explain", project_reader=ProjectReader(project))
    assert result.ok and "src/main.py:1" in result.message
    assert client.responses.create.call_count == 2
    client.close.assert_called_once()
