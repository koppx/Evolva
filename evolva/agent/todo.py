from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

TodoStatus = Literal["pending", "in_progress", "blocked", "done", "cancelled"]


@dataclass
class TodoItem:
    id: int
    title: str
    status: TodoStatus = "pending"
    detail: str = ""
    owner: str = "Evolva"
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class TodoStore:
    """Persistent lightweight todolist for agent planning and execution state."""

    VALID_STATUSES: set[str] = {"pending", "in_progress", "blocked", "done", "cancelled"}

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list(self, *, include_done: bool = True) -> list[TodoItem]:
        items = self._load()
        if not include_done:
            items = [x for x in items if x.status not in {"done", "cancelled"}]
        return items

    def add(self, title: str, *, detail: str = "", owner: str = "Evolva") -> TodoItem:
        title = title.strip()
        if not title:
            raise ValueError("todo title is required")
        items = self._load()
        next_id = max((item.id for item in items), default=0) + 1
        item = TodoItem(id=next_id, title=title, detail=detail.strip(), owner=owner.strip() or "Evolva")
        items.append(item)
        self._save(items)
        return item

    def update(self, todo_id: int, *, status: str | None = None, title: str | None = None, detail: str | None = None, owner: str | None = None) -> TodoItem:
        items = self._load()
        for item in items:
            if item.id != todo_id:
                continue
            if status is not None:
                if status not in self.VALID_STATUSES:
                    raise ValueError(f"invalid status: {status}")
                item.status = status  # type: ignore[assignment]
            if title is not None and title.strip():
                item.title = title.strip()
            if detail is not None:
                item.detail = detail.strip()
            if owner is not None and owner.strip():
                item.owner = owner.strip()
            item.updated_at = time.time()
            self._save(items)
            return item
        raise KeyError(f"todo not found: {todo_id}")

    def clear(self, *, include_done: bool = False) -> int:
        items = self._load()
        if include_done:
            count = len(items)
            self._save([])
            return count
        kept = [x for x in items if x.status not in {"done", "cancelled"}]
        count = len(items) - len(kept)
        self._save(kept)
        return count

    def context(self, limit: int = 12) -> str:
        items = self.list(include_done=False)[-limit:]
        if not items:
            return "No active todos."
        return "\n".join(self._format(item) for item in items)

    def render(self, *, include_done: bool = True) -> str:
        items = self.list(include_done=include_done)
        if not items:
            return "No todos."
        return "\n".join(self._format(item) for item in items)

    def _format(self, item: TodoItem) -> str:
        detail = f" — {item.detail}" if item.detail else ""
        return f"#{item.id} [{item.status}] ({item.owner}) {item.title}{detail}"

    def _load(self) -> list[TodoItem]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return [TodoItem(**row) for row in raw if isinstance(row, dict)]

    def _save(self, items: list[TodoItem]) -> None:
        self.path.write_text(json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2), encoding="utf-8")
