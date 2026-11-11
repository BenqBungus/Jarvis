"""ProfileController (gui/profile_wiring.py): the active profile reaching the
HUD, the permission gate, memory, voice language, Settings and habits."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QObject, Signal

from jarvis import trusted_actions
from jarvis.audit import AuditLogger
from jarvis.gui.main_window import MainWindow
from jarvis.gui.profile_wiring import ProfileController
from jarvis.gui.settings_page import SettingsPage
from jarvis.habits import HabitLearner
from jarvis.models import CommandResult
from jarvis.profiles import ProfileStore
from jarvis.realtime import RealtimeVoiceConfig
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


class FakeExecutor(QObject):
    result_ready = Signal(str, str, object)

    def __init__(self) -> None:
        super().__init__()
        self.submitted = []

    def submit(self, text, source="text"):
        self.submitted.append(("text", text, source))

    def submit_tool(self, name, arguments, source="control"):
        self.submitted.append(("tool", name, arguments, source))


class Voice:
    language = None

    def set_conversation_language(self, code):
        self.language = code


@pytest.fixture
def app(qapp, tmp_path):
    settings = JarvisSettings(personalization={"address_name": "Берк", "role_packs": ["gamer"]},
                              openai={"conversation_language": "bg"})
    store = ProfileStore(tmp_path / "profiles", settings=settings, windows_user="Berk")
    store.pin_iterations = 1000
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(), settings=settings)
    window = MainWindow()
    page = SettingsPage(settings, settings_path=tmp_path / "settings.json")
    window.set_settings_widget(page)
    executor, stt, audit = FakeExecutor(), Voice(), AuditLogger(tmp_path / "audit.jsonl")
    learner = HabitLearner(store.profile_dir, audit_path=tmp_path / "audit.jsonl", primary_id=store.primary_id)
    controller = ProfileController(store, window=window, settings_page=page, router=router, executor=executor,
                                   audit=audit, settings=settings, stt=stt, learner=learner)
    yield controller
    trusted_actions.allow_full_access(True)
    window.deleteLater()


def _add_kid(controller, monkeypatch):
    dialog = controller.edit("")
    dialog.name_input.setText("Ани")
    dialog.level_cards["kid"].click()
    dialog._on_save()
    assert "PIN" in dialog.error_label.text()  # a kid profile needs the adult PIN first
    dialog._pending_pin = "2468"
    dialog._on_save()
    return controller.store.get("ani")


def test_startup_applies_the_migrated_profile(app):
    window, store = app.window, app.store
    assert window._profile_button.isVisibleTo(window)
    assert window._profile["id"] == "berk" and app.audit.profile_id == "berk"
    assert app.router.tools.level_gate.level == "adult" and app.stt.language == "bg"
    config = RealtimeVoiceConfig.from_settings(app.settings)
    assert config.greeting.startswith("Здравей, Берк")
    assert "Gaming:" in app.settings.response_language_instruction()


def test_a_kid_profile_is_limited_until_the_adult_pin(app, monkeypatch, tmp_path):
    kid = _add_kid(app, monkeypatch)
    assert kid["permission_level"] == "kid" and app.store.has_pin()
    assert app.switch("ani").ok
    assert app.router.tools.level_gate.level == "kid"
    assert app.window._level_badge.text() == "KID MODE" and not app.window._settings_button.isEnabled()
    assert app.router.long_term_memory.path == tmp_path / "profiles" / "ani" / "memory" / "memory.sqlite3"
    blocked = app.router.handle("изключи компютъра")
    assert blocked.metadata.get("blocked_by_level") == "kid"
    assert not trusted_actions.trusted_local_action(JarvisSettings(safety={"full_access_local": True}),
                                                    "create_folder")
    answers = iter(["1111", "2468"])
    monkeypatch.setattr(app.window, "ask_adult_pin", lambda name, error="": next(answers))
    assert app.switch("berk").ok
    assert app.router.tools.level_gate.level == "adult"
    assert app.router.long_term_memory.path.name == "memory.sqlite3"
    assert "profiles" not in app.router.long_term_memory.path.parts  # back on the original files


def test_cancelling_the_pin_stays_in_the_kid_profile(app, monkeypatch):
    _add_kid(app, monkeypatch)
    app.switch("ani")
    monkeypatch.setattr(app.window, "ask_adult_pin", lambda name, error="": None)
    assert not app.switch("berk").ok and app.store.active_id == "ani"


def test_a_guest_starts_clean_every_time(app, tmp_path):
    app.store.create("Гост", permission_level="guest")
    app.switch("gost")
    memory = tmp_path / "profiles" / "gost" / "memory"
    app.router.conversation_memory.add_turn("user", "secret plans")
    assert memory.exists()
    app.switch("berk")
    app.switch("gost")
    assert not (memory / "conversation_history.jsonl").exists()
    assert app.router.handle("запомни, че обичам пица").metadata.get("blocked_by_level") == "guest"


def test_results_show_blocks_and_name_the_profile(app):
    app.executor.result_ready.emit("text", "x", CommandResult(
        False, "An adult profile is needed to read email.", metadata={"blocked_by_level": "kid"}))
    assert app.window._transcript_tone == "blocked"
    app.executor.result_ready.emit("voice", "наричай ме шефе", CommandResult(
        True, "Saved", metadata={"preference_key": "address_name", "preference_value": "шефе"}))
    assert app.store.active()["personality"]["address_as"] == "шефе"


def test_settings_changes_go_to_the_active_profile(app):
    page = app.settings_page
    page._pack_switches["student"].setChecked(True)
    page._language_combo.setCurrentIndex(page._language_combo.findData("en"))
    page._on_save()
    profile = app.store.active()
    assert profile["role_packs"] == ["gamer", "student"] and profile["language"] == "en"
    assert app.settings.conversation_language == "en" and app.stt.language == "en"
    assert list(app.window._pack_cards) == ["gamer", "student"]


def test_habits_become_routines_that_only_run_when_asked(app, tmp_path):
    now = datetime.now().astimezone()
    records = [{"timestamp": (now - timedelta(days=day)).isoformat(), "action": "open_target", "ok": True,
                "dry_run": False, "source": "gui_text", "metadata": {"open_target": "discord", "profile_id": "berk"}}
               for day in (1, 2, 3)]
    (tmp_path / "audit.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    app.refresh_habits()
    [habit_id] = list(app.window._habit_cards)
    app.window.habit_accepted.emit(habit_id)
    app.learner.due_routines = lambda: app.learner.routines()  # pretend its time has come
    app.check_routines()
    assert habit_id in app.window._routine_cards and app.executor.submitted == []
    app.window.routine_run_requested.emit(habit_id)
    assert app.executor.submitted == [("text", "отвори discord", "routine")]
