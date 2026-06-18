from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from evolva.storage import atomic_update_json, atomic_write_json, read_json

ContextKind = Literal["message", "note", "artifact", "summary", "decision"]


@dataclass
class ContextItem:
    kind: ContextKind
    content: str
    role: str = "system"
    meta: dict[str, Any] | None = None
    ts: float = 0.0

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = time.time()
        if self.meta is None:
            self.meta = {}


class ContextStore:
    """Persistent run context: recent messages, notes, artifacts, and summaries."""

    def __init__(self, path: Path, *, max_items: int = 200):
        self.path = path
        self.max_items = max_items
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, kind: ContextKind, content: str, *, role: str = "system", meta: dict[str, Any] | None = None) -> ContextItem:
        content = content.strip()
        if not content:
            raise ValueError("context content is required")
        item = ContextItem(kind=kind, content=content, role=role, meta=meta or {})

        def update(raw: Any) -> list[dict[str, Any]]:
            items = self._items_from_raw(raw)
            items.append(item)
            if len(items) > self.max_items:
                items = items[-self.max_items :]
            return [asdict(x) for x in items]

        atomic_update_json(self.path, [], update)
        return item

    def recent(self, limit: int = 12, *, kinds: list[str] | None = None) -> list[ContextItem]:
        items = self._load()
        if kinds:
            allowed = set(kinds)
            items = [x for x in items if x.kind in allowed]
        return items[-limit:]

    def search(self, query: str, limit: int = 8) -> list[ContextItem]:
        q = query.lower().strip()
        if not q:
            return self.recent(limit)
        scored: list[tuple[int, ContextItem]] = []
        for item in self._load():
            hay = f"{item.kind} {item.role} {item.content} {json.dumps(item.meta or {}, ensure_ascii=False)}".lower()
            score = sum(1 for token in q.split() if token in hay)
            if q in hay:
                score += 3
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: (x[0], x[1].ts), reverse=True)
        return [item for _, item in scored[:limit]]

    def compact(self, title: str = "Conversation summary", limit: int = 30) -> ContextItem:
        recent = self.recent(limit)
        if not recent:
            return self.add("summary", f"{title}: no context yet.")
        bullets = []
        for item in recent:
            content = item.content.replace("\n", " ")[:240]
            bullets.append(f"- {item.kind}/{item.role}: {content}")
        return self.add("summary", title + "\n" + "\n".join(bullets), meta={"source_items": len(recent)})

    def render(self, query: str = "", limit: int = 12) -> str:
        items = self.search(query, limit) if query else self.recent(limit)
        if not items:
            return "No context."
        return "\n".join(self._format(item) for item in items)

    def prompt_context(self, query: str, limit: int = 8) -> str:
        items = self.search(query, limit) if query else self.recent(limit)
        if not items:
            return "No persistent context."
        return "\n".join(self._format(item) for item in items)

    def _format(self, item: ContextItem) -> str:
        content = item.content.replace("\n", " ")
        return f"- [{item.kind}/{item.role}] {content}"

    def _load(self) -> list[ContextItem]:
        if not self.path.exists():
            return []
        return self._items_from_raw(read_json(self.path, []))

    def _save(self, items: list[ContextItem]) -> None:
        atomic_write_json(self.path, [asdict(x) for x in items])

    def _items_from_raw(self, raw: Any) -> list[ContextItem]:
        rows: list[ContextItem] = []
        source = raw if isinstance(raw, list) else []
        for row in source:
            if isinstance(row, dict):
                rows.append(ContextItem(**row))
        return rows
