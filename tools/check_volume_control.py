"""Check Core Audio on a worker thread; optionally reapply the current, unmuted level."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from jarvis.volume import _endpoint_volume, get_master_volume_percent
from jarvis.windows_actions import WindowsActions


def check(write: bool) -> dict:
    level = get_master_volume_percent()
    with _endpoint_volume() as endpoint:
        muted = bool(endpoint.GetMute())
    result = {"worker_read_ok": True, "within_range": 0 <= level <= 100, "write_check": "not_requested"}
    if write and not muted:
        actions = WindowsActions()
        actions._record_rollback = False
        applied = actions.set_volume(level)
        result.update(write_check="passed" if applied.ok else "failed", verification=applied.metadata.get("verification"))
        if not applied.ok:
            raise RuntimeError(applied.message)
    elif write:
        result["write_check"] = "skipped_to_preserve_mute"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--same-level", action="store_true")
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=1) as pool:
        print(pool.submit(check, args.same_level).result(timeout=15))
