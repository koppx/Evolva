from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from difflib import SequenceMatcher

from evolva.storage import append_jsonl, atomic_write_jsonl, read_jsonl


@dataclass
class MemoryItem:
    kind: str
    content: str
    confidence: float = 0.7
    source: str = "user"
    ts: float = 0.0
    id: str = ""
    evidence: list[str] | None = None
    status: str = "active"
    version: int = 1
    supersedes: str = ""

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = time.time()
        if self.evidence is None:
            self.evidence = []
        if not self.id:
            base = f"{self.kind}\n{self.content}\n{self.source}\n{self.ts:.6f}"
            self.id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        kind: str,
        content: str,
        *,
        confidence: float = 0.7,
        source: str = "user",
        evidence: list[str] | None = None,
        status: str = "active",
        supersedes: str = "",
    ) -> MemoryItem:
        item = MemoryItem(kind=kind, content=content.strip(), confidence=confidence, source=source, evidence=evidence or [], status=status, supersedes=supersedes)
        if not item.content:
            return item
        append_jsonl(self.path, asdict(item))
        return item

    def rollback(self, item_id: str, *, reason: str = "manual rollback") -> bool:
        """Mark a memory as rolled back without deleting historical evidence."""
        items = self.all(100000)
        changed = False
        for item in items:
            if item.id == item_id:
                item.status = "rolled_back"
                item.evidence = [*(item.evidence or []), reason]
                changed = True
        if not changed:
            return False
        atomic_write_jsonl(self.path, [asdict(item) for item in items])
        return True

    def find_similar(self, kind: str, content: str, *, threshold: float = 0.92, limit: int = 500) -> MemoryItem | None:
        """Return a near-duplicate memory item when one already exists."""
        normalized = self._normalize(content)
        if not normalized:
            return None
        for item in reversed(self.all(limit)):
            if item.kind != kind:
                continue
            other = self._normalize(item.content)
            if not other:
                continue
            if normalized == other:
                return item
            if SequenceMatcher(None, normalized, other).ratio() >= threshold:
                return item
        return None

    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.all(10000):
            counts[item.kind] = counts.get(item.kind, 0) + 1
        counts["total"] = sum(counts.values())
        return counts

    def render_stats(self) -> str:
        stats = self.stats()
        total = stats.pop("total", 0)
        lines = ["Memory stats", f"- total: {total}"]
        for kind, count in sorted(stats.items()):
            lines.append(f"- {kind}: {count}")
        return "\n".join(lines)

    def render_items(self, *, query: str = "", limit: int = 10) -> str:
        items = self.search(query, limit=limit) if query else self.all(limit)
        if not items:
            return "No memories."
        lines = []
        for item in items:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.ts))
            lines.append(f"- [{item.kind}/{item.confidence:.1f}/{item.status}] {item.content} ({item.source}, {ts}, id={item.id})")
        return "\n".join(lines)

    def all(self, limit: int = 50) -> list[MemoryItem]:
        if not self.path.exists():
            return []
        rows: list[MemoryItem] = []
        for raw in read_jsonl(self.path):
            try:
                rows.append(MemoryItem(**raw))
            except Exception:
                continue
        return rows[-limit:]

    def search(self, query: str, limit: int = 8) -> list[MemoryItem]:
        q = query.lower().strip()
        if not q:
            return self.all(limit)
        scored: list[tuple[int, MemoryItem]] = []
        for item in self.all(1000):
            if item.status == "rolled_back":
                continue
            hay = f"{item.kind} {item.content} {item.source} {' '.join(item.evidence or [])}".lower()
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
        return "\n".join(f"- [{m.kind}/{m.confidence:.1f}/{m.status}] {m.content}" for m in items if m.status != "rolled_back")

    def _normalize(self, text: str) -> str:
        return " ".join(text.lower().strip().split())
