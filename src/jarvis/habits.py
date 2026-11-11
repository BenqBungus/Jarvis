"""Learned habits: repeated actions become suggestions, accepted ones become
routines that ask before they run.

X3 of docs/claude/PERSONALIZATION_HANDOFF.md, built by Claude on the user's
decision of 2026-09-25. Learns from the audit log (logs/audit.jsonl), one
profile at a time; decisions live in that profile's habits.json. Nothing
runs by itself: a due routine is offered on the HUD and runs only when the
person presses Run, through the command executor and its confirmations.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import AUDIT_LOG_PATH

WINDOW_DAYS = 14
MIN_DAYS = 3
TIME_TOLERANCE = 45  # minutes either side of the usual time
MERGE_TOLERANCE = 15  # habits this close in time, on the same days, become one routine
DUE_WINDOW = 10  # minutes after its time a routine is still offered
MAX_SUGGESTIONS = 3
_SKIP_SOURCES = ("routine", "memory")  # a routine's own runs and memory browsing teach nothing
_MODES = {"quiet": ("Quiet mode", "Quiet mode"), "study": ("Study mode", "режим учене"),
          "battery": ("Battery Saver", "режим батерия"), "gaming": ("Gaming mode", "режим игра")}


@dataclass(frozen=True)
class Observation:
    when: datetime  # local time
    key: str  # what was done, e.g. "open:discord"
    kind: str  # routine | volume | mode
    verb: str  # "open", "volume", "mode"
    label: str  # "Discord", "30%", "Gaming mode"
    label_bg: str
    action: dict  # how to repeat it: {"command": ...} or {"tool": ..., "arguments": {...}}


def _part_of_day(minutes: int) -> str:
    hour = minutes // 60
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 18:
        return "Afternoon"
    return "Evening" if 18 <= hour < 23 else "Night"


def _join(items: list[str], word: str) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1]


def observation_from(record: dict, local_tz=None) -> Observation | None:
    """What a successful audit record teaches, if anything."""
    if not record.get("ok") or record.get("dry_run"):
        return None
    source = str(record.get("source") or "")
    if source.endswith(_SKIP_SOURCES):
        return None
    try:
        when = datetime.fromisoformat(str(record.get("timestamp", "")).replace("Z", "+00:00")).astimezone(local_tz)
    except ValueError:
        return None
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    arguments = metadata.get("tool_arguments") if isinstance(metadata.get("tool_arguments"), dict) else {}
    action = str(record.get("action") or "")
    if action == "open_target" and isinstance(metadata.get("open_target"), str):
        target = metadata["open_target"].strip()
        if not target or len(target) > 60:
            return None
        label = target[:1].upper() + target[1:]
        return Observation(when, f"open:{target.lower()}", "routine", "open", label, label,
                           {"command": f"отвори {target}"})
    if action in {"open_application", "launch_installed_app"} and arguments:
        name = next((str(value) for value in arguments.values() if isinstance(value, str) and value.strip()), "")
        if name:
            return Observation(when, f"open:{name.lower()}", "routine", "open", name, name,
                               {"tool": action, "arguments": arguments})
    if action == "open_url" and isinstance(arguments.get("url"), str):
        host = urlparse(arguments["url"]).netloc.lower().removeprefix("www.")
        if host:
            return Observation(when, f"open:{host}", "routine", "open", host, host,
                               {"tool": "open_url", "arguments": {"url": arguments["url"]}})
    if action == "open_nitrosense":
        return Observation(when, "open:nitrosense", "routine", "open", "NitroSense", "NitroSense",
                           {"tool": "open_nitrosense", "arguments": {}})
    if action == "set_volume" and isinstance(arguments.get("percent"), int):
        percent = max(0, min(100, round(arguments["percent"] / 5) * 5))
        return Observation(when, f"volume:{percent}", "volume", "volume", f"{percent}%", f"{percent}%",
                           {"tool": "set_volume", "arguments": {"percent": percent}})
    if action in {"apply_mode", "game_mode"}:
        mode = "gaming" if action == "game_mode" else str(arguments.get("mode") or "").lower()
        if mode in _MODES:
            return Observation(when, f"mode:{mode}", "mode", "mode", _MODES[mode][0], _MODES[mode][1],
                               {"tool": action, "arguments": arguments})
    return None


class HabitLearner:
    def __init__(self, dir_for: Callable[[str], Path], *, audit_path: Path = AUDIT_LOG_PATH,
                 primary_id: str = "", clock: Callable[[], datetime] | None = None, local_tz=None) -> None:
        self._dir_for = dir_for
        self.audit_path = Path(audit_path)
        self.primary_id = primary_id
        self.profile_id = primary_id  # the active profile (gui/profile_wiring.py)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._tz = local_tz
        self._last: dict[str, dict[str, dict]] = {}

    # ---------------------------------------------------------- learning

    def observations(self, profile_id: str | None = None, now: datetime | None = None) -> list[Observation]:
        profile_id = profile_id or self.profile_id
        now = now or self._clock()
        since = now - timedelta(days=WINDOW_DAYS)
        found = []
        try:
            handle = self.audit_path.open(encoding="utf-8")
        except OSError:
            return []
        with handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
                owner = metadata.get("profile_id") or self.primary_id
                if owner != profile_id:
                    continue
                observation = observation_from(record, self._tz)
                if observation is not None and since <= observation.when <= now:
                    found.append(observation)
        return found

    def suggestions(self, profile: dict | str | None = None, now: datetime | None = None) -> list[dict]:
        """New habits worth offering to this profile (none for Guests or when
        learning is off), minus accepted, dismissed and snoozed ones."""
        if isinstance(profile, dict):
            if not profile.get("learn_habits", True) or profile.get("permission_level") == "guest":
                return []
            profile_id = str(profile.get("id") or self.profile_id)
        else:
            profile_id = profile or self.profile_id
        now = now or self._clock()
        found = self._find(self.observations(profile_id, now))
        decisions = self._load(profile_id)
        snoozed = {key for key, until in decisions["snoozed"].items() if until > now.isoformat()}
        hidden = set(decisions["routines"]) | set(decisions["dismissed"]) | snoozed
        fresh = [suggestion for suggestion in found if suggestion["id"] not in hidden][:MAX_SUGGESTIONS]
        self._last[profile_id] = {suggestion["id"]: suggestion for suggestion in found}
        return fresh

    def _find(self, observations: list[Observation]) -> list[dict]:
        groups: dict[str, list[Observation]] = {}
        for observation in observations:
            groups.setdefault(observation.key, []).append(observation)
        candidates = []
        for key, items in groups.items():
            cluster = self._time_cluster(items)
            if cluster is not None:
                candidates.append({"minute": cluster[0], "days": cluster[1], "items": items, "kind": items[0].kind})
        candidates.sort(key=lambda item: item["minute"])
        merged: list[dict] = []
        for candidate in candidates:
            target = next((group for group in merged if group["kind"] != "volume" and candidate["kind"] != "volume"
                           and abs(group["minute"] - candidate["minute"]) <= MERGE_TOLERANCE
                           and len(group["days"] & candidate["days"]) >= MIN_DAYS), None)
            if target is None:
                merged.append({"minute": candidate["minute"], "days": set(candidate["days"]),
                               "parts": [candidate], "kind": candidate["kind"]})
            else:
                target["parts"].append(candidate)
                target["days"] &= candidate["days"]
                target["kind"] = "routine"
        suggestions = [self._suggestion(group) for group in merged]
        return sorted(suggestions, key=lambda item: (-item["confidence"], item["trigger"]["time"]))

    @staticmethod
    def _time_cluster(items: list[Observation]) -> tuple[int, set[date]] | None:
        times = [(item.when.date(), item.when.hour * 60 + item.when.minute) for item in items]
        best: tuple[int, set[date]] | None = None
        for _day, center in times:
            days = {day for day, minute in times if abs(minute - center) <= TIME_TOLERANCE}
            if best is None or len(days) > len(best[1]):
                best = (center, days)
        if best is None or len(best[1]) < MIN_DAYS:
            return None
        members = [minute for _day, minute in times if abs(minute - best[0]) <= TIME_TOLERANCE]
        median = int(round(statistics.median(members) / 5) * 5) % (24 * 60)
        return median, best[1]

    @staticmethod
    def _suggestion(group: dict) -> dict:
        minute = group["minute"]
        clock = f"{minute // 60:02d}:{minute % 60:02d}"
        part = _part_of_day(minute)
        samples = [candidate["items"][-1] for candidate in group["parts"]]
        opens = [item for item in samples if item.verb == "open"]
        modes = [item for item in samples if item.verb == "mode"]
        volumes = [item for item in samples if item.verb == "volume"]
        phrases, phrases_bg = [], []
        for item in modes:
            phrases.append(f"switch on {item.label}")
            phrases_bg.append(f"пускаш {item.label_bg}")
        if opens:
            phrases.append("open " + _join([item.label for item in opens], "and"))
            phrases_bg.append("отваряш " + _join([item.label_bg for item in opens], "и"))
        for item in volumes:
            phrases.append(f"set the volume to {item.label}")
            phrases_bg.append(f"слагаш звука на {item.label_bg}")
        if any(item.key == "mode:gaming" for item in modes):
            title = f"Gaming {part.lower()}"
        elif group["kind"] == "volume":
            title = f"{part} volume"
        else:
            title = f"{part} routine"
        days = len(group["days"])
        sentence_bg = _join(phrases_bg, "и")
        keys = sorted(item.key for item in samples)
        digest = hashlib.sha1(f"{group['kind']}|{'|'.join(keys)}|{clock}".encode("utf-8")).hexdigest()[:10]
        return {
            "id": f"h-{digest}",
            "title": title,
            "detail": f"You {_join(phrases, 'and')} most days around {clock}.",
            "detail_bg": f"{sentence_bg[:1].upper()}{sentence_bg[1:]} почти всеки ден около {clock}.",
            "kind": group["kind"],
            "trigger": {"time": clock, "days": "daily"},
            "actions": [item.action for item in samples],
            "confidence": round(min(1.0, days / 7), 2),
            "evidence": f"Seen on {days} days in the last {WINDOW_DAYS} days",
        }

    # --------------------------------------------------------- decisions

    def accept(self, habit_id: str, profile_id: str | None = None) -> dict | None:
        profile_id = profile_id or self.profile_id
        suggestion = self._last.get(profile_id, {}).get(habit_id)
        if suggestion is None:
            return None
        decisions = self._load(profile_id)
        routine = {**suggestion, "accepted_at": self._clock().isoformat()}
        decisions["routines"][habit_id] = routine
        decisions["snoozed"].pop(habit_id, None)
        self._save(profile_id, decisions)
        return routine

    def dismiss(self, habit_id: str, profile_id: str | None = None) -> None:
        profile_id = profile_id or self.profile_id
        decisions = self._load(profile_id)
        if habit_id not in decisions["dismissed"]:
            decisions["dismissed"].append(habit_id)
        decisions["snoozed"].pop(habit_id, None)
        self._save(profile_id, decisions)

    def snooze(self, habit_id: str, days: int = 7, profile_id: str | None = None) -> None:
        profile_id = profile_id or self.profile_id
        decisions = self._load(profile_id)
        decisions["snoozed"][habit_id] = (self._clock() + timedelta(days=days)).isoformat()
        self._save(profile_id, decisions)

    def routines(self, profile_id: str | None = None) -> list[dict]:
        return list(self._load(profile_id or self.profile_id)["routines"].values())

    def remove_routine(self, routine_id: str, profile_id: str | None = None) -> None:
        profile_id = profile_id or self.profile_id
        decisions = self._load(profile_id)
        decisions["routines"].pop(routine_id, None)
        self._save(profile_id, decisions)

    def due_routines(self, profile_id: str | None = None, now: datetime | None = None) -> list[dict]:
        """Routines whose time came in the last few minutes and that were not
        offered today yet."""
        profile_id = profile_id or self.profile_id
        now = now or self._clock()
        decisions = self._load(profile_id)
        minute = now.hour * 60 + now.minute
        due = []
        for routine_id, routine in decisions["routines"].items():
            hour, _, rest = str(routine.get("trigger", {}).get("time", "")).partition(":")
            if not (hour.isdigit() and rest.isdigit()):
                continue
            start = int(hour) * 60 + int(rest)
            if 0 <= minute - start <= DUE_WINDOW and decisions["offered"].get(routine_id) != now.date().isoformat():
                due.append(routine)
        return due

    def mark_offered(self, routine_id: str, profile_id: str | None = None, now: datetime | None = None) -> None:
        profile_id = profile_id or self.profile_id
        decisions = self._load(profile_id)
        decisions["offered"][routine_id] = (now or self._clock()).date().isoformat()
        self._save(profile_id, decisions)

    # ------------------------------------------------------------ storage

    def _file(self, profile_id: str) -> Path:
        return Path(self._dir_for(profile_id)) / "habits.json"

    def _load(self, profile_id: str) -> dict:
        data: dict[str, Any] = {}
        try:
            data = json.loads(self._file(profile_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not isinstance(data, dict):
            data = {}
        return {"routines": data.get("routines") if isinstance(data.get("routines"), dict) else {},
                "dismissed": data.get("dismissed") if isinstance(data.get("dismissed"), list) else [],
                "snoozed": data.get("snoozed") if isinstance(data.get("snoozed"), dict) else {},
                "offered": data.get("offered") if isinstance(data.get("offered"), dict) else {}}

    def _save(self, profile_id: str, decisions: dict) -> None:
        path = self._file(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
