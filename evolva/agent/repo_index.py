from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


@dataclass
class CodeChunk:
    """A searchable code or document span with symbol-level location data."""

    path: str
    language: str
    symbol: str
    kind: str
    start_line: int
    end_line: int
    text: str
    references: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class RepoIndexSnapshot:
    """Persisted repository index snapshot used by local search and evals."""

    root: str
    chunks: list[CodeChunk]
    built_at: float
    backend: str


class RepoIndex:
    """Local semantic repository index with symbol chunks and lexical vectors.

    The index is intentionally local-first: it never calls a network service and
    does not require a cloud embedding provider. If tree-sitter is installed the
    backend field records that the optional parser is available; otherwise Evolva
    uses deterministic stdlib symbol extraction. Search ranks chunks with a
    lightweight bag-of-tokens cosine score plus symbol/path boosts.
    """

    IGNORE_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
    }
    GENERATED_PARTS = {
        "evolva/repo_index",
        "evolva/traces",
        "evolva/eval_results",
        "evolva/workspace",
        "evolva/optimization_reports",
    }
    EXTENSIONS = {
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".jsonl": "jsonl",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".txt": "text",
    }
    TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[A-Z]?[a-z]+|[0-9]+")
    PY_SYMBOL_RE = re.compile(r"^(?P<indent>\s*)(?P<kind>class|def|async\s+def)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
    IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import\s+(.+)|import\s+(.+))", re.MULTILINE)
    MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def __init__(self, root: Path, index_file: Path | None = None, *, max_file_bytes: int = 250_000):
        self.root = root.resolve()
        self.index_file = (index_file or self.root / "evolva" / "repo_index" / "index.json").resolve()
        self.max_file_bytes = max_file_bytes

    def build(self, *, max_files: int = 1000) -> RepoIndexSnapshot:
        """Build and persist a repository index snapshot."""
        chunks: list[CodeChunk] = []
        for path in self._iter_files(max_files=max_files):
            text = self._read_text(path)
            if text is None:
                continue
            rel = self._rel(path)
            language = self.EXTENSIONS.get(path.suffix.lower(), "text")
            chunks.extend(self._chunk_file(rel, text, language))
        snapshot = RepoIndexSnapshot(root=str(self.root), chunks=chunks, built_at=time.time(), backend=self._backend_name())
        self._write(snapshot)
        return snapshot

    def load(self) -> RepoIndexSnapshot | None:
        """Load the latest persisted snapshot, returning None if absent or invalid."""
        if not self.index_file.exists():
            return None
        try:
            payload = json.loads(self.index_file.read_text(encoding="utf-8"))
            chunks = [CodeChunk(**item) for item in payload.get("chunks", [])]
            return RepoIndexSnapshot(
                root=str(payload.get("root", self.root)),
                chunks=chunks,
                built_at=float(payload.get("built_at", 0)),
                backend=str(payload.get("backend", "unknown")),
            )
        except Exception:
            return None

    def search(self, query: str, *, limit: int = 8) -> list[CodeChunk]:
        """Search indexed chunks by natural language, symbol, path, or reference."""
        snapshot = self.load() or self.build()
        query_tokens = self._token_counts(query)
        if not query_tokens:
            return []
        ranked: list[CodeChunk] = []
        q_lower = query.lower()
        for chunk in snapshot.chunks:
            score = self._score(query_tokens, q_lower, chunk)
            if score <= 0:
                continue
            ranked.append(CodeChunk(**{**asdict(chunk), "score": round(score, 4)}))
        ranked.sort(key=lambda c: (-c.score, c.path, c.start_line))
        return ranked[: max(1, int(limit))]

    def _iter_files(self, *, max_files: int) -> Iterable[Path]:
        seen = 0
        for path in sorted(self.root.rglob("*")):
            if seen >= max_files:
                break
            if not path.is_file():
                continue
            if self._ignored(path):
                continue
            if path.suffix.lower() not in self.EXTENSIONS:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
            except OSError:
                continue
            seen += 1
            yield path

    def _ignored(self, path: Path) -> bool:
        rel = self._rel(path)
        parts = set(Path(rel).parts)
        if parts & self.IGNORE_DIRS:
            return True
        return any(rel == item or rel.startswith(item + "/") for item in self.GENERATED_PARTS)

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _chunk_file(self, rel: str, text: str, language: str) -> list[CodeChunk]:
        if language == "python":
            return self._chunk_python(rel, text)
        if language == "markdown":
            return self._chunk_markdown(rel, text)
        return [self._file_chunk(rel, text, language)]

    def _chunk_python(self, rel: str, text: str) -> list[CodeChunk]:
        lines = text.splitlines()
        matches = list(self.PY_SYMBOL_RE.finditer(text))
        if not matches:
            return [self._file_chunk(rel, text, "python")]
        line_starts = self._line_offsets(text)
        chunks: list[CodeChunk] = []
        module_refs = self._references(text)
        for index, match in enumerate(matches):
            indent = len(match.group("indent"))
            raw_kind = match.group("kind")
            kind = "function" if "def" in raw_kind else "class"
            name = match.group("name")
            start = self._line_for_offset(line_starts, match.start())
            end = len(lines)
            for later in matches[index + 1 :]:
                later_indent = len(later.group("indent"))
                if later_indent <= indent:
                    end = self._line_for_offset(line_starts, later.start()) - 1
                    break
            chunk_text = "\n".join(lines[start - 1 : end]).strip("\n")
            chunks.append(
                CodeChunk(
                    path=rel,
                    language="python",
                    symbol=name,
                    kind=kind,
                    start_line=start,
                    end_line=end,
                    text=chunk_text,
                    references=sorted(set(module_refs + self._identifier_refs(chunk_text)[:80])),
                )
            )
        return chunks

    def _chunk_markdown(self, rel: str, text: str) -> list[CodeChunk]:
        lines = text.splitlines()
        matches = list(self.MD_HEADING_RE.finditer(text))
        if not matches:
            return [self._file_chunk(rel, text, "markdown")]
        line_starts = self._line_offsets(text)
        chunks: list[CodeChunk] = []
        for index, match in enumerate(matches):
            start = self._line_for_offset(line_starts, match.start())
            end = len(lines)
            if index + 1 < len(matches):
                end = self._line_for_offset(line_starts, matches[index + 1].start()) - 1
            title = match.group(2).strip()
            chunk_text = "\n".join(lines[start - 1 : end]).strip("\n")
            chunks.append(
                CodeChunk(
                    path=rel,
                    language="markdown",
                    symbol=title,
                    kind="section",
                    start_line=start,
                    end_line=end,
                    text=chunk_text,
                    references=self._identifier_refs(chunk_text)[:80],
                )
            )
        return chunks

    def _file_chunk(self, rel: str, text: str, language: str) -> CodeChunk:
        lines = text.splitlines()
        return CodeChunk(
            path=rel,
            language=language,
            symbol=Path(rel).name,
            kind="file",
            start_line=1,
            end_line=max(1, len(lines)),
            text=text[:20000],
            references=self._identifier_refs(text)[:80],
        )

    def _score(self, query_tokens: Counter[str], q_lower: str, chunk: CodeChunk) -> float:
        field = f"{chunk.path} {chunk.symbol} {chunk.kind} {' '.join(chunk.references)} {chunk.text}"
        doc_tokens = self._token_counts(field)
        cosine = self._cosine(query_tokens, doc_tokens)
        if cosine <= 0:
            return 0.0
        symbol_lower = chunk.symbol.lower()
        path_lower = chunk.path.lower()
        text_lower = chunk.text.lower()
        symbol_boost = 1.4 if q_lower in symbol_lower or symbol_lower in q_lower else 0.0
        path_boost = 0.7 if any(token in path_lower for token in query_tokens) else 0.0
        text_boost = 0.4 if q_lower and q_lower in text_lower else 0.0
        fuzzy = SequenceMatcher(None, q_lower, f"{path_lower} {symbol_lower}").ratio() * 0.25
        return cosine + symbol_boost + path_boost + text_boost + fuzzy

    def _token_counts(self, text: str) -> Counter[str]:
        tokens: list[str] = []
        for raw in self.TOKEN_RE.findall(text):
            tokens.extend(self._split_identifier(raw))
        return Counter(token for token in tokens if len(token) > 1)

    def _split_identifier(self, value: str) -> list[str]:
        pieces = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ").replace("-", " ").split()
        return [piece.lower() for piece in pieces]

    def _cosine(self, left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(count * right.get(token, 0) for token, count in left.items())
        if dot == 0:
            return 0.0
        l_norm = math.sqrt(sum(count * count for count in left.values()))
        r_norm = math.sqrt(sum(count * count for count in right.values()))
        return dot / max(1e-9, l_norm * r_norm)

    def _references(self, text: str) -> list[str]:
        refs: list[str] = []
        for match in self.IMPORT_RE.finditer(text):
            if match.group(1):
                refs.append(match.group(1))
                refs.extend(part.strip().split(" as ")[0] for part in match.group(2).split(","))
            elif match.group(3):
                refs.extend(part.strip().split(" as ")[0] for part in match.group(3).split(","))
        return [ref for ref in refs if ref]

    def _identifier_refs(self, text: str) -> list[str]:
        seen: set[str] = set()
        refs: list[str] = []
        for token in self.TOKEN_RE.findall(text):
            if token in seen or len(token) < 3:
                continue
            seen.add(token)
            refs.append(token)
        return refs

    def _write(self, snapshot: RepoIndexSnapshot) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(snapshot)
        tmp = self.index_file.with_suffix(self.index_file.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_file)

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    def _backend_name(self) -> str:
        try:
            import tree_sitter  # type: ignore  # noqa: F401
        except Exception:
            return "stdlib_symbol_vectors"
        return "tree_sitter_available+stdlib_symbol_vectors"

    @staticmethod
    def _line_offsets(text: str) -> list[int]:
        offsets = [0]
        for match in re.finditer("\n", text):
            offsets.append(match.end())
        return offsets

    @staticmethod
    def _line_for_offset(offsets: list[int], offset: int) -> int:
        lo = 0
        hi = len(offsets)
        while lo < hi:
            mid = (lo + hi) // 2
            if offsets[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid
        return max(1, lo)
