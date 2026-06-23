from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from evolva.tools.base import ToolResult


MAX_COMMAND_OUTPUT_CHARS = 20_000
DANGEROUS_SHELL = [
    "rm -rf",
    "rm -fr",
    "rm -rf /",
    "git reset --hard",
    "mkfs",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
]
SHELL_CONTROL_TOKENS = ["&&", "||", "|", ";", "`", "$(", ">", "<"]
SNAPSHOT_IGNORE_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


@dataclass(frozen=True)
class SandboxPolicy:
    root: Path
    workspace: Path
    allow_shell: bool = True
    default_timeout: int = 30
    backend: str = "local"
    container_image: str = "python:3.12-slim"
    container_network: str = "none"
    container_read_only: bool = True
    container_memory: str = "512m"
    container_cpus: str = "1"
    container_pids_limit: int = 128
    container_user: str = ""
    writable_roots: tuple[Path, ...] = field(default_factory=tuple)
    rollback_on_failure: bool = True
    snapshot_roots: tuple[Path, ...] = field(default_factory=tuple)
    max_snapshot_bytes: int = 5_000_000


@dataclass(frozen=True)
class CommandSpec:
    command: str
    argv: list[str]
    cwd: Path
    timeout: int
    env: dict[str, str] | None = None

    @property
    def executable(self) -> str:
        return Path(self.argv[0]).name if self.argv else ""


@dataclass
class SnapshotEntry:
    data: bytes
    mode: int


@dataclass
class SandboxSnapshot:
    """In-memory file snapshot for best-effort rollback of local executions."""

    root: Path
    roots: tuple[Path, ...]
    files: dict[Path, SnapshotEntry]
    skipped: list[str]

    def restore(self) -> dict[str, object]:
        removed = 0
        restored = 0
        known = set(self.files)
        for root in self.roots:
            if not root.exists():
                continue
            for path in sorted((p for p in root.rglob("*") if p.is_file()), reverse=True):
                rel = path.relative_to(self.root)
                if rel not in known:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
        for rel, entry in self.files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.write_bytes(entry.data)
                path.chmod(entry.mode)
                restored += 1
            except OSError:
                pass
        for root in self.roots:
            _remove_empty_dirs(root)
        return {"removed": removed, "restored": restored, "skipped": list(self.skipped)}


class SandboxBackend(Protocol):
    """Execution backend contract for local-first sandbox implementations."""

    name: str

    def run_command(self, spec: CommandSpec) -> ToolResult: ...

    def run_python(self, code: str, *, cwd: Path, timeout: int) -> ToolResult: ...


class LocalWorkspaceBackend:
    """Default backend: execute commands inside the workspace root."""

    name = "local"

    def run_command(self, spec: CommandSpec) -> ToolResult:
        try:
            proc = subprocess.run(spec.argv, cwd=spec.cwd, shell=False, text=True, capture_output=True, timeout=spec.timeout, env=spec.env)
        except subprocess.TimeoutExpired as exc:
            return ToolResult(False, f"Command timed out after {spec.timeout}s: {exc}", {"returncode": None, "backend": self.name, "timeout": spec.timeout, "argv": spec.argv})
        output, truncated = _bounded_output(proc.stdout, proc.stderr)
        return ToolResult(
            proc.returncode == 0,
            output or f"exit={proc.returncode}",
            {
                "returncode": proc.returncode,
                "backend": self.name,
                "argv": spec.argv,
                "executable": spec.executable,
                "cwd": str(spec.cwd),
                "timeout": spec.timeout,
                "truncated": truncated,
            },
        )

    def run_python(self, code: str, *, cwd: Path, timeout: int) -> ToolResult:
        try:
            proc = subprocess.run(["python3", "-c", code], cwd=cwd, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return ToolResult(False, f"Python timed out after {timeout}s: {exc}")
        output, truncated = _bounded_output(proc.stdout, proc.stderr)
        return ToolResult(proc.returncode == 0, output or f"exit={proc.returncode}", {"returncode": proc.returncode, "backend": self.name, "truncated": truncated})


class DockerWorkspaceBackend:
    """Optional Docker backend for stronger process isolation.

    The workspace root is bind-mounted at the same absolute path inside the
    container so existing cwd/path metadata remains stable for callers.
    """

    name = "docker"

    def __init__(
        self,
        *,
        root: Path,
        image: str = "python:3.12-slim",
        network: str = "none",
        read_only: bool = True,
        memory: str = "512m",
        cpus: str = "1",
        pids_limit: int = 128,
        user: str = "",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.root = root.resolve()
        self.image = image
        self.network = network or "none"
        self.read_only = bool(read_only)
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = int(pids_limit)
        self.user = user or _host_user()
        self.runner = runner

    def run_command(self, spec: CommandSpec) -> ToolResult:
        try:
            args = self._docker_args(spec.cwd, spec.argv)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"backend": self.name})
        try:
            proc = self.runner(args, cwd=self.root, shell=False, text=True, capture_output=True, timeout=spec.timeout)
        except subprocess.TimeoutExpired as exc:
            return ToolResult(False, f"Command timed out after {spec.timeout}s: {exc}", {"returncode": None, "backend": self.name, "timeout": spec.timeout, "argv": spec.argv, "image": self.image})
        except FileNotFoundError:
            return ToolResult(False, "Docker executable not found for container sandbox backend", {"returncode": None, "backend": self.name, "argv": spec.argv, "image": self.image})
        output, truncated = _bounded_output(proc.stdout, proc.stderr)
        return ToolResult(
            proc.returncode == 0,
            output or f"exit={proc.returncode}",
            {
                "returncode": proc.returncode,
                "backend": self.name,
                "argv": spec.argv,
                "docker_argv": args,
                "executable": spec.executable,
                "cwd": str(spec.cwd),
                "timeout": spec.timeout,
                "image": self.image,
                "network": self.network,
                "read_only": self.read_only,
                "memory": self.memory,
                "cpus": self.cpus,
                "pids_limit": self.pids_limit,
                "user": self.user,
                "truncated": truncated,
            },
        )

    def run_python(self, code: str, *, cwd: Path, timeout: int) -> ToolResult:
        spec = CommandSpec(command="python3 -c <code>", argv=["python3", "-c", code], cwd=cwd, timeout=timeout)
        return self.run_command(spec)

    def _docker_args(self, cwd: Path, argv: list[str]) -> list[str]:
        cwd = cwd.resolve()
        try:
            cwd.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"cwd escapes sandbox root: {cwd}") from exc
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.network,
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--pids-limit",
            str(self.pids_limit),
            "--user",
            self.user,
            "--workdir",
            str(cwd),
            "--mount",
            f"type=bind,src={self.root},dst={self.root}",
        ]
        if self.read_only:
            args.extend(["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])
        args.extend([self.image, *argv])
        return args


class Sandbox:
    """Workspace-aware sandbox for path resolution and local command execution."""

    def __init__(self, policy: SandboxPolicy, backend: SandboxBackend | None = None):
        root = policy.root.resolve()
        workspace = policy.workspace.resolve()
        writable_roots = tuple((root / item).resolve() if not item.is_absolute() else item.resolve() for item in policy.writable_roots) or (root,)
        snapshot_roots = tuple((root / item).resolve() if not item.is_absolute() else item.resolve() for item in policy.snapshot_roots) or (workspace,)
        self.policy = SandboxPolicy(
            root,
            workspace,
            policy.allow_shell,
            policy.default_timeout,
            policy.backend,
            policy.container_image,
            policy.container_network,
            policy.container_read_only,
            policy.container_memory,
            policy.container_cpus,
            policy.container_pids_limit,
            policy.container_user,
            writable_roots,
            policy.rollback_on_failure,
            snapshot_roots,
            policy.max_snapshot_bytes,
        )
        self.backend = backend or build_backend(self.policy)
        self.policy.workspace.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self.policy.root

    @property
    def workspace(self) -> Path:
        return self.policy.workspace

    def resolve(self, path: str | Path, *, base: Path | None = None, must_be_under_root: bool = True) -> Path:
        base_path = (base or self.root).resolve()
        candidate = (base_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if must_be_under_root:
            try:
                candidate.relative_to(self.root)
            except ValueError as exc:
                raise ValueError(f"Path escapes sandbox root: {candidate}") from exc
        return candidate

    def resolve_write(self, path: str | Path, *, base: Path | None = None) -> Path:
        candidate = self.resolve(path, base=base, must_be_under_root=True)
        if not self.is_writable(candidate):
            roots = ", ".join(str(root) for root in self.policy.writable_roots)
            raise ValueError(f"Path is outside sandbox writable roots: {candidate}; writable_roots={roots}")
        return candidate

    def is_writable(self, path: str | Path) -> bool:
        candidate = Path(path).resolve()
        for root in self.policy.writable_roots:
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def describe(self) -> str:
        writable = ",".join(str(root.relative_to(self.root) if _is_relative_to(root, self.root) else root) for root in self.policy.writable_roots)
        snapshots = ",".join(str(root.relative_to(self.root) if _is_relative_to(root, self.root) else root) for root in self.policy.snapshot_roots)
        details = (
            f"Sandbox root={self.root}; workspace={self.workspace}; shell={'enabled' if self.policy.allow_shell else 'disabled'}; "
            f"backend={self.backend.name}; writable_roots={writable}; rollback_on_failure={self.policy.rollback_on_failure}; snapshot_roots={snapshots}"
        )
        if isinstance(self.backend, DockerWorkspaceBackend):
            details += f"; image={self.backend.image}; network={self.backend.network}; read_only={self.backend.read_only}; memory={self.backend.memory}; cpus={self.backend.cpus}; pids_limit={self.backend.pids_limit}"
        return details

    def run_shell(self, command: str, *, cwd: str = ".", timeout: int | None = None) -> ToolResult:
        if not self.policy.allow_shell:
            return ToolResult(False, "Shell execution is disabled by sandbox policy")
        lowered = command.lower()
        if any(bad in lowered for bad in DANGEROUS_SHELL):
            return ToolResult(False, f"Blocked dangerous command: {command}")
        cwd_path = self.resolve(cwd)
        if not cwd_path.is_dir():
            return ToolResult(False, f"cwd is not a directory: {cwd_path}")
        try:
            spec = parse_command(command, cwd=cwd_path, timeout=timeout or self.policy.default_timeout)
        except ValueError as exc:
            return ToolResult(False, str(exc))
        return self._run_with_snapshot(lambda: self.backend.run_command(spec))

    def run_python(self, code: str, *, timeout: int = 10) -> ToolResult:
        return self._run_with_snapshot(lambda: self.backend.run_python(code, cwd=self.root, timeout=timeout))

    def smoke_check(self, *, timeout: int = 10) -> ToolResult:
        """Run a fixed backend smoke check for deployment/pre-prod validation."""

        expected = "evolva-sandbox-ok"
        result = self.run_python(f"print('{expected}')", timeout=timeout)
        data = dict(result.data) if isinstance(result.data, dict) else {}
        data.update({"backend": self.backend.name, "expected": expected})
        ok = result.ok and expected in result.output
        status = "ok" if ok else "failed"
        return ToolResult(ok, f"Sandbox smoke {status} backend={self.backend.name}\n{result.output}", data)

    def snapshot(self) -> SandboxSnapshot:
        files: dict[Path, SnapshotEntry] = {}
        skipped: list[str] = []
        used = 0
        roots = tuple(root for root in self.policy.snapshot_roots if _is_relative_to(root, self.root))
        for root in roots:
            if not root.exists():
                continue
            for path in _iter_snapshot_files(root):
                rel = path.relative_to(self.root)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if used + stat.st_size > self.policy.max_snapshot_bytes:
                    skipped.append(rel.as_posix())
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                files[rel] = SnapshotEntry(data, stat.st_mode)
                used += stat.st_size
        return SandboxSnapshot(self.root, roots, files, skipped)

    def _run_with_snapshot(self, execute: Callable[[], ToolResult]) -> ToolResult:
        snapshot = self.snapshot() if self.policy.rollback_on_failure else None
        result = execute()
        if result.ok or snapshot is None:
            return result
        rollback = snapshot.restore()
        data = dict(result.data) if isinstance(result.data, dict) else {"raw_data": result.data}
        data["rollback"] = rollback
        output = f"{result.output}\nRolled back sandbox snapshot: restored={rollback['restored']} removed={rollback['removed']}"
        skipped = rollback.get("skipped")
        if isinstance(skipped, list) and skipped:
            output += f" skipped={len(skipped)}"
        return ToolResult(False, output, data)


def parse_command(command: str, *, cwd: Path, timeout: int) -> CommandSpec:
    command = command.strip()
    if not command:
        raise ValueError("shell command is empty")
    _reject_shell_control(command)
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"shell command cannot be parsed: {exc}") from exc
    if not argv:
        raise ValueError("shell command is empty")
    return CommandSpec(command=command, argv=argv, cwd=cwd.resolve(), timeout=max(1, int(timeout)))


def build_backend(policy: SandboxPolicy) -> SandboxBackend:
    backend = (policy.backend or "local").lower()
    if backend in {"local", "workspace"}:
        return LocalWorkspaceBackend()
    if backend in {"docker", "container"}:
        return DockerWorkspaceBackend(
            root=policy.root,
            image=policy.container_image,
            network=policy.container_network,
            read_only=policy.container_read_only,
            memory=policy.container_memory,
            cpus=policy.container_cpus,
            pids_limit=policy.container_pids_limit,
            user=policy.container_user,
        )
    raise ValueError(f"Unknown sandbox backend: {policy.backend}")


def _reject_shell_control(command: str) -> None:
    for token in SHELL_CONTROL_TOKENS:
        if token in command:
            raise ValueError(f"shell control operator `{token}` is not allowed; use a single structured command")


def _bounded_output(stdout: str, stderr: str) -> tuple[str, bool]:
    output = (stdout + stderr).strip()
    if len(output) <= MAX_COMMAND_OUTPUT_CHARS:
        return output, False
    return output[:MAX_COMMAND_OUTPUT_CHARS] + "\n[TRUNCATED]", True


def _host_user() -> str:
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return f"{os.getuid()}:{os.getgid()}"
    return "1000:1000"


def _iter_snapshot_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SNAPSHOT_IGNORE_DIRS for part in path.parts):
            continue
        yield path


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
