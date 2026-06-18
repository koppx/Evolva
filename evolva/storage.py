from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


try:  # pragma: no cover - Windows fallback is intentionally simple.
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Advisory lock next to a state file.

    The lock is process-safe on Unix/macOS. On platforms without `fcntl` it
    still creates the lock file and behaves as a no-op, which keeps tests and
    local operation portable without promising cross-process safety there.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    local_lock = _local_lock_for(lock_path)
    with local_lock:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return _fresh_default(default)
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return _fresh_default(default)
        return json.loads(raw)
    except json.JSONDecodeError:
        _quarantine_corrupt(path)
        return _fresh_default(default)


def atomic_update_json(path: Path, default: Any, update: Callable[[Any], Any]) -> Any:
    with file_lock(path):
        data = read_json(path, default)
        result = update(data)
        to_write = result if result is not None else data
        atomic_write_json(path, to_write)
        return to_write


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        _quarantine_corrupt(path)
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    with file_lock(path):
        atomic_write_text(path, text)


def _quarantine_corrupt(path: Path) -> None:
    if not path.exists():
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    corrupt = path.with_name(f"{path.name}.corrupt.{ts}")
    try:
        path.replace(corrupt)
    except OSError:
        pass


def _fresh_default(default: Any) -> Any:
    if callable(default):
        return default()
    if isinstance(default, list):
        return list(default)
    if isinstance(default, dict):
        return dict(default)
    return default


def _local_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCAL_LOCKS[key] = lock
        return lock
