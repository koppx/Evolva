from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from evolva.storage import atomic_update_json, atomic_write_json, read_json

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
        created: TodoItem | None = None

        def update(raw: object) -> list[dict]:
            nonlocal created
            items = self._items_from_raw(raw)
            next_id = max((item.id for item in items), default=0) + 1
            created = TodoItem(id=next_id, title=title, detail=detail.strip(), owner=owner.strip() or "Evolva")
            items.append(created)
            return [asdict(x) for x in items]

        atomic_update_json(self.path, [], update)
        assert created is not None
        return created

    def update(self, todo_id: int, *, status: str | None = None, title: str | None = None, detail: str | None = None, owner: str | None = None) -> TodoItem:
        updated: TodoItem | None = None

        def apply_update(raw: object) -> list[dict]:
            nonlocal updated
            items = self._items_from_raw(raw)
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
                updated = item
                break
            if updated is None:
                raise KeyError(f"todo not found: {todo_id}")
            return [asdict(x) for x in items]

        atomic_update_json(self.path, [], apply_update)
        assert updated is not None
        return updated

    def clear(self, *, include_done: bool = False) -> int:
        removed = 0

        def apply_clear(raw: object) -> list[dict]:
            nonlocal removed
            items = self._items_from_raw(raw)
            if include_done:
                removed = len(items)
                return []
            kept = [x for x in items if x.status not in {"done", "cancelled"}]
            removed = len(items) - len(kept)
            return [asdict(x) for x in kept]

        atomic_update_json(self.path, [], apply_clear)
        return removed

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
        raw = read_json(self.path, [])
        return self._items_from_raw(raw)

    def _save(self, items: list[TodoItem]) -> None:
        atomic_write_json(self.path, [asdict(x) for x in items])

    def _items_from_raw(self, raw: object) -> list[TodoItem]:
        if not isinstance(raw, list):
            return []
        items: list[TodoItem] = []
        for row in raw:
            if isinstance(row, dict):
                items.append(TodoItem(**row))
        return items
