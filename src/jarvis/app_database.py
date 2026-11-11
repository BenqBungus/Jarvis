from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .processes import background_process_options, powershell_command


APP_INDEX_PATH = Path("data/app_index.json")


@dataclass(frozen=True)
class AppEntry:
    name: str
    app_id: str


class AppDatabase:
    def __init__(self, path: Path = APP_INDEX_PATH) -> None:
        self.path = path

    def load(self) -> list[AppEntry]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return [AppEntry(name=str(row["name"]), app_id=str(row["app_id"])) for row in data]

    def find(self, query: str) -> AppEntry | None:
        query = query.strip().lower()
        if not query:
            return None
        entries = self.load()
        exact = [entry for entry in entries if entry.name.lower() == query]
        if exact:
            return exact[0]
        starts = [entry for entry in entries if entry.name.lower().startswith(query)]
        if starts:
            return sorted(starts, key=lambda entry: len(entry.name))[0]
        contains = [entry for entry in entries if query in entry.name.lower()]
        if contains:
            return sorted(contains, key=lambda entry: len(entry.name))[0]
        return None

    def refresh(self) -> list[AppEntry]:
        script = """
Get-StartApps |
Sort-Object Name |
Select-Object Name, AppID |
ConvertTo-Json -Compress
""".strip()
        completed = subprocess.run(
            powershell_command(script),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **background_process_options(),
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Get-StartApps failed").strip())
        raw = (completed.stdout or "").strip()
        if not raw:
            entries: list[AppEntry] = []
        else:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            entries = [
                AppEntry(name=str(row["Name"]), app_id=str(row["AppID"]))
                for row in data
                if row.get("Name") and row.get("AppID")
            ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([asdict(entry) for entry in entries], file, ensure_ascii=False, indent=2)
            file.write("\n")
        return entries
