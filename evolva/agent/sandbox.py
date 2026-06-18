from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
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
        self.policy = SandboxPolicy(
            policy.root.resolve(),
            policy.workspace.resolve(),
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

    def describe(self) -> str:
        details = f"Sandbox root={self.root}; workspace={self.workspace}; shell={'enabled' if self.policy.allow_shell else 'disabled'}; backend={self.backend.name}"
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
        return self.backend.run_command(spec)

    def run_python(self, code: str, *, timeout: int = 10) -> ToolResult:
        return self.backend.run_python(code, cwd=self.root, timeout=timeout)

    def smoke_check(self, *, timeout: int = 10) -> ToolResult:
        """Run a fixed backend smoke check for deployment/pre-prod validation."""

        expected = "evolva-sandbox-ok"
        result = self.run_python(f"print('{expected}')", timeout=timeout)
        data = dict(result.data) if isinstance(result.data, dict) else {}
        data.update({"backend": self.backend.name, "expected": expected})
        ok = result.ok and expected in result.output
        status = "ok" if ok else "failed"
        return ToolResult(ok, f"Sandbox smoke {status} backend={self.backend.name}\n{result.output}", data)


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
