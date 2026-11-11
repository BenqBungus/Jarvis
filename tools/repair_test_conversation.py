"""One-time repair of known September 6 test fixtures, with backup and preview."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data/conversation_history.jsonl"
FIXTURE_REPLIES = {
    "chat: скучно ми е", "chat: скучно ми е и не знам какво да правя",
    "chat: помниш ли любим браузър / memory=Preferred browser is Opera GX",
    "memory_count=0", "web: latest nvidia drivers",
}
for model in ("gpt-5.6-sol", "gpt-5.6-terra"):
    FIXTURE_REPLIES.add(f"Would ask {model} with web search: какво е инфлация")
    for query in ("последните новини за nvidia", "rtx 4060 и rtx 4070"):
        for source in ("Search result - https://example.com/result", "RTX comparison - https://example.com/rtx"):
            FIXTURE_REPLIES.add(f"Would research with {model}: {query}\n\nSources:\n1. {source}\n\n"
                               "Say 'отвори първия' or 'прочети втория' to continue from these results.")
FIXTURE_QUESTIONS = {"май ми е скучно", "скучно ми е и не знам какво да правя", "помниш ли любим браузър",
                     "би ли проверил актуални новини за amd", "какво е инфлация",
                     "провери в интернет последните новини за nvidia", "сравни rtx 4060 и rtx 4070"}


def fixture_indexes(records: list[dict]) -> set[int]:
    removed = set()
    for index, record in enumerate(records):
        stamp = str(record.get("created_at", ""))
        if (record.get("role") != "assistant" or record.get("content") not in FIXTURE_REPLIES
                or not stamp.startswith("2026-09-06")):
            continue
        removed.add(index)
        if not index:
            continue
        previous = records[index - 1]
        if previous.get("role") == "user" and previous.get("content") in FIXTURE_QUESTIONS:
            try:
                gap = (datetime.fromisoformat(stamp) - datetime.fromisoformat(previous["created_at"])).total_seconds()
            except (ValueError, KeyError, TypeError):
                continue
            if 0 <= gap <= 2:
                removed.add(index - 1)
    return removed


def repair(apply: bool = False) -> None:
    original = HISTORY.read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    records = [json.loads(line) for line in lines]
    removed = fixture_indexes(records)
    print(f"Known fixture records: {len(removed)}; records to preserve: {len(records) - len(removed)}")
    if not apply or not removed:
        return
    backup = ROOT / "data/development-backups" / (
        "conversation-before-repair-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".jsonl")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HISTORY, backup)
    temporary = HISTORY.with_suffix(".repair.tmp")
    temporary.write_bytes("".join(line for index, line in enumerate(lines) if index not in removed).encode("utf-8"))
    if HISTORY.read_bytes() != original:
        temporary.unlink()
        raise RuntimeError("History changed during repair; close Jarvis and retry. Nothing was replaced.")
    temporary.replace(HISTORY)
    print(f"Backup: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Close Jarvis first. Back up and remove only the known test records.")
    repair(parser.parse_args().apply)
