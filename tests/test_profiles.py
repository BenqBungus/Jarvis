"""ProfileStore (src/jarvis/profiles.py): migration, validation, avatars,
the adult PIN and switching."""
from __future__ import annotations

import json

import pytest

from jarvis.profiles import AVATAR_FILE, PIN_ATTEMPTS, ProfileError, ProfileStore
from jarvis.role_packs import DEFAULT_PACKS
from jarvis.user_settings import JarvisSettings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _store(tmp_path, **kwargs) -> ProfileStore:
    settings = kwargs.pop("settings", JarvisSettings(
        personalization={"address_name": "Берк", "personality": {"preset": "coach"}, "role_packs": ["student"]},
        openai={"conversation_language": "bg"}))
    store = ProfileStore(tmp_path / "profiles", settings=settings, windows_user=kwargs.pop("windows_user", "Berk"))
    store.pin_iterations = 1000  # fast tests; stored with the hash
    return store


def test_first_run_migrates_the_current_person(tmp_path):
    store = _store(tmp_path)
    [profile] = store.list_profiles()
    assert profile["id"] == "berk" and profile["display_name"] == "Берк"
    assert profile["personality"]["preset"] == "coach" and profile["role_packs"] == ["student"]
    assert profile["language"] == "bg" and profile["windows_user"] == "Berk"
    assert profile["permission_level"] == "adult" and store.is_primary("berk")
    assert store.memory_dir("berk") is None  # keeps the original data/ memory files
    assert json.loads((tmp_path / "profiles" / "profiles.json").read_text(encoding="utf-8"))["primary"] == "berk"


def test_fresh_settings_get_default_packs_and_a_name(tmp_path):
    store = _store(tmp_path, settings=JarvisSettings(), windows_user="")
    profile = store.active()
    assert profile["display_name"] == "Me" and profile["role_packs"] == list(DEFAULT_PACKS)


def test_create_update_and_validation(tmp_path):
    store = _store(tmp_path)
    ani = store.create("Ани", permission_level="kid", role_packs=["student", "nope"], avatar="",
                       personality={"preset": "tutor"}, voice={"live_voice": "marin", "x": 1}, language="en")
    assert ani["id"] == "ani" and ani["role_packs"] == ["student"] and ani["voice"] == {"live_voice": "marin"}
    assert store.memory_dir("ani") == tmp_path / "profiles" / "ani" / "memory"
    assert store.create("Ани")["id"] == "ani-2"
    with pytest.raises(ProfileError):
        store.create("")
    with pytest.raises(ProfileError):
        store.update("ani", {"favourite_colour": "red"})
    with pytest.raises(ProfileError):
        store.update("ani", {"language": "fr"})
    guest = store.create("Гост", permission_level="guest", learn_habits=True)
    assert guest["learn_habits"] is False
    assert store.update("ani", {"display_name": "  Ани Б  "})["display_name"] == "Ани Б"


def test_there_is_always_an_adult_and_the_first_profile_stays(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ProfileError):
        store.update("berk", {"permission_level": "kid"})
    with pytest.raises(ProfileError):
        store.delete("berk")
    assert store.create("Мама")["id"] == "mama"
    store.update("mama", {"permission_level": "kid"})  # berk is still an adult
    store.create("Гост", permission_level="guest")
    store.switch("gost")
    store.delete("gost")
    assert store.active_id == "berk" and store.get("gost") is None
    assert any((tmp_path / "profiles" / ".deleted").iterdir())  # moved, not destroyed


def test_one_windows_account_chooses_one_profile(tmp_path):
    store = _store(tmp_path)
    store.create("Мама", windows_user="berk")
    assert store.get("berk")["windows_user"] == "" and store.get("mama")["windows_user"] == "berk"


def test_avatar_must_be_a_small_png(tmp_path):
    store = _store(tmp_path)
    path = store.set_avatar("berk", PNG)
    assert path.name == AVATAR_FILE and store.avatar_path("berk") == path
    with pytest.raises(ProfileError):
        store.set_avatar("berk", b"GIF89a")
    with pytest.raises(ProfileError):
        store.set_avatar("berk", PNG + b"\x00" * (2 * 1024 * 1024))
    store.update("berk", {"avatar": ""})
    assert store.avatar_path("berk") is None and not path.exists()


def test_the_pin_is_hashed_and_guards_the_way_back_to_adults(tmp_path):
    store = _store(tmp_path)
    store.create("Ани", permission_level="kid")
    with pytest.raises(ProfileError):
        store.set_pin("12a4")
    store.set_pin("2468")
    raw = (tmp_path / "profiles" / "profiles.json").read_text(encoding="utf-8")
    assert "2468" not in raw and json.loads(raw)["pin"]["hash"]
    assert store.switch("ani").ok  # adult to kid needs nothing
    needed = store.switch("berk")
    assert not needed.ok and needed.metadata["pin_required"]
    wrong = store.switch("berk", pin="1111")
    assert not wrong.ok and wrong.metadata.get("pin_wrong")
    assert store.switch("berk", pin="2468").ok and store.active_id == "berk"


def test_too_many_wrong_pins_lock_switching_for_a_while(tmp_path):
    store = _store(tmp_path)
    store.create("Ани", permission_level="kid")
    store.set_pin("2468")
    store.switch("ani")
    for _ in range(PIN_ATTEMPTS):
        store.switch("berk", pin="0000")
    locked = store.switch("berk", pin="2468")
    assert not locked.ok and locked.metadata.get("locked")


def test_startup_picks_the_windows_users_profile_unless_that_skips_the_pin(tmp_path):
    store = _store(tmp_path)
    store.create("Ани", permission_level="kid", windows_user="ani")
    store.switch("ani")
    assert ProfileStore(tmp_path / "profiles", windows_user="Berk").active_id == "berk"
    store = ProfileStore(tmp_path / "profiles", windows_user="Berk")
    store.pin_iterations = 1000
    store.set_pin("2468")
    store.switch("ani")
    assert ProfileStore(tmp_path / "profiles", windows_user="Berk").active_id == "ani"
    assert ProfileStore(tmp_path / "profiles", windows_user="ani").active_id == "ani"


def test_an_older_or_damaged_file_is_repaired_or_set_aside(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "profiles.json").write_text(json.dumps({
        "primary": "berk", "active": "berk",
        "profiles": [{"id": "berk", "display_name": "Берк"}, {"broken": True}]}), encoding="utf-8")
    store = ProfileStore(root, windows_user="")
    assert store.active()["permission_level"] == "adult" and len(store.list_profiles()) == 1
    (root / "profiles.json").write_text("{not json", encoding="utf-8")
    store = ProfileStore(root, settings=JarvisSettings(personalization={"address_name": "Берк"}), windows_user="")
    assert store.active()["display_name"] == "Берк"
    assert list(root.glob("profiles.corrupt-*.json"))
