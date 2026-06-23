from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTIVE_SKILL_STATUSES = {"active"}
INACTIVE_SKILL_STATUSES = {"draft", "deprecated", "disabled", "quarantined"}
VALID_SKILL_STATUSES = ACTIVE_SKILL_STATUSES | INACTIVE_SKILL_STATUSES


@dataclass
class Skill:
    name: str
    content: str
    path: Path
    metadata: dict[str, Any] | None = None


class SkillStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._ensure_seed_skills()

    def _ensure_seed_skills(self) -> None:
        seed = self.directory / "general_agent.md"
        if not seed.exists():
            seed.write_text(
                "# general_agent\n\n"
                "- Break complex requests into short plans.\n"
                "- Prefer safe workspace-local file operations.\n"
                "- Verify code changes by running lightweight checks when possible.\n"
                "- After failures, capture a lesson with the cause and prevention.\n",
                encoding="utf-8",
            )

    def list(self) -> list[Skill]:
        skills: list[Skill] = []
        for path in sorted(self.directory.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            metadata, body = self._parse_frontmatter(content)
            skills.append(Skill(path.stem, body, path, metadata))
        return skills

    def match(self, query: str, *, limit: int = 5, include_inactive: bool = False) -> list[Skill]:
        """Return skills selected by manifest triggers and lexical relevance."""
        q = query.lower().strip()
        scored: list[tuple[int, Skill]] = []
        for skill in self.list():
            metadata = skill.metadata or {}
            if not include_inactive and self._status(metadata) not in ACTIVE_SKILL_STATUSES:
                continue
            triggers = self._metadata_list(metadata.get("triggers")) + self._metadata_list(metadata.get("keywords"))
            hay = (skill.name + "\n" + skill.content + "\n" + " ".join(triggers)).lower()
            score = sum(2 for trigger in triggers if trigger.lower() and trigger.lower() in q)
            score += sum(1 for token in q.split() if token in hay)
            if not q or score:
                scored.append((score, skill))
        scored.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        return [skill for _, skill in scored[:limit]]

    def context(self, query: str = "") -> str:
        skills = [skill for skill in self.list() if self._status(skill.metadata or {}) in ACTIVE_SKILL_STATUSES]
        if not skills:
            return "No skills."
        selected = self.match(query, limit=5)
        if not selected:
            selected = skills[:3]
        return "\n\n".join(f"## {s.name}\n{s.content[:1500]}" for s in selected[:5])

    def upsert(self, name: str, content: str, *, metadata: dict[str, Any] | None = None) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_") or f"skill_{int(time.time())}"
        path = self.directory / f"{safe}.md"
        new_body = content.strip()
        if path.exists():
            old = path.read_text(encoding="utf-8")
            old_metadata, old_body = self._parse_frontmatter(old)
            merged_body = old_body.strip()
            if new_body and new_body not in merged_body:
                merged_body = (merged_body.rstrip() + "\n\n" + new_body).strip()
            if metadata or old_metadata:
                merged_metadata = {**old_metadata, **dict(metadata or {})}
                path.write_text(self._with_frontmatter(safe, merged_body, merged_metadata).rstrip() + "\n", encoding="utf-8")
            elif merged_body != old.strip():
                path.write_text(f"# {safe}\n\n{merged_body}\n", encoding="utf-8")
        else:
            if metadata:
                path.write_text(self._with_frontmatter(safe, new_body, metadata).rstrip() + "\n", encoding="utf-8")
            else:
                path.write_text(f"# {safe}\n\n{new_body}\n", encoding="utf-8")
        return path

    def set_status(self, name: str, status: str, *, reason: str = "status update") -> bool:
        status = status.strip().lower()
        if status not in VALID_SKILL_STATUSES:
            raise ValueError(f"invalid skill status: {status}")
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_")
        path = self.directory / f"{safe}.md"
        if not path.exists():
            return False
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(raw)
        metadata = dict(metadata or {})
        metadata["status"] = status
        metadata["status_reason"] = reason
        metadata["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if "created_at" not in metadata:
            metadata["created_at"] = metadata["updated_at"]
        path.write_text(self._with_frontmatter(safe, body.strip(), metadata) + "\n", encoding="utf-8")
        return True

    def stats(self) -> dict[str, int]:
        skills = self.list()
        evolved = sum(1 for s in skills if (s.metadata or {}).get("source") == "self_evolution" or "source: self_evolution" in s.content or s.name.startswith("evolved_"))
        stats = {"total": len(skills), "evolved": evolved}
        for skill in skills:
            status = self._status(skill.metadata or {})
            stats[f"status:{status}"] = stats.get(f"status:{status}", 0) + 1
        return stats

    def audit(self) -> dict[str, int]:
        stats = self.stats()
        active = stats.get("status:active", 0)
        inactive = sum(stats.get(f"status:{status}", 0) for status in INACTIVE_SKILL_STATUSES)
        missing_triggers = 0
        missing_source = 0
        for skill in self.list():
            metadata = skill.metadata or {}
            if self._status(metadata) not in ACTIVE_SKILL_STATUSES:
                continue
            if skill.name != "general_agent" and not (self._metadata_list(metadata.get("triggers")) or self._metadata_list(metadata.get("keywords"))):
                missing_triggers += 1
            if skill.name != "general_agent" and not metadata.get("source"):
                missing_source += 1
        return {
            "total": stats.get("total", 0),
            "active": active,
            "inactive": inactive,
            "active_missing_triggers": missing_triggers,
            "active_missing_source": missing_source,
        }

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        if not content.startswith("---\n"):
            legacy_start = content.find("\n---\n")
            if legacy_start > 0:
                metadata, body = self._parse_frontmatter(content[legacy_start + 1 :])
                if metadata:
                    return metadata, body
            return {}, content
        end = content.find("\n---", 4)
        if end < 0:
            return {}, content
        raw = content[4:end]
        body = content[content.find("\n", end + 4) + 1 :]
        metadata: dict[str, Any] = {}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if "," in value:
                metadata[key.strip()] = [item.strip() for item in value.split(",") if item.strip()]
            else:
                metadata[key.strip()] = value
        return metadata, body

    def _metadata_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, tuple):
            return [str(item) for item in value]
        return [str(value)]

    def _status(self, metadata: dict[str, Any]) -> str:
        status = str(metadata.get("status") or "active").strip().lower()
        return status if status in VALID_SKILL_STATUSES else "quarantined"

    def _with_frontmatter(self, safe_name: str, content: str, metadata: dict[str, Any]) -> str:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data = {"name": safe_name, "status": "active", "updated_at": now, **metadata}
        if "created_at" not in data:
            data["created_at"] = now
        lines = ["---"]
        for key in sorted(data):
            value = data[key]
            if isinstance(value, (list, tuple)):
                rendered = ", ".join(str(x) for x in value)
            else:
                rendered = str(value)
            lines.append(f"{key}: {rendered}")
        lines.append("---")
        return "\n".join(lines) + "\n\n" + content
