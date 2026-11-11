import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QTest

from jarvis.ai_client import JarvisAI
from jarvis.gui.game_chat import GameChatDialog
from jarvis.models import CommandResult
from jarvis.user_settings import JarvisSettings


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.create.return_value = SimpleNamespace(output_text="Use cover.", output=[])
    factory = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory))
    return client, factory


@pytest.mark.parametrize("language,marker", [("bg", "Bulgarian (bg)"), ("en", "Reply only in English"), ("auto", "current user request")])
@pytest.mark.parametrize("web", [False, True])
def test_bounded_advice_only_request(provider, language, marker, web):
    client, factory = provider
    ai = JarvisAI(settings=JarvisSettings(openai={"conversation_language": language}))
    history = [{"role": "user", "content": "x"*5000} for _ in range(14)]
    result = ai.answer_game_question("Как да защитавам?", game="Valorant", context="Ascent", history=history, web=web)
    assert result.ok
    sent = client.responses.create.call_args.kwargs
    assert sent["tools"] == ([{"type": "web_search"}] if web else [])
    assert sent["store"] is False
    assert sent["max_output_tokens"] == 1600
    assert marker in sent["instructions"]
    assert "cannot see the screen" in sent["instructions"]
    payload = json.loads(sent["input"])
    assert payload["game"] == "Valorant" and payload["context"] == "Ascent"
    assert len(payload["recent_discussion"]) == 10
    assert len(payload["recent_discussion"][0]["content"]) == 4000
    factory.assert_called_once_with(timeout=45.0, max_retries=0)
    client.__exit__.assert_called_once()


@pytest.mark.parametrize("game,question,context", [("", "hi", ""), ("A", "", ""), ("x"*121, "hi", ""), ("A", "x"*3001, ""), ("A", "hi", "x"*601)])
def test_validation_never_calls_provider(provider, game, question, context):
    assert not JarvisAI().answer_game_question(question, game=game, context=context).ok
    provider[1].assert_not_called()


def test_missing_key_and_dry_run_do_not_call_provider(provider, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert not JarvisAI().answer_game_question("hi", game="A").ok
    assert JarvisAI(dry_run=True).answer_game_question("hi", game="A").ok
    provider[1].assert_not_called()


def test_sources_are_observed_deduplicated_http_urls(provider):
    client, _ = provider
    urls = ["https://example.com/patch", "file:///C:/secret", "javascript:evil()", "https://example.com/patch", "https://user:password@example.com"]
    citations = [SimpleNamespace(type="url_citation", url=u, title="Patch notes") for u in urls]
    client.responses.create.return_value.output = [SimpleNamespace(content=[SimpleNamespace(annotations=citations)])]
    result = JarvisAI().answer_game_question("Latest patch?", game="A", web=True)
    assert result.metadata["sources"] == [{"title": "Patch notes", "url": urls[0]}]


def test_failure_hides_provider_details_and_empty_answer_is_not_success(provider):
    client, _ = provider
    client.responses.create.return_value.output_text = ""
    assert not JarvisAI().answer_game_question("hi", game="A").ok
    client.responses.create.side_effect = RuntimeError("secret raw API response")
    result = JarvisAI().answer_game_question("hi", game="A")
    assert not result.ok and "secret" not in result.message and not result.error


@pytest.fixture
def dialog(qapp):
    ai = MagicMock()
    ai.answer_game_question.return_value = CommandResult(True, "Use cover. <img src='https://example.com/tracker'>")
    d = GameChatDialog(ai)
    d.game.setText("Valorant")
    yield d
    d.shutdown()
    if d._thread:
        d._thread.join(timeout=2)


def ask(d, question="How do I defend?"):
    d.question.setText(question)
    d.send_question()


def test_follow_up_and_game_change_clear_context(dialog, pump_events):
    ask(dialog)
    assert pump_events(lambda: not dialog._busy)
    assert len(dialog.history) == 2
    assert "<img" in dialog.messages.toPlainText()
    ask(dialog, "And on attack?")
    assert pump_events(lambda: not dialog._busy)
    assert len(dialog.ai.answer_game_question.call_args.kwargs["history"]) == 2
    dialog.game.setText("Minecraft")
    assert not dialog.history and not dialog.messages.toPlainText()
    ask(dialog)
    assert pump_events(lambda: not dialog._busy)
    assert dialog.ai.answer_game_question.call_args.kwargs["history"] == []


@pytest.mark.parametrize("operation", ["cancel", "clear_chat", "shutdown", "change_game"])
def test_late_result_never_reappears(dialog, pump_events, operation):
    started, release = threading.Event(), threading.Event()
    def answer(*a, **k):
        started.set()
        release.wait(2)
        return CommandResult(True, "STALE ANSWER")
    dialog.ai.answer_game_question.side_effect = answer
    ask(dialog)
    assert started.wait(1)
    if operation == "change_game":
        dialog.game.setText("Minecraft")
    else:
        getattr(dialog, operation)()
    ask(dialog, "must not start another worker")
    assert dialog.ai.answer_game_question.call_count == 1
    release.set()
    dialog._thread.join(2)
    dialog._poll()
    assert "STALE ANSWER" not in dialog.messages.toPlainText()
    assert not dialog.history


def test_error_keeps_retry_question_without_invented_history(dialog, pump_events):
    dialog.ai.answer_game_question.return_value = CommandResult(False, "Unavailable")
    ask(dialog, "test question")
    assert pump_events(lambda: not dialog._busy)
    assert dialog.question.text() == "test question"
    assert dialog.status.text() == "Unavailable"
    assert not dialog.history


def test_escape_hides_and_reopening_preserves_chat(dialog, pump_events):
    dialog.open_chat()
    ask(dialog)
    assert pump_events(lambda: not dialog._busy)
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    QTest.keyClick(dialog.question, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    dialog.toggle()
    assert dialog.isVisible() and len(dialog.history) == 2
    dialog.toggle()
    assert not dialog.isVisible()


def test_links_require_click_and_http_scheme(dialog, monkeypatch):
    opened = []
    monkeypatch.setattr("jarvis.gui.game_chat.QDesktopServices.openUrl", lambda url: opened.append(url.toString()))
    for link in ["file:///C:/test", "javascript:foo()", "https://user:pw@example.com", "https://example.com"]:
        dialog._open_source(QUrl(link))
    assert opened == ["https://example.com"]


def test_native_manager_uses_separate_id_and_combined_modifiers(qapp):
    import ctypes
    from ctypes.wintypes import MSG
    from jarvis.gui.hotkey import HotkeyManager, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY
    manager = HotkeyManager(modifiers=MOD_ALT | MOD_CONTROL, hotkey_id=3, label="Ctrl+Alt+Space")
    manager._user32 = MagicMock()
    manager._user32.RegisterHotKey.return_value = 1
    hits = []
    manager.hotkey_pressed.connect(lambda: hits.append(True))
    assert manager.register()
    manager._user32.RegisterHotKey.assert_called_once_with(None, 3, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, 0x20)
    msg = MSG()
    msg.message = WM_HOTKEY
    for ident in [1, 2, 3]:
        msg.wParam = ident
        manager.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
    assert hits == [True]
    manager.unregister()
    manager._user32.UnregisterHotKey.assert_called_once_with(None, 3)


def test_app_wires_game_chat_without_registering_real_hotkeys(qapp, monkeypatch):
    from jarvis.gui import app as gui_app
    monkeypatch.setattr(gui_app.BackgroundMonitor, "start", lambda self: None)
    monkeypatch.setattr(gui_app, "TextToSpeech", lambda: SimpleNamespace(enabled=False, speak=lambda *a: False))
    monkeypatch.setattr(gui_app.HotkeyManager, "register", lambda self: pytest.fail("real hotkey in offscreen test"))
    _, parts = gui_app.build_app(dry_run=True)
    try:
        manager, chat = parts["game_hotkey_manager"], parts["game_chat"]
        assert manager._hotkey_id == 3 and manager._modifiers == 3
        manager.hotkey_pressed.emit()
        assert chat.isVisible()
        manager.hotkey_pressed.emit()
        assert not chat.isVisible()
        parts["game_button"].click()
        assert chat.isVisible()
        parts["game_hotkey_toggle"].setChecked(False)
        assert JarvisSettings.load().mode_preferences["game_chat_hotkey_enabled"] is False
        parts["shutdown"]()
        assert chat._closed and not chat.isVisible()
    finally:
        parts["shutdown"]()
