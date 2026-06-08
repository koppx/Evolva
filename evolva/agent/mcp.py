from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True


class MCPClient:
    """Minimal stdio MCP client using JSON-RPC Content-Length framing."""

    def __init__(self, config: MCPServerConfig, *, root: Path):
        self.config = config
        self.root = root
        self.proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._initialized = False

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        env = os.environ.copy()
        env.update(self.config.env)
        cwd = self.config.cwd or str(self.root)
        self.proc = subprocess.Popen(
            [self.config.command, *self.config.args],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
                "clientInfo": {"name": "Evolva", "version": "0.1.0"},
            },
        )
        if "error" in result:
            raise RuntimeError(f"MCP initialize failed for {self.config.name}: {result['error']}")
        self.notify("notifications/initialized", {})
        self._initialized = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self.request("tools/list", {})
        if "error" in result:
            raise RuntimeError(f"MCP tools/list failed for {self.config.name}: {result['error']}")
        return list(result.get("result", {}).get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in result:
            raise RuntimeError(f"MCP tools/call failed for {self.config.name}/{name}: {result['error']}")
        return dict(result.get("result", {}))

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.start()
            assert self.proc is not None
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            while True:
                message = self._read()
                if message.get("id") == request_id:
                    return message

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.start()
            self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _write(self, message: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def _read(self) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None
        stdout = self.proc.stdout
        headers: dict[str, str] = {}
        while True:
            line = stdout.readline()
            if not line:
                stderr = self._stderr_tail()
                raise RuntimeError(f"MCP server {self.config.name} closed stdout. stderr={stderr}")
            if line in {b"\r\n", b"\n"}:
                break
            key, _, value = line.decode("ascii", errors="replace").partition(":")
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = stdout.read(length)
        if len(body) != length:
            raise RuntimeError(f"MCP server {self.config.name} returned incomplete message")
        return json.loads(body.decode("utf-8"))

    def _stderr_tail(self) -> str:
        if not self.proc or not self.proc.stderr:
            return ""
        try:
            return self.proc.stderr.read(2000).decode("utf-8", errors="replace")
        except Exception:
            return ""


class MCPManager:
    def __init__(self, config_file: Path, *, root: Path):
        self.config_file = config_file
        self.root = root
        self.clients: dict[str, MCPClient] = {}
        self.servers = self.load_configs(config_file)

    def load_configs(self, path: Path) -> dict[str, MCPServerConfig]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_servers = data.get("servers", data if isinstance(data, dict) else {})
        servers: dict[str, MCPServerConfig] = {}
        for name, item in raw_servers.items():
            if not item or item.get("enabled", True) is False:
                continue
            servers[name] = MCPServerConfig(
                name=name,
                command=str(item["command"]),
                args=list(item.get("args", [])),
                env=dict(item.get("env", {})),
                cwd=item.get("cwd"),
                enabled=bool(item.get("enabled", True)),
            )
        return servers

    def list_servers(self) -> list[str]:
        return sorted(self.servers)

    def add_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        enabled: bool = True,
    ) -> MCPServerConfig:
        """Persist and activate a stdio MCP server configuration.

        The method is intentionally local-first: it only edits Evolva's local
        `servers.json` and refreshes the in-memory manager. Starting the server
        still happens lazily when `/mcp tools` or `mcp_call` is used.
        """
        name = name.strip()
        command = command.strip()
        if not name:
            raise ValueError("MCP server name cannot be empty")
        if not command:
            raise ValueError("MCP server command cannot be empty")
        data = self._raw_config()
        servers = data.setdefault("servers", {})
        servers[name] = {
            "command": command,
            "args": list(args or []),
            "env": dict(env or {}),
            "enabled": bool(enabled),
        }
        if cwd:
            servers[name]["cwd"] = cwd
        self._write_config(data)
        config = MCPServerConfig(name=name, command=command, args=list(args or []), env=dict(env or {}), cwd=cwd, enabled=enabled)
        self.servers[name] = config
        if name in self.clients:
            self.clients[name].close()
            self.clients.pop(name, None)
        return config

    def remove_server(self, name: str) -> bool:
        """Remove a local MCP server configuration if it exists."""
        data = self._raw_config()
        servers = data.setdefault("servers", {})
        existed = name in servers
        if existed:
            servers.pop(name, None)
            self._write_config(data)
        if name in self.clients:
            self.clients[name].close()
            self.clients.pop(name, None)
        self.servers.pop(name, None)
        return existed

    def client(self, server: str) -> MCPClient:
        if server not in self.servers:
            raise KeyError(f"Unknown MCP server: {server}")
        if server not in self.clients:
            self.clients[server] = MCPClient(self.servers[server], root=self.root)
        return self.clients[server]

    def list_tools(self, server: str | None = None) -> list[dict[str, Any]]:
        names = [server] if server else self.list_servers()
        rows: list[dict[str, Any]] = []
        for name in names:
            for tool in self.client(name).list_tools():
                tool = dict(tool)
                tool["server"] = name
                rows.append(tool)
        return rows

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.client(server).call_tool(tool, arguments)

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()

    def _raw_config(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {"servers": {}}
        data = json.loads(self.config_file.read_text(encoding="utf-8"))
        if "servers" in data:
            return data
        return {"servers": data if isinstance(data, dict) else {}}

    def _write_config(self, data: dict[str, Any]) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_mcp_result(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            kind = item.get("type")
            if kind == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts).strip() or json.dumps(result, ensure_ascii=False, indent=2)
    return json.dumps(result, ensure_ascii=False, indent=2)
