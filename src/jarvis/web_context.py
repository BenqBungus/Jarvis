from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


WEB_CONTEXT_PATH = Path("data/web_context.json")


@dataclass(frozen=True)
class WebCandidate:
    title: str
    url: str


@dataclass(frozen=True)
class WebPageRecord:
    title: str
    url: str
    excerpt: str = ""
    text_length: int = 0
    ordinal: int | None = None
    match_query: str = ""
    timestamp: str = ""


class WebContext:
    def __init__(self, path: Path = WEB_CONTEXT_PATH) -> None:
        self.path = path

    def save_candidates(self, candidates: list[WebCandidate], query: str) -> None:
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "candidates": [asdict(candidate) for candidate in candidates],
            "opened": [],
            "read_pages": [],
        }
        self._write_data(data)

    def load_candidates(self) -> list[WebCandidate]:
        data = self._load_data()
        return [
            WebCandidate(title=str(row["title"]), url=str(row["url"]))
            for row in data.get("candidates", [])
            if row.get("title") and row.get("url")
        ]

    def pick(self, ordinal: int) -> WebCandidate | None:
        candidates = self.load_candidates()
        index = ordinal - 1
        if index < 0 or index >= len(candidates):
            return None
        return candidates[index]

    def find(self, query: str) -> tuple[int, WebCandidate] | None:
        cleaned = query.strip().lower()
        if not cleaned:
            return None
        tokens = [token for token in re.split(r"\W+", cleaned, flags=re.UNICODE) if token]
        best: tuple[int, int, WebCandidate] | None = None
        for index, candidate in enumerate(self.load_candidates(), start=1):
            haystack = f"{candidate.title} {candidate.url}".lower()
            if cleaned in haystack:
                score = 100 + len(cleaned)
            else:
                score = sum(1 for token in tokens if token in haystack)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, index, candidate)
        if best is None:
            return None
        return (best[1], best[2])

    def record_opened(
        self,
        candidate: WebCandidate,
        *,
        ordinal: int | None = None,
        match_query: str = "",
    ) -> None:
        data = self._load_data()
        opened = data.setdefault("opened", [])
        opened.append(
            asdict(
                WebPageRecord(
                    title=candidate.title,
                    url=candidate.url,
                    ordinal=ordinal,
                    match_query=match_query,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        )
        data["opened"] = opened[-20:]
        self._write_data(data)

    def record_read(
        self,
        *,
        url: str,
        title: str = "",
        excerpt: str = "",
        text_length: int = 0,
        ordinal: int | None = None,
        match_query: str = "",
    ) -> None:
        data = self._load_data()
        read_pages = data.setdefault("read_pages", [])
        read_pages.append(
            asdict(
                WebPageRecord(
                    title=title,
                    url=url,
                    excerpt=excerpt,
                    text_length=text_length,
                    ordinal=ordinal,
                    match_query=match_query,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        )
        data["read_pages"] = read_pages[-20:]
        self._write_data(data)

    def recent_opened(self, limit: int = 10) -> list[WebPageRecord]:
        return self._load_records("opened", limit=limit)

    def recent_read_pages(self, limit: int = 10) -> list[WebPageRecord]:
        return self._load_records("read_pages", limit=limit)

    def session_summary(self) -> dict:
        data = self._load_data()
        return {
            "query": str(data.get("query", "")),
            "timestamp": str(data.get("timestamp", "")),
            "candidates": [asdict(candidate) for candidate in self.load_candidates()],
            "opened": [asdict(record) for record in self.recent_opened(limit=10)],
            "read_pages": [asdict(record) for record in self.recent_read_pages(limit=10)],
        }

    def _load_records(self, key: str, *, limit: int) -> list[WebPageRecord]:
        data = self._load_data()
        rows = data.get(key, [])
        records = [
            WebPageRecord(
                title=str(row.get("title", "")),
                url=str(row.get("url", "")),
                excerpt=str(row.get("excerpt", "")),
                text_length=int(row.get("text_length") or 0),
                ordinal=int(row["ordinal"]) if row.get("ordinal") is not None else None,
                match_query=str(row.get("match_query", "")),
                timestamp=str(row.get("timestamp", "")),
            )
            for row in rows
            if row.get("url")
        ]
        return records[-max(1, limit) :]

    def _load_data(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_data(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
