from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class MemoryItem:
    kind: str
    content: str
    confidence: float = 0.7
    source: str = "user"
    ts: float = 0.0

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = time.time()


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, kind: str, content: str, *, confidence: float = 0.7, source: str = "user") -> MemoryItem:
        item = MemoryItem(kind=kind, content=content.strip(), confidence=confidence, source=source)
        if not item.content:
            return item
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        return item

    def all(self, limit: int = 50) -> list[MemoryItem]:
        if not self.path.exists():
            return []
        rows: list[MemoryItem] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(MemoryItem(**json.loads(line)))
            except Exception:
                continue
        return rows[-limit:]

    def search(self, query: str, limit: int = 8) -> list[MemoryItem]:
        q = query.lower().strip()
        if not q:
            return self.all(limit)
        scored: list[tuple[int, MemoryItem]] = []
        for item in self.all(1000):
            hay = f"{item.kind} {item.content} {item.source}".lower()
            score = sum(1 for token in q.split() if token in hay)
            if q in hay:
                score += 3
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: (x[0], x[1].ts), reverse=True)
        return [item for _, item in scored[:limit]]

    def context(self, query: str) -> str:
        items = self.search(query, limit=6)
        if not items:
            return "No relevant memories."
        return "\n".join(f"- [{m.kind}/{m.confidence:.1f}] {m.content}" for m in items)
