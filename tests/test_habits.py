"""HabitLearner (src/jarvis/habits.py): what the audit log teaches, per
profile, and how accepted routines come due."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from jarvis.habits import HabitLearner, observation_from

UTC = timezone.utc
NOW = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)


def _record(when, action, *, profile="berk", ok=True, source="gui_text", **metadata):
    return {"timestamp": when.isoformat(), "action": action, "ok": ok, "dry_run": False, "source": source,
            "metadata": {**metadata, "profile_id": profile}}


def _write(path, records):
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def _evenings(days, minute=0, **kwargs):
    return [_record(NOW - timedelta(days=day, hours=1) + timedelta(minutes=minute), **kwargs) for day in days]


def _learner(tmp_path, records):
    audit = tmp_path / "audit.jsonl"
    _write(audit, records)
    return HabitLearner(lambda profile_id: tmp_path / profile_id, audit_path=audit, primary_id="berk",
                        clock=lambda: NOW, local_tz=UTC)


def test_what_a_record_teaches():
    when = NOW
    assert observation_from(_record(when, "open_target", open_target="discord"), UTC).action == {
        "command": "отвори discord"}
    volume = observation_from(_record(when, "set_volume", tool_arguments={"percent": 32}), UTC)
    assert volume.key == "volume:30" and volume.action["arguments"] == {"percent": 30}
    assert observation_from(_record(when, "open_url", tool_arguments={"url": "https://www.plasico.bg/x"}),
                            UTC).key == "open:plasico.bg"
    assert observation_from(_record(when, "open_target", ok=False, open_target="discord"), UTC) is None
    assert observation_from(_record(when, "open_target", source="gui_routine", open_target="discord"), UTC) is None
    assert observation_from(_record(when, "remember", tool_arguments={"text": "x"}), UTC) is None


def test_the_same_apps_at_the_same_time_become_one_routine(tmp_path):
    records = (_evenings([1, 2, 3, 5], action="open_target", open_target="discord")
               + _evenings([1, 2, 3, 5], minute=4, action="open_target", open_target="steam")
               + _evenings([1, 2, 3], action="game_mode"))
    learner = _learner(tmp_path, records)
    [suggestion] = learner.suggestions({"id": "berk", "learn_habits": True, "permission_level": "adult"})
    assert suggestion["title"] == "Gaming evening" and suggestion["trigger"] == {"time": "20:00", "days": "daily"}
    assert suggestion["detail"] == "You switch on Gaming mode and open Discord and Steam most days around 20:00."
    assert suggestion["detail_bg"].startswith("Пускаш режим игра и отваряш Discord и Steam")
    assert {"command": "отвори steam"} in suggestion["actions"] and suggestion["id"].startswith("h-")


def test_two_days_or_scattered_times_are_not_a_habit(tmp_path):
    records = (_evenings([1, 2], action="open_target", open_target="discord")
               + [_record(NOW - timedelta(days=day, hours=hours), "open_target", open_target="steam")
                  for day, hours in ((1, 1), (2, 6), (3, 11))])
    assert _learner(tmp_path, records).suggestions("berk") == []


def test_habits_belong_to_one_profile_and_guests_learn_nothing(tmp_path):
    records = _evenings([1, 2, 3], action="open_target", open_target="discord", profile="ani")
    learner = _learner(tmp_path, records)
    assert learner.suggestions("berk") == []
    assert len(learner.suggestions("ani")) == 1
    assert learner.suggestions({"id": "ani", "permission_level": "guest"}) == []
    assert learner.suggestions({"id": "ani", "learn_habits": False}) == []


def test_decisions_are_remembered_per_profile(tmp_path):
    records = (_evenings([1, 2, 3], action="open_target", open_target="discord")
               + _evenings([1, 2, 3], minute=-600, action="set_volume", tool_arguments={"percent": 30}))
    learner = _learner(tmp_path, records)
    first, second = learner.suggestions("berk")
    learner.snooze(first["id"])
    learner.dismiss(second["id"])
    assert learner.suggestions("berk") == []
    stored = json.loads((tmp_path / "berk" / "habits.json").read_text(encoding="utf-8"))
    assert second["id"] in stored["dismissed"] and first["id"] in stored["snoozed"]
    learner = HabitLearner(lambda profile_id: tmp_path / profile_id, audit_path=tmp_path / "audit.jsonl",
                           primary_id="berk", clock=lambda: NOW + timedelta(days=8), local_tz=UTC)
    later = learner.suggestions("berk", now=NOW + timedelta(days=8))
    assert [item["id"] for item in later] == [first["id"]]  # "Later" asks again after a week; dismissed never


def test_an_accepted_routine_comes_due_once_a_day(tmp_path):
    learner = _learner(tmp_path, _evenings([1, 2, 3], action="open_target", open_target="discord"))
    [suggestion] = learner.suggestions("berk")
    routine = learner.accept(suggestion["id"])
    assert routine["trigger"]["time"] == "20:00" and learner.suggestions("berk") == []
    evening = datetime(2026, 9, 26, 20, 4, tzinfo=UTC)
    assert [item["id"] for item in learner.due_routines(now=evening)] == [suggestion["id"]]
    assert learner.due_routines(now=evening.replace(hour=19)) == []
    assert learner.due_routines(now=evening.replace(minute=30)) == []
    learner.mark_offered(suggestion["id"], now=evening)
    assert learner.due_routines(now=evening) == []
    learner.remove_routine(suggestion["id"])
    assert learner.routines() == []


def test_a_missing_or_damaged_log_teaches_nothing(tmp_path):
    learner = HabitLearner(lambda profile_id: tmp_path / profile_id, audit_path=tmp_path / "missing.jsonl",
                           primary_id="berk", clock=lambda: NOW)
    assert learner.suggestions("berk") == []
    (tmp_path / "audit.jsonl").write_text("{broken\n[]\n", encoding="utf-8")
    assert _learner(tmp_path, []).suggestions("berk") == []
