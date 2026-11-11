from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location("history_repair", Path(__file__).resolve().parents[1] / "tools/repair_test_conversation.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def turn(role, text, delta=0, day=6):
    stamp = datetime(2026, 9, day, tzinfo=timezone.utc) + timedelta(seconds=delta)
    return {"role": role, "content": text, "created_at": stamp.isoformat()}


def test_repair_only_matches_known_fixture_date_and_exact_assistant_text():
    records = [turn("user", "A real question"), turn("assistant", "A real reply"),
               turn("user", "помниш ли любим браузър"), turn("assistant", "memory_count=0", 1),
               turn("assistant", "memory_count=0", day=7), turn("user", "memory_count=0")]
    assert repair.fixture_indexes(records) == {2, 3}


def test_repair_keeps_unrelated_or_old_user_turn_before_fixture():
    assert repair.fixture_indexes([turn("user", "A real question"), turn("assistant", "memory_count=0", 1)]) == {1}
    assert repair.fixture_indexes([turn("user", "помниш ли любим браузър"), turn("assistant", "memory_count=0", 10)]) == {1}


def test_repair_preview_does_not_write_and_apply_backs_up_original_bytes(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    real = turn("user", "Real speech")
    original = "".join(json.dumps(r) + "\n" for r in (real, turn("assistant", "memory_count=0"))).encode()
    path.write_bytes(original)
    monkeypatch.setattr(repair, "HISTORY", path)
    monkeypatch.setattr(repair, "ROOT", tmp_path)
    repair.repair()
    assert path.read_bytes() == original
    assert not (tmp_path / "data").exists()
    repair.repair(apply=True)
    assert json.loads(path.read_text()) == real
    backups = list((tmp_path / "data/development-backups").glob("*.jsonl"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
