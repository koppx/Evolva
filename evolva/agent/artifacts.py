from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evolva.storage import append_jsonl, read_jsonl


@dataclass
class ArtifactRecord:
    """Versioned metadata for a produced local artifact."""

    path: str
    sha256: str
    size_bytes: int
    kind: str = "file"
    producer: str = ""
    run_id: str = ""
    event_id: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactManifest:
    """Append-only artifact manifest for eval, replay, and provenance.

    The manifest deliberately stores paths relative to the project root. This
    keeps traces portable across machines while still allowing sha256-based
    verification of produced files.
    """

    def __init__(self, path: Path, root: Path, *, max_file_bytes: int = 25 * 1024 * 1024, max_records: int = 10_000):
        self.path = path
        self.root = root.resolve()
        self.max_file_bytes = int(max_file_bytes)
        self.max_records = int(max_records)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_file(
        self,
        path: Path,
        *,
        producer: str = "",
        run_id: str = "",
        event_id: str = "",
        kind: str = "file",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        """Record a file artifact and append it to manifest.jsonl."""

        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes root: {resolved}") from exc
        stat = resolved.stat()
        if self.max_file_bytes > 0 and stat.st_size > self.max_file_bytes:
            raise ValueError(f"artifact exceeds max_file_bytes={self.max_file_bytes}: {relative.as_posix()}")
        digest = _sha256_file(resolved)
        record = ArtifactRecord(
            path=relative.as_posix(),
            sha256=digest,
            size_bytes=stat.st_size,
            kind=kind,
            producer=producer,
            run_id=run_id,
            event_id=event_id,
            created_at=time.time(),
            metadata=metadata or {},
        )
        append_jsonl(self.path, record.to_dict())
        self.prune(max_records=self.max_records)
        return record

    def list(self, limit: int | None = None) -> list[ArtifactRecord]:
        """Return recorded artifacts, newest last unless limit trims from end."""

        if not self.path.exists():
            return []
        rows: list[ArtifactRecord] = []
        for raw in read_jsonl(self.path):
            try:
                rows.append(ArtifactRecord(**raw))
            except Exception:
                continue
        if limit is not None:
            return rows[-int(limit) :]
        return rows

    def find(self, artifact_path: str) -> list[ArtifactRecord]:
        """Find manifest records by project-relative artifact path."""

        normalized = artifact_path.replace("\\", "/").lstrip("/")
        return [record for record in self.list() if record.path == normalized]

    def verify(self, artifact_path: str) -> dict[str, Any]:
        """Return current existence and digest status for the latest record."""

        records = self.find(artifact_path)
        latest = records[-1] if records else None
        if latest is None:
            return {"path": artifact_path, "recorded": False, "exists": False, "sha256_ok": False}
        path = (self.root / latest.path).resolve()
        exists = path.exists()
        current_sha = _sha256_file(path) if exists and path.is_file() else ""
        return {
            "path": latest.path,
            "recorded": True,
            "exists": exists,
            "sha256_ok": bool(current_sha and current_sha == latest.sha256),
            "expected_sha256": latest.sha256,
            "actual_sha256": current_sha,
        }

    def prune(
        self,
        *,
        max_records: int | None = None,
        older_than: float | None = None,
        remove_missing: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Prune manifest records by count, age, and missing-file status.

        This only edits the manifest. It deliberately does not delete artifact
        files, because produced files may also be user-facing deliverables.
        """

        records = self.list()
        kept = list(records)
        removed: list[ArtifactRecord] = []
        if older_than is not None:
            next_kept: list[ArtifactRecord] = []
            for record in kept:
                if record.created_at and record.created_at < older_than:
                    removed.append(record)
                else:
                    next_kept.append(record)
            kept = next_kept
        if remove_missing:
            next_kept = []
            for record in kept:
                if not (self.root / record.path).exists():
                    removed.append(record)
                else:
                    next_kept.append(record)
            kept = next_kept
        if max_records is not None and max_records > 0 and len(kept) > max_records:
            overflow = len(kept) - max_records
            removed.extend(kept[:overflow])
            kept = kept[overflow:]
        if not dry_run and len(kept) != len(records):
            from evolva.storage import atomic_write_jsonl

            atomic_write_jsonl(self.path, [record.to_dict() for record in kept])
        return {
            "before": len(records),
            "after": len(kept),
            "removed": len(records) - len(kept),
            "removed_paths": [record.path for record in removed],
            "dry_run": dry_run,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
