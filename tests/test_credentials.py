import os
from unittest.mock import Mock

import pytest

from jarvis.credentials import TARGET, load_api_key, remove_api_key, save_api_key


def test_credentials_roundtrip_uses_current_user_store(monkeypatch):
    import win32cred
    write = Mock()
    monkeypatch.setattr(win32cred, "CredWrite", write)
    value = "sk-example-not-a-real-credential"
    save_api_key(value)
    payload = write.call_args.args[0]
    assert payload["TargetName"] == TARGET
    assert payload["CredentialBlob"] == value.encode("utf-16-le")
    assert payload["Persist"] == win32cred.CRED_PERSIST_LOCAL_MACHINE
    monkeypatch.setattr(win32cred, "CredRead", lambda *a: payload)
    assert load_api_key() == value


def test_missing_credential_is_not_a_startup_error(monkeypatch):
    import win32cred
    import pywintypes
    monkeypatch.setattr(win32cred, "CredRead", Mock(side_effect=pywintypes.error(1168, "CredRead", "Not found")))
    assert load_api_key() == ""
    monkeypatch.setattr(win32cred, "CredDelete", Mock(side_effect=pywintypes.error(1168, "CredDelete", "Not found")))
    remove_api_key()


@pytest.mark.parametrize("value", ["", "not-a-key", "sk-too short", "sk-" + "x" * 1025])
def test_invalid_key_does_not_touch_credential_store(value, monkeypatch):
    import win32cred
    write = Mock()
    monkeypatch.setattr(win32cred, "CredWrite", write)
    with pytest.raises(ValueError):
        save_api_key(value)
    write.assert_not_called()


def test_key_page_saves_without_terminal_and_never_displays_secret(qapp, monkeypatch):
    from jarvis.gui.first_run_wizard import _ApiKeyPage
    save = Mock()
    monkeypatch.setattr("jarvis.credentials.save_api_key", save)
    page = _ApiKeyPage()
    value = "sk-example-not-a-real-credential"
    page._key_input.setText(value)
    page._save_key()
    save.assert_called_once_with(value)
    assert page._key_input.text() == ""
    assert value not in page._status_label.text()
    assert os.environ["OPENAI_API_KEY"] == value
    monkeypatch.setattr("jarvis.credentials.remove_api_key", Mock())
    page._remove_key()
    assert "OPENAI_API_KEY" not in os.environ


def test_key_page_does_not_claim_saved_on_error(qapp, monkeypatch):
    from jarvis.gui.first_run_wizard import _ApiKeyPage
    monkeypatch.setattr("jarvis.credentials.save_api_key", Mock(side_effect=OSError("private details")))
    page = _ApiKeyPage()
    page._key_input.setText("sk-example-not-a-real-credential")
    page._save_key()
    assert not page.is_configured()
    assert "Could not save" in page._status_label.text()
    assert "private details" not in page._status_label.text()


def test_loader_respects_test_disable_and_environment_priority(monkeypatch):
    from jarvis.config import ensure_openai_api_key_visible
    read = Mock(return_value="sk-example-not-a-real-credential")
    monkeypatch.setattr("jarvis.credentials.load_api_key", read)
    monkeypatch.setenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "0")
    assert not ensure_openai_api_key_visible()
    read.assert_not_called()
    monkeypatch.setenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "1")
    assert ensure_openai_api_key_visible()
    assert os.environ["OPENAI_API_KEY"] == read.return_value
    os.environ.pop("OPENAI_API_KEY", None)
