import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel

from jarvis.ai_client import JarvisAI, DEFAULT_MODEL
from jarvis.gui.settings_page import SettingsPage
from jarvis.gui.settings_runtime import SettingsRuntime
from jarvis.user_settings import JarvisSettings


@pytest.fixture
def rig(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OPENAI_MODEL", raising=False)
    settings = JarvisSettings(browser_paths={"chrome": "C:/chrome.exe", "edge": "C:/edge.exe"})
    ai = JarvisAI(settings=settings)
    page = SettingsPage(settings, ai=ai, settings_path=tmp_path/'settings.json')
    stt = SimpleNamespace(_listen_lock=threading.RLock(), _recognizer=SimpleNamespace(non_speaking_duration=0.5))
    tts = SimpleNamespace(_lock=threading.Lock(), _engine=None)
    assistant = SimpleNamespace(tts=SimpleNamespace(enabled=False))
    screen = SimpleNamespace(sharing=SimpleNamespace(ai=SimpleNamespace(model="old")), model_label=QLabel())
    busy = [False]
    mic = threading.Lock()
    runtime = SettingsRuntime(settings, stt, tts, assistant, mic, lambda: busy[0], screen, page)
    yield SimpleNamespace(settings=settings, page=page, stt=stt, tts=tts, assistant=assistant,
                          screen=screen, busy=busy, mic=mic, runtime=runtime, ai=ai)
    runtime.stop()
    page.close()


def test_saved_voice_controls_reach_existing_instances(rig, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    p = rig.page
    p._tts_provider_combo.setCurrentText("openai")
    p._tts_voice_combo.setCurrentText("marin")
    p._tts_model_input.setText("tts-test")
    p._stt_provider_combo.setCurrentText("openai")
    p._stt_model_input.setText("stt-test")
    p._energy_threshold_spinbox.setValue(450)
    p._pause_threshold_spinbox.setValue(300)
    p._on_save()
    assert rig.tts.provider == "openai" and rig.tts.openai_voice == "marin"
    assert rig.tts.openai_model == "tts-test" and rig.tts.enabled
    assert rig.stt.openai_model == "stt-test" and rig.stt.provider == "openai"
    assert rig.stt._recognizer.energy_threshold == 450
    assert not rig.stt._recognizer.dynamic_energy_threshold
    assert rig.stt._recognizer.pause_threshold == 0.3
    assert rig.stt._recognizer.non_speaking_duration <= 0.3
    assert rig.assistant.tts.enabled
    assert "comfortable pacing" in rig.tts.openai_instructions


def test_busy_audio_defers_changes_until_safe_boundary(rig):
    rig.busy[0] = True
    rig.page._on_save()
    assert rig.runtime._pending and not hasattr(rig.tts, "provider")
    rig.busy[0] = False
    rig.mic.acquire()
    assert not rig.runtime.apply_audio()
    rig.mic.release()
    assert rig.runtime.apply_audio()
    assert not rig.runtime._pending


def test_provider_without_engine_or_key_is_not_ready(rig):
    rig.page._tts_provider_combo.setCurrentText("windows")
    rig.page._on_save()
    assert not rig.tts.enabled


def test_browser_switch_and_clearing_path_work(rig):
    rig.page._browser_combo.setCurrentText("chrome")
    assert rig.page._browser_path_input.text() == "C:/chrome.exe"
    rig.page._browser_combo.setCurrentText("edge")
    assert rig.page._browser_path_input.text() == "C:/edge.exe"
    rig.page._browser_path_input.clear()
    rig.page._on_save()
    assert "edge" not in rig.settings.browser_paths
    assert "edge" not in JarvisSettings.load(rig.page._settings_path).browser_paths


def test_blank_model_resets_and_screen_model_tracks_save(rig):
    rig.page._model_input.setText("fixture-vision")
    rig.page._on_save()
    assert rig.ai.model == rig.screen.sharing.ai.model == "fixture-vision"
    assert rig.screen.model_label.text() == "fixture-vision"
    rig.page._model_input.clear()
    rig.page._on_save()
    assert rig.ai.model == rig.screen.sharing.ai.model == DEFAULT_MODEL


def test_personality_and_packs_affect_text_prompt(rig):
    rig.settings.personalization.update({"personality": {"preset": "engineer", "humor": 0, "detail": 2}, "address_name": "Test Name", "role_packs": ["business"]})
    prompt = rig.settings.response_language_instruction()
    assert "Test Name" in prompt
    assert "terse and exact" in prompt and "Use no humor" in prompt
    assert "thorough, well-structured" in prompt
    assert "gmail_search" in prompt and "Gaming:" not in prompt


def test_stop_prevents_deferred_apply(rig):
    rig.busy[0] = True
    rig.runtime.saved()
    rig.runtime.stop()
    rig.busy[0] = False
    assert not rig.runtime.apply_audio()


def test_custom_voice_delivery_is_preserved(rig):
    rig.settings.openai["text_to_speech_instructions"] = "Speak calmly, with short pauses."
    rig.runtime.saved()
    assert rig.tts.openai_instructions == "Speak calmly, with short pauses."


def test_browser_persistence_error_stays_visible(rig, monkeypatch):
    rig.settings.preferred_browser = "edge"
    rig.page._browser_path_input.clear()
    monkeypatch.setattr(rig.settings, "save", MagicMock(side_effect=OSError("fixture")))
    rig.runtime.saved()
    assert "Could not save cleared browser path" in rig.page._status_label.text()
