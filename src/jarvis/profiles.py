"""Profiles: everyone in the house gets their own Jarvis.

X1 of docs/claude/PERSONALIZATION_HANDOFF.md, built by Claude on the user's
decision of 2026-09-25. The records live in data/profiles/profiles.json and
each profile's avatar, habits and memory in data/profiles/<id>/. The first
profile is migrated from settings.personalization and keeps using the
existing data/ memory files, so nothing already remembered moves or is lost.

The adult PIN is stored only as a salted PBKDF2 hash.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
import zlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CommandResult
from .personality import normalize as normalize_personality
from .role_packs import normalize_packs

PROFILES_ROOT = Path("data/profiles")
LEVELS = ("adult", "kid", "guest")
LANGUAGES = ("en", "bg", "auto")
FIELDS = frozenset({"display_name", "avatar", "avatar_hue", "windows_user", "language", "personality",
                    "role_packs", "permission_level", "learn_habits", "voice"})
AVATAR_FILE = "avatar.png"
MAX_AVATAR_BYTES = 2 * 1024 * 1024
PIN_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 60
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
    "ё": "yo", "ы": "y", "э": "e",
})


class ProfileError(ValueError):
    """A change the store refuses; the message is safe to show."""


def _slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.strip().lower().translate(_TRANSLIT)).strip("-")
    return text[:24].strip("-") or "profile"


def default_hue(name: str) -> int:
    """The same default as gui/avatar.hue_for, without importing Qt."""
    return zlib.crc32((name or "").strip().lower().encode("utf-8")) % 360


class ProfileStore:
    def __init__(self, root: Path | str = PROFILES_ROOT, *, settings: Any = None,
                 windows_user: str | None = None) -> None:
        self.root = Path(root)
        self._path = self.root / "profiles.json"
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
        self._failed_pins = 0
        self._locked_until = 0.0
        self.pin_iterations = 200_000
        self.windows_user = windows_user if windows_user is not None else os.environ.get("USERNAME", "")
        self._data = self._load(settings)
        self._select_startup_profile()

    # ------------------------------------------------------------- reading

    def list_profiles(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._data["profiles"])

    def get(self, profile_id: str) -> dict | None:
        with self._lock:
            profile = self._find(profile_id)
            return copy.deepcopy(profile) if profile is not None else None

    def active(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._find(self._data["active"]))

    @property
    def active_id(self) -> str:
        return self._data["active"]

    @property
    def primary_id(self) -> str:
        return self._data["primary"]

    def is_primary(self, profile_id: str) -> bool:
        return profile_id == self._data["primary"]

    def profile_dir(self, profile_id: str) -> Path:
        return self.root / profile_id

    def memory_dir(self, profile_id: str) -> Path | None:
        """Where this profile's memory lives; None = the original data/ files."""
        return None if self.is_primary(profile_id) else self.profile_dir(profile_id) / "memory"

    def avatar_path(self, profile_id: str) -> Path | None:
        profile = self._find(profile_id)
        if profile is None or not profile.get("avatar"):
            return None
        path = self.profile_dir(profile_id) / AVATAR_FILE
        return path if path.is_file() else None

    def avatar_paths(self) -> dict[str, Path | None]:
        return {profile["id"]: self.avatar_path(profile["id"]) for profile in self.list_profiles()}

    def has_pin(self) -> bool:
        return bool(self._data.get("pin"))

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    # ------------------------------------------------------------- changes

    def create(self, display_name: str, **fields: Any) -> dict:
        with self._lock:
            name = self._clean({"display_name": display_name}, None)["display_name"]
            record = self._new_record(name)
            record.update(self._clean(fields, record))
            self._enforce(record)
            self._data["profiles"].append(record)
            self._rebind_windows_user(record)
            self.profile_dir(record["id"]).mkdir(parents=True, exist_ok=True)
            self._save()
            created = copy.deepcopy(record)
        self._notify()
        return created

    def update(self, profile_id: str, changes: dict) -> dict:
        with self._lock:
            profile = self._require(profile_id)
            cleaned = self._clean(dict(changes or {}), profile)
            candidate = {**profile, **cleaned}
            self._enforce(candidate, previous=profile)
            if cleaned.get("avatar") == "":
                (self.profile_dir(profile_id) / AVATAR_FILE).unlink(missing_ok=True)
            profile.update(cleaned)
            if profile["permission_level"] == "guest":
                profile["learn_habits"] = False
            self._rebind_windows_user(profile)
            self._save()
            updated = copy.deepcopy(profile)
        self._notify()
        return updated

    def delete(self, profile_id: str) -> None:
        """Removes a profile from Jarvis. Its folder moves to data/profiles/.deleted,
        so nothing is destroyed by accident."""
        with self._lock:
            profile = self._require(profile_id)
            if profile["permission_level"] == "adult" and self._adult_count() == 1:
                raise ProfileError("Jarvis needs at least one adult profile.")
            if self.is_primary(profile_id):
                raise ProfileError("The first profile keeps Jarvis's original memory and cannot be deleted.")
            self._data["profiles"] = [item for item in self._data["profiles"] if item["id"] != profile_id]
            if self._data["active"] == profile_id:
                self._data["active"] = self._data["primary"]
            folder = self.profile_dir(profile_id)
            if folder.exists():
                target = self.root / ".deleted" / f"{profile_id}-{datetime.now():%Y%m%d-%H%M%S}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(folder), str(target))
            self._save()
        self._notify()

    def set_avatar(self, profile_id: str, png: bytes) -> Path:
        if not isinstance(png, (bytes, bytearray)) or not bytes(png).startswith(_PNG_SIGNATURE):
            raise ProfileError("The avatar must be a PNG image.")
        if len(png) > MAX_AVATAR_BYTES:
            raise ProfileError("The avatar image is larger than 2 MB.")
        with self._lock:
            profile = self._require(profile_id)
            folder = self.profile_dir(profile_id)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / AVATAR_FILE
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(bytes(png))
            os.replace(temporary, path)
            profile["avatar"] = AVATAR_FILE
            self._save()
        self._notify()
        return path

    def set_pin(self, pin: str) -> None:
        if not self._valid_pin(pin):
            raise ProfileError("The adult PIN must be 4 to 8 digits.")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, self.pin_iterations)
        with self._lock:
            self._data["pin"] = {"salt": salt.hex(), "hash": digest.hex(), "iterations": self.pin_iterations}
            self._failed_pins = 0
            self._locked_until = 0.0
            self._save()

    def check_pin(self, pin: str | None) -> bool:
        stored = self._data.get("pin")
        if not stored:
            return True
        if not isinstance(pin, str) or not self._valid_pin(pin):
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), bytes.fromhex(stored["salt"]),
                                     int(stored.get("iterations", self.pin_iterations)))
        return hmac.compare_digest(digest.hex(), stored["hash"])

    def switch(self, profile_id: str, pin: str | None = None) -> CommandResult:
        with self._lock:
            target = self._find(profile_id)
            if target is None:
                return CommandResult(False, "There is no such profile.")
            name = target["display_name"]
            if target["id"] == self._data["active"]:
                return CommandResult(True, f"{name} is already active.", metadata={"profile_id": target["id"]})
            current = self._find(self._data["active"])
            if current["permission_level"] != "adult" and target["permission_level"] == "adult" and self.has_pin():
                now = time.monotonic()
                if now < self._locked_until:
                    return CommandResult(False, "Too many wrong PINs. Try again in a minute.",
                                         metadata={"pin_required": True, "locked": True})
                if pin is None:
                    return CommandResult(False, f"The adult PIN is needed to switch to {name}.",
                                         metadata={"pin_required": True})
                if not self.check_pin(pin):
                    self._failed_pins += 1
                    if self._failed_pins >= PIN_ATTEMPTS:
                        self._failed_pins = 0
                        self._locked_until = now + PIN_LOCKOUT_SECONDS
                    return CommandResult(False, "That PIN is not right.", metadata={"pin_required": True, "pin_wrong": True})
            self._failed_pins = 0
            self._data["active"] = target["id"]
            self._save()
            level = target["permission_level"]
        self._notify()
        return CommandResult(True, f"Switched to {name}.", metadata={"profile_id": profile_id, "permission_level": level})

    # ------------------------------------------------------------ internal

    def _find(self, profile_id: str) -> dict | None:
        return next((profile for profile in self._data["profiles"] if profile["id"] == profile_id), None)

    def _require(self, profile_id: str) -> dict:
        profile = self._find(profile_id)
        if profile is None:
            raise ProfileError("There is no such profile.")
        return profile

    def _adult_count(self) -> int:
        return sum(profile["permission_level"] == "adult" for profile in self._data["profiles"])

    def _new_record(self, name: str) -> dict:
        base = _slug(name)
        taken = {profile["id"] for profile in self._data.get("profiles", [])} | {".deleted"}
        profile_id, counter = base, 2
        while profile_id in taken:
            profile_id, counter = f"{base}-{counter}", counter + 1
        return {"id": profile_id, "display_name": name, "avatar": "", "avatar_hue": default_hue(name),
                "windows_user": "", "language": "auto", "personality": normalize_personality(None),
                "role_packs": normalize_packs(None), "permission_level": "adult", "learn_habits": True, "voice": {}}

    @staticmethod
    def _valid_pin(pin: Any) -> bool:
        return isinstance(pin, str) and pin.isascii() and pin.isdigit() and 4 <= len(pin) <= 8

    def _clean(self, changes: dict, existing: dict | None) -> dict:
        unknown = sorted(set(changes) - FIELDS - {"id"})
        if unknown:
            raise ProfileError(f"Unknown profile field: {', '.join(unknown)}")
        if "id" in changes and (existing is None or changes["id"] != existing.get("id")):
            raise ProfileError("A profile's id cannot change.")
        cleaned: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "id":
                continue
            if key == "display_name":
                name = value.strip() if isinstance(value, str) else ""
                if not 1 <= len(name) <= 32:
                    raise ProfileError("A profile needs a name of up to 32 characters.")
                cleaned[key] = name
            elif key == "avatar":
                if value not in ("", (existing or {}).get("avatar")):
                    raise ProfileError("Use set_avatar() to change the avatar image.")
                cleaned[key] = value
            elif key == "avatar_hue":
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ProfileError("avatar_hue must be a whole number.")
                cleaned[key] = value % 360
            elif key == "windows_user":
                if not isinstance(value, str) or len(value.strip()) > 64:
                    raise ProfileError("windows_user must be a Windows user name.")
                cleaned[key] = value.strip()
            elif key == "language":
                if value not in LANGUAGES:
                    raise ProfileError("language must be en, bg or auto.")
                cleaned[key] = value
            elif key == "personality":
                if not isinstance(value, dict):
                    raise ProfileError("personality must be an object.")
                cleaned[key] = normalize_personality(value)
            elif key == "role_packs":
                if not isinstance(value, (list, tuple)):
                    raise ProfileError("role_packs must be a list.")
                cleaned[key] = normalize_packs(list(value))
            elif key == "permission_level":
                if value not in LEVELS:
                    raise ProfileError("permission_level must be adult, kid or guest.")
                cleaned[key] = value
            elif key == "learn_habits":
                if not isinstance(value, bool):
                    raise ProfileError("learn_habits must be true or false.")
                cleaned[key] = value
            elif key == "voice":
                if not isinstance(value, dict):
                    raise ProfileError("voice must be an object.")
                voice = value.get("live_voice")
                cleaned[key] = ({"live_voice": voice} if isinstance(voice, str) and re.fullmatch(r"[a-z]{2,24}", voice)
                                else {})
        return cleaned

    def _enforce(self, candidate: dict, previous: dict | None = None) -> None:
        if (previous is not None and previous["permission_level"] == "adult"
                and candidate["permission_level"] != "adult" and self._adult_count() == 1):
            raise ProfileError("Jarvis needs at least one adult profile.")
        if candidate["permission_level"] != "adult" and self.is_primary(candidate["id"]):
            raise ProfileError("The first profile stays an adult profile.")
        if candidate["permission_level"] == "guest":
            candidate["learn_habits"] = False

    def _rebind_windows_user(self, profile: dict) -> None:
        """One Windows account chooses one profile: the newest binding wins."""
        user = profile.get("windows_user", "").lower()
        if not user:
            return
        for other in self._data["profiles"]:
            if other is not profile and other.get("windows_user", "").lower() == user:
                other["windows_user"] = ""

    def _select_startup_profile(self) -> None:
        """The profile bound to this Windows account, unless that would skip the
        adult PIN (a Kid or Guest was last active); else the last active one."""
        with self._lock:
            active = self._find(self._data.get("active", "")) or self._find(self._data["primary"])
            bound = next((profile for profile in self._data["profiles"] if self.windows_user
                          and profile.get("windows_user", "").lower() == self.windows_user.lower()), None)
            if bound is not None and not (active["permission_level"] != "adult"
                                          and bound["permission_level"] == "adult" and self.has_pin()):
                active = bound
            if self._data.get("active") != active["id"]:
                self._data["active"] = active["id"]
                self._save()

    def _load(self, settings: Any) -> dict:
        if self._path.is_file():
            try:
                data = self._repair(json.loads(self._path.read_text(encoding="utf-8")))
                if data is not None:
                    return data
            except (OSError, ValueError):
                pass
            backup = self._path.with_name(f"profiles.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                self._path.replace(backup)
            except OSError:
                pass
        return self._migrate(settings)

    def _repair(self, data: Any) -> dict | None:
        """The stored data with any field a newer version added filled in;
        None when it is unusable."""
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
            return None
        profiles = []
        self._data = {"profiles": []}
        for raw in data["profiles"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw.get("display_name"):
                continue
            record = {**self._new_record(str(raw["display_name"])), "id": raw["id"]}
            record.update({key: value for key, value in raw.items() if key in FIELDS})
            profiles.append(record)
        ids = {profile["id"] for profile in profiles}
        if data.get("primary") not in ids:
            return None
        return {"version": 1, "primary": data["primary"], "active": data.get("active") or data["primary"],
                "pin": data.get("pin") if isinstance(data.get("pin"), dict) else None, "profiles": profiles}

    def _migrate(self, settings: Any) -> dict:
        """The first profile: today's settings and name, bound to this Windows account."""
        personalization = dict(getattr(settings, "personalization", {}) or {})
        name = str(personalization.get("address_name") or self.windows_user or "Me").strip()[:32] or "Me"
        language = getattr(settings, "conversation_language", None)
        if language not in LANGUAGES:
            language = (getattr(settings, "openai", {}) or {}).get("conversation_language", "auto")
        self._data = {"version": 1, "primary": "", "active": "", "pin": None, "profiles": []}
        record = self._new_record(name)
        record.update({
            "windows_user": self.windows_user,
            "language": language if language in LANGUAGES else "auto",
            "personality": normalize_personality(personalization.get("personality")),
            "role_packs": normalize_packs(personalization.get("role_packs")),
        })
        self._data.update({"primary": record["id"], "active": record["id"], "profiles": [record]})
        self.profile_dir(record["id"]).mkdir(parents=True, exist_ok=True)
        self._save()
        return self._data

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()
