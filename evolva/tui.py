from __future__ import annotations

import curses
import importlib.metadata
import json
import locale
import os
import shlex
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

from evolva.agent.dream import DreamEngine
from evolva.agent.evolution_analyzer import EvalEvolutionAnalyzer, TraceEvolutionAnalyzer, apply_proposals, render_analysis, render_reports
from evolva.agent.core import EvolvaAgent, TurnResult
from evolva.config import AgentConfig, mask_secret, remove_runtime_config_keys, save_runtime_config
from evolva.loops import LoopRunner, render_loop_result, render_loop_specs


TUI_HELP = """
TUI keys:
  Enter          Send message or command
  Ctrl+L         Clear screen messages
  Ctrl+T         Toggle tool log panel
  Ctrl+R         Show recent traces
  Ctrl+X         Show latest trace context events
  F2             Prepare /model command
  F4             Open provider setup command
  PgUp/PgDn      Scroll chat
  Up/Down        Navigate input history
  Esc            Cancel current input line
  /exit          Quit

Commands:
  /help, /config [set|wizard|clear], /tools, /skills, /memory [query|stats|recent n], /context [query], /todo, /agents, /trace [list|show|context], /model [name], /policy, /mcp [add|remove|tools], /image <path|url> [text], /evolve [feedback|status|audit|trace|apply-trace|eval|apply-eval], /dream [backlog|verify|apply|--min-confidence n], /loop [list|show|run], /run <tool> <json>
""".strip()


@dataclass
class ChatLine:
    role: str
    text: str
    ts: str


class TUIConfirmation:
    """Confirmation adapter used by EvolvaAgent in TUI mode."""

    def __init__(self, app: "EvolvaTUI"):
        self.app = app

    def ask(self, tool_name: str, args: dict[str, Any]) -> bool:
        if self.app.assume_yes:
            return True
        prompt = f"Allow tool `{tool_name}` with args {json.dumps(args, ensure_ascii=False)}? y/N"
        return self.app.request_confirmation(prompt)


class EvolvaTUI:
    def __init__(self, assume_yes: bool = False, show_tools: bool = True):
        self.agent = EvolvaAgent(AgentConfig(), assume_yes=assume_yes, confirmer=TUIConfirmation(self))
        self.assume_yes = assume_yes
        self.show_tools = show_tools
        self.messages: list[ChatLine] = []
        self.tool_logs: list[str] = []
        self.input_text = ""
        self.history: list[str] = []
        self.history_index: int | None = None
        self.config_wizard: dict[str, Any] | None = None
        self.scroll = 0
        self.status = "Ready"
        self.busy = False
        self.queue: Queue[tuple[str, Any]] = Queue()
        self.confirmation_prompt: str | None = None
        self.confirmation_event: threading.Event | None = None
        self.confirmation_answer: bool | None = None
        self.stdscr: Any = None
        self._cached_version: str | None = None

    def run(self) -> int:
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        return curses.wrapper(self._main)

    def _main(self, stdscr: Any) -> int:
        self.stdscr = stdscr
        self._safe_curs_set(1)
        self._safe_use_default_colors()
        self._init_colors()
        stdscr.keypad(True)
        stdscr.timeout(100)
        self.status = "ready"
        if not self.agent.llm.available:
            self.status = "local mode · F4 config to connect a model"

        while True:
            self._drain_queue()
            self._draw()
            ch = self._read_key(stdscr)
            if ch is None:
                continue
            if self._handle_key(ch) is False:
                return 0

    def _read_key(self, stdscr: Any) -> int | str | None:
        try:
            ch = stdscr.get_wch()
        except curses.error:
            return None
        if ch == -1:
            return None
        return ch

    def _init_colors(self) -> None:
        try:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_CYAN, -1)    # user
            curses.init_pair(2, curses.COLOR_GREEN, -1)   # agent
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # system/status
            curses.init_pair(4, curses.COLOR_MAGENTA, -1) # tools
            curses.init_pair(5, curses.COLOR_RED, -1)     # errors
            curses.init_pair(6, curses.COLOR_BLUE, -1)    # panel chrome
            curses.init_pair(7, curses.COLOR_WHITE, -1)   # muted text
            curses.init_pair(8, curses.COLOR_YELLOW, -1)  # Evolva gold
        except (curses.error, ValueError):
            # Some pseudo terminals support curses drawing but not color pairs.
            # Keep TUI startup resilient and fall back to A_NORMAL rendering.
            pass

    def _safe_curs_set(self, visibility: int) -> None:
        try:
            curses.curs_set(visibility)
        except (curses.error, ValueError):
            pass

    def _safe_use_default_colors(self) -> None:
        try:
            curses.use_default_colors()
        except (curses.error, ValueError):
            pass

    def _color(self, pair: int, extra: int = 0) -> int:
        try:
            return curses.color_pair(pair) | extra
        except (curses.error, ValueError):
            return curses.A_NORMAL | extra

    def request_confirmation(self, prompt: str) -> bool:
        event = threading.Event()
        self.confirmation_prompt = prompt
        self.confirmation_event = event
        self.confirmation_answer = None
        self.status = prompt
        event.wait()
        answer = bool(self.confirmation_answer)
        self.confirmation_prompt = None
        self.confirmation_event = None
        self.confirmation_answer = None
        return answer

    def _handle_key(self, ch: int | str) -> bool | None:
        text = self._key_text(ch)
        if self.confirmation_event is not None:
            if text in ("y", "Y"):
                self.confirmation_answer = True
                self.status = "Tool approved."
                self.confirmation_event.set()
            elif text in ("n", "N", "\x1b", "\n", "\r") or self._is_key(ch, curses.KEY_ENTER):
                self.confirmation_answer = False
                self.status = "Tool denied."
                self.confirmation_event.set()
            return None
        if self.busy:
            if self._is_key(ch, curses.KEY_PPAGE):
                self.scroll += 3
            elif self._is_key(ch, curses.KEY_NPAGE):
                self.scroll = max(0, self.scroll - 3)
            return None

        if text in ("\n", "\r") or self._is_key(ch, curses.KEY_ENTER):
            line = self.input_text.strip()
            self.input_text = ""
            self.history_index = None
            if not line:
                return None
            if self.config_wizard is not None:
                self._handle_config_wizard_input(line)
                return None
            self.history.append(self._sanitize_display_line(line))
            if line in {"/exit", "/quit"}:
                return False
            self._submit(line)
            return None
        if text == "\x0c":  # Ctrl+L
            self.messages.clear()
            self.tool_logs.clear()
            self.scroll = 0
            self.status = "Cleared."
            return None
        if text == "\x14":  # Ctrl+T
            self.show_tools = not self.show_tools
            self.status = "Tool panel " + ("on" if self.show_tools else "off")
            return None
        if text == "\x12":  # Ctrl+R
            self._show_recent_traces()
            return None
        if text == "\x18":  # Ctrl+X
            self._show_latest_trace_context()
            return None
        if self._is_key(ch, curses.KEY_F2):
            self.input_text = "/model "
            self.status = "Type a model name, then Enter. Use /model to view current model."
            return None
        if self._is_key(ch, curses.KEY_F4):
            self.input_text = "/config wizard"
            self.status = "Press Enter to configure model, base URL, and API key."
            return None
        if text == "\x1b":  # Esc
            self.input_text = ""
            if self.config_wizard is not None:
                self.config_wizard = None
                self.status = "Config wizard cancelled."
                return None
            self.status = "Input cleared."
            return None
        if text in ("\b", "\x7f") or self._is_key(ch, curses.KEY_BACKSPACE):
            self.input_text = self.input_text[:-1]
            return None
        if self._is_key(ch, curses.KEY_PPAGE):
            self.scroll += 5
            return None
        if self._is_key(ch, curses.KEY_NPAGE):
            self.scroll = max(0, self.scroll - 5)
            return None
        if self._is_key(ch, curses.KEY_UP):
            if self.history:
                if self.history_index is None:
                    self.history_index = len(self.history) - 1
                else:
                    self.history_index = max(0, self.history_index - 1)
                self.input_text = self.history[self.history_index]
            return None
        if self._is_key(ch, curses.KEY_DOWN):
            if self.history_index is not None:
                self.history_index += 1
                if self.history_index >= len(self.history):
                    self.history_index = None
                    self.input_text = ""
                else:
                    self.input_text = self.history[self.history_index]
            return None
        if text == "\t":  # Tab quick complete common slash commands
            self._complete_command()
            return None
        if text and text.isprintable():
            self.input_text += text
        return None

    def _key_text(self, ch: int | str) -> str:
        if isinstance(ch, str):
            return ch
        try:
            return chr(ch)
        except (TypeError, ValueError):
            return ""

    def _is_key(self, ch: int | str, *keys: int) -> bool:
        return isinstance(ch, int) and ch in keys

    def _complete_command(self) -> None:
        commands = ["/help", "/config", "/tools", "/skills", "/memory", "/context", "/todo", "/agents", "/trace", "/model", "/policy", "/repo", "/mcp", "/image", "/evolve", "/dream", "/loop", "/run", "/exit"]
        matches = [c for c in commands if c.startswith(self.input_text)]
        if len(matches) == 1:
            self.input_text = matches[0] + (" " if matches[0] not in {"/help", "/tools", "/skills", "/exit"} else "")
            self.status = f"Completed {matches[0]}"
        elif matches:
            self.status = "Matches: " + ", ".join(matches)

    def _submit(self, line: str) -> None:
        self.scroll = 0
        self._add_user(self._sanitize_display_line(line))
        if line.startswith("/"):
            self._handle_command(line)
            return
        self.busy = True
        self.status = "Agent thinking..."
        thread = threading.Thread(target=self._worker_chat, args=(line,), daemon=True)
        thread.start()

    def _worker_chat(self, line: str) -> None:
        try:
            result = self.agent.chat(line)
            self.queue.put(("agent_result", result))
        except Exception as exc:
            self.queue.put(("error", f"Agent error: {exc}"))

    def _worker_chat_image(self, question: str, image: str) -> None:
        try:
            result = self.agent.chat(question, image_sources=[image])
            self.queue.put(("agent_result", result))
        except Exception as exc:
            self.queue.put(("error", f"Image chat error: {exc}"))

    def _handle_command(self, line: str) -> None:
        try:
            if line == "/help":
                self._add_system(TUI_HELP)
            elif line.startswith("/config"):
                self._handle_config_command(line.removeprefix("/config").strip())
            elif line == "/tools":
                self._add_system(self.agent.tools.describe())
            elif line == "/skills":
                skills = self.agent.skills.list()
                body = "\n".join(f"- {s.name}: {s.path}" for s in skills) or "No skills"
                self._add_system(body)
            elif line.startswith("/memory"):
                query = line.removeprefix("/memory").strip()
                if query in {"stats", "stat", "status"}:
                    self._add_system(self.agent.memory.render_stats())
                elif query.startswith("recent"):
                    parts = query.split()
                    limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
                    self._add_system(self.agent.memory.render_items(limit=limit))
                elif query.startswith("search "):
                    self._add_system(self.agent.memory.render_items(query=query.removeprefix("search ").strip(), limit=10))
                else:
                    self._add_system(self.agent.memory.context(query))
            elif line.startswith("/context"):
                query = line.removeprefix("/context").strip()
                self._add_system(self.agent.context.render(query=query))
            elif line.startswith("/todo"):
                rest = line.removeprefix("/todo").strip()
                if not rest:
                    self._add_system(self.agent.todos.render(include_done=True))
                elif rest.startswith("add "):
                    item = self.agent.todos.add(rest.removeprefix("add ").strip())
                    self._add_system(f"Added todo #{item.id}: {item.title}")
                elif rest.startswith("done "):
                    item = self.agent.todos.update(int(rest.removeprefix("done ").strip()), status="done")
                    self._add_system(f"Done todo #{item.id}: {item.title}")
                else:
                    self._add_system("Usage: /todo | /todo add <title> | /todo done <id>")
            elif line == "/agents":
                self._add_system(self.agent.coordinator.list_roles())
            elif line.startswith("/trace"):
                rest = line.removeprefix("/trace").strip()
                if rest in {"", "list"}:
                    self._show_recent_traces()
                elif rest.startswith("show "):
                    self._add_system(self.agent.tracer.render(rest.removeprefix("show ").strip()))
                elif rest.startswith("context "):
                    run_id = rest.removeprefix("context ").strip()
                    if run_id in {"", "latest"}:
                        self._show_latest_trace_context()
                    else:
                        self._add_system(self.agent.tracer.render_context(run_id))
                else:
                    self._add_system("Usage: /trace list | /trace show <run_id> | /trace context <run_id|latest>")
            elif line.startswith("/model"):
                self._handle_model_command(line.removeprefix("/model").strip())
            elif line == "/policy":
                self._add_system(self.agent.policy.as_tool_result().output)
            elif line.startswith("/repo"):
                rest = line.removeprefix("/repo").strip()
                if rest in {"", "build"}:
                    result = self.agent._call_tool("repo_index_build", {})
                elif rest.startswith("search "):
                    result = self.agent._call_tool("repo_index_search", {"query": rest.removeprefix("search ").strip()})
                else:
                    self._add_system("Usage: /repo build | /repo search <query>")
                    return
                self._add_system(result.output)
            elif line.startswith("/mcp"):
                rest = line.removeprefix("/mcp").strip()
                if not rest:
                    self._add_system(self.agent._call_tool("mcp_servers", {}).output)
                elif rest.startswith("add "):
                    parts = shlex.split(rest.removeprefix("add ").strip())
                    if len(parts) < 2:
                        self._add_system("Usage: /mcp add <name> <command> [args...]")
                    else:
                        self._add_system(self.agent._call_tool("mcp_add_server", {"name": parts[0], "command": parts[1], "args": parts[2:]}).output)
                elif rest.startswith("remove "):
                    name = rest.removeprefix("remove ").strip()
                    self._add_system(self.agent._call_tool("mcp_remove_server", {"name": name}).output)
                elif rest.startswith("tools"):
                    server = rest.removeprefix("tools").strip()
                    self._add_system(self.agent._call_tool("mcp_tools", {"server": server}).output)
                else:
                    self._add_system("Usage: /mcp | /mcp add <name> <command> [args...] | /mcp remove <name> | /mcp tools [server] | /run mcp_call {...}")
            elif line.startswith("/image"):
                rest = line.removeprefix("/image").strip()
                if not rest:
                    self._add_system("Usage: /image <path-or-url> [question]")
                else:
                    parts = shlex.split(rest)
                    image = parts[0]
                    question = " ".join(parts[1:]) or "请分析这张图片。"
                    self.busy = True
                    self.status = "Agent reading image..."
                    thread = threading.Thread(target=self._worker_chat_image, args=(question, image), daemon=True)
                    thread.start()
            elif line.startswith("/evolve"):
                feedback = line.removeprefix("/evolve").strip()
                if feedback in {"status", "stats"}:
                    self._add_system(self.agent.evolution.render_status())
                elif feedback in {"audit", "health"}:
                    trace_analysis = TraceEvolutionAnalyzer(self.agent.tracer).analyze()
                    eval_analysis = EvalEvolutionAnalyzer(self.agent.config.eval_results_dir).analyze_file()
                    self._add_system(self.agent.evolution.render_audit(trace_analysis=trace_analysis, eval_analysis=eval_analysis))
                elif feedback in {"trace", "analyze", "analyze-traces"}:
                    self._add_system(render_analysis(TraceEvolutionAnalyzer(self.agent.tracer).analyze()))
                elif feedback in {"apply-trace", "apply-traces"}:
                    analysis = TraceEvolutionAnalyzer(self.agent.tracer).analyze()
                    reports = apply_proposals(self.agent.evolution, analysis.proposals)
                    self._add_system(render_analysis(analysis) + "\n" + render_reports(reports))
                elif feedback.startswith("eval") or feedback.startswith("from-eval") or feedback.startswith("apply-eval"):
                    parts = shlex.split(feedback)
                    apply = bool(parts and parts[0] in {"from-eval", "apply-eval"})
                    path = self.agent.sandbox.resolve(parts[1]) if len(parts) > 1 else None
                    analysis = EvalEvolutionAnalyzer(self.agent.config.eval_results_dir).analyze_file(path)
                    body = render_analysis(analysis)
                    if apply:
                        body += "\n" + render_reports(apply_proposals(self.agent.evolution, analysis.proposals))
                    self._add_system(body)
                else:
                    report = self.agent.evolution.evolve(feedback, task="manual TUI feedback")
                    actions = "\n".join(f"- {action}" for action in report.actions)
                    self._add_system(
                        f"已进化：{report.summary()}\n"
                        f"置信度：{report.confidence:.2f}，记忆写入：{report.memory_written}\n"
                        f"动作：\n{actions}\n"
                        f"技能：{report.skill_name} ({report.skill_path})"
                    )
            elif line.startswith("/dream"):
                rest = line.removeprefix("/dream").strip()
                parts = shlex.split(rest) if rest else []
                engine = DreamEngine(self.agent)
                if parts and parts[0] in {"backlog", "candidates", "status"}:
                    self._add_system(engine.render_backlog())
                    return
                if parts and parts[0] == "verify":
                    limit = 20
                    tasks_path = None
                    promote = "--promote" in parts
                    for idx, part in enumerate(parts):
                        if part in {"--limit", "-n"} and idx + 1 < len(parts):
                            limit = int(parts[idx + 1])
                        elif part in {"--tasks", "--eval"} and idx + 1 < len(parts):
                            tasks_path = self.agent.sandbox.resolve(parts[idx + 1])
                    self._add_system(engine.render_verification(engine.verify_backlog(tasks_path=tasks_path, limit=limit, promote=promote)))
                    return
                apply = bool(parts and parts[0] in {"apply", "--apply"})
                limit = 20
                report_path = None
                min_confidence = None
                for idx, part in enumerate(parts):
                    if part in {"--limit", "-n"} and idx + 1 < len(parts):
                        limit = int(parts[idx + 1])
                    elif part in {"--report", "-r"} and idx + 1 < len(parts):
                        report_path = self.agent.sandbox.resolve(parts[idx + 1])
                    elif part in {"--min-confidence", "--threshold"} and idx + 1 < len(parts):
                        min_confidence = float(parts[idx + 1])
                dream_report = engine.run(trace_limit=limit, eval_report=report_path, apply=apply, min_confidence=min_confidence)
                self._add_system(engine.render(dream_report))
            elif line.startswith("/loop"):
                rest = line.removeprefix("/loop").strip()
                runner = LoopRunner(self.agent)
                if rest in {"", "list"}:
                    self._add_system(render_loop_specs(runner.list_specs()))
                elif rest.startswith("show "):
                    spec = runner.load(rest.removeprefix("show ").strip())
                    self._add_system(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
                elif rest.startswith("run "):
                    self.busy = True
                    self.status = "Running loop..."
                    thread = threading.Thread(target=self._worker_loop, args=(rest.removeprefix("run ").strip(),), daemon=True)
                    thread.start()
                else:
                    self._add_system("Usage: /loop list | /loop show <loop_id|path> | /loop run <loop_id|path>")
            elif line.startswith("/run"):
                self.busy = True
                self.status = "Running tool..."
                thread = threading.Thread(target=self._worker_run_tool, args=(line,), daemon=True)
                thread.start()
            else:
                self._add_system("Unknown command. Use /help.")
        except Exception as exc:
            self._add_error(str(exc))

    def _handle_model_command(self, value: str) -> None:
        if not value:
            choices = ", ".join(self._model_choices()) or "set EVOLVA_MODEL_CHOICES=model-a,model-b"
            self._add_system(
                f"Current model: {self.agent.config.model}\n"
                f"Provider: {self.agent.config.base_url}\n"
                f"API key: {mask_secret(self.agent.config.api_key)}\n"
                f"Temperature: {self.agent.config.temperature}\n"
                f"Available shortcuts: {choices}\n"
                f"Switch with /model <name>, configure with /config wizard, or press F2/F4."
            )
            return
        if value in {"next", "cycle"}:
            value = self._next_model()
        switched = self.agent.set_model(value)
        self.status = f"Model switched to {switched}"
        self._add_system(f"Switched model: {switched}")

    def _handle_config_command(self, value: str) -> None:
        if not value:
            self._add_system(
                "Provider configuration\n"
                f"- model: {self.agent.config.model}\n"
                f"- base_url: {self.agent.config.base_url}\n"
                f"- api_key: {mask_secret(self.agent.config.api_key)}\n"
                f"- temperature: {self.agent.config.temperature}\n"
                f"- local file: {self.agent.config.runtime_config_file}\n\n"
                "Commands:\n"
                "  /config wizard\n"
                "  /config set model <name>\n"
                "  /config set base_url <url>\n"
                "  /config set temperature <number>\n"
                "  /config set api_key <key>\n"
                "  /config clear api_key"
            )
            return
        if value == "wizard":
            self._start_config_wizard()
            return
        if value.startswith("set "):
            self._config_set(value.removeprefix("set ").strip())
            return
        if value.startswith("clear "):
            key = value.removeprefix("clear ").strip()
            if key not in {"api_key", "model", "base_url", "temperature"}:
                self._add_system("Usage: /config clear api_key|model|base_url|temperature")
                return
            data = remove_runtime_config_keys([key], self.agent.config.runtime_config_file)
            defaults = AgentConfig(root=self.agent.config.root)
            if key == "api_key":
                self.agent.update_llm_config(api_key="")
            elif key == "model":
                self.agent.update_llm_config(model=defaults.model)
            elif key == "base_url":
                self.agent.update_llm_config(base_url=defaults.base_url)
            elif key == "temperature":
                self.agent.update_llm_config(temperature=defaults.temperature)
            self._add_system(f"Cleared {key}. Remaining saved keys: {', '.join(data.keys()) or 'none'}")
            return
        self._add_system("Usage: /config | /config wizard | /config set <model|base_url|temperature|api_key> <value> | /config clear api_key")

    def _config_set(self, rest: str) -> None:
        if not rest:
            self._add_system("Usage: /config set <model|base_url|temperature|api_key> <value>")
            return
        try:
            key, raw_value = rest.split(maxsplit=1)
        except ValueError:
            self._add_system("Usage: /config set <model|base_url|temperature|api_key> <value>")
            return
        key = key.strip()
        if key not in {"api_key", "model", "base_url", "temperature"}:
            self._add_system("Supported keys: model, base_url, api_key, temperature")
            return
        value: str | float = raw_value.strip()
        if key == "temperature":
            value = float(value)
        save_runtime_config({key: value}, self.agent.config.runtime_config_file)
        self.agent.update_llm_config(**{key: value})
        shown = mask_secret(str(value)) if key == "api_key" else value
        self.status = f"Saved {key}."
        self._add_system(f"Saved {key}: {shown}\nEffective model: {self.agent.config.model}\nProvider: {self.agent.config.base_url}\nAPI key: {mask_secret(self.agent.config.api_key)}")

    def _start_config_wizard(self) -> None:
        fields = ["model", "base_url", "temperature", "api_key"]
        self.config_wizard = {"fields": fields, "index": 0, "values": {}}
        self.input_text = self.agent.config.model
        self.status = "Config wizard: model. Press Enter to accept/edit, Esc to cancel."
        self._add_system(
            "Provider setup wizard started.\n"
            "Edit each value in the input bar and press Enter. Leave API key empty to keep the current key.\n"
            "Secrets are masked in the TUI and saved only to the local git-ignored runtime config."
        )

    def _handle_config_wizard_input(self, value: str) -> None:
        wizard = self.config_wizard
        if wizard is None:
            return
        fields: list[str] = wizard["fields"]
        index = int(wizard["index"])
        field = fields[index]
        values: dict[str, Any] = wizard["values"]
        if field == "model":
            values[field] = value or self.agent.config.model
        elif field == "base_url":
            values[field] = value or self.agent.config.base_url
        elif field == "temperature":
            values[field] = float(value) if value else self.agent.config.temperature
        elif field == "api_key" and value:
            values[field] = value
        index += 1
        if index >= len(fields):
            self.config_wizard = None
            save_runtime_config(values, self.agent.config.runtime_config_file)
            self.agent.update_llm_config(**values)
            self._add_system(
                "Provider config saved.\n"
                f"- model: {self.agent.config.model}\n"
                f"- base_url: {self.agent.config.base_url}\n"
                f"- api_key: {mask_secret(self.agent.config.api_key)}\n"
                f"- temperature: {self.agent.config.temperature}"
            )
            self.status = "Provider config saved."
            return
        wizard["index"] = index
        next_field = fields[index]
        defaults = {
            "base_url": self.agent.config.base_url,
            "temperature": str(self.agent.config.temperature),
            "api_key": "",
        }
        self.input_text = defaults.get(next_field, "")
        self.status = f"Config wizard: {next_field}. Press Enter to continue, Esc to cancel."

    def _sanitize_display_line(self, line: str) -> str:
        if line.startswith("/config set api_key"):
            return "/config set api_key <hidden>"
        return line

    def _worker_config_wizard(self) -> None:
        # Kept as a compatibility no-op target for external tests/extensions.
        try:
            self.queue.put(("system", "Use /config wizard inside the TUI to configure provider settings."))
        except Exception as exc:
            self.queue.put(("error", f"Config wizard error: {exc}"))

    def _model_choices(self) -> list[str]:
        raw = os.getenv("EVOLVA_MODEL_CHOICES", "")
        choices = [item.strip() for item in raw.split(",") if item.strip()]
        if self.agent.config.model not in choices:
            choices.insert(0, self.agent.config.model)
        return list(dict.fromkeys(choices))

    def _next_model(self) -> str:
        choices = self._model_choices()
        if len(choices) <= 1:
            return self.agent.config.model
        current = self.agent.config.model
        idx = choices.index(current) if current in choices else -1
        return choices[(idx + 1) % len(choices)]

    def _show_recent_traces(self) -> None:
        rows = self.agent.tracer.list_runs()
        body = "\n".join(f"- {r['run_id']} status={r['status']} duration={r['duration_ms']}ms input={r['user_input']}" for r in rows) or "No traces"
        self._add_system(body)

    def _show_latest_trace_context(self) -> None:
        rows = self.agent.tracer.list_runs(limit=1)
        if not rows:
            self._add_system("No traces")
            return
        self._add_system(self.agent.tracer.render_context(rows[0]["run_id"]))

    def _worker_run_tool(self, line: str) -> None:
        try:
            rest = line.removeprefix("/run").strip()
            if not rest:
                self.queue.put(("system", "Usage: /run <tool> <json>"))
                return
            try:
                name, args_text = rest.split(maxsplit=1)
                args: dict[str, Any] = json.loads(args_text)
            except ValueError:
                parts = shlex.split(rest)
                name = parts[0]
                args = {}
            result = self.agent._call_tool(name, args)
            self.queue.put(("tool_result", (name, result.ok, result.output)))
        except Exception as exc:
            self.queue.put(("error", f"Tool error: {exc}"))

    def _worker_loop(self, loop_id: str) -> None:
        try:
            result = LoopRunner(self.agent).run(loop_id)
            self.queue.put(("loop_result", result))
        except Exception as exc:
            self.queue.put(("error", f"Loop error: {exc}"))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except Empty:
                break
            if kind == "agent_result":
                result: TurnResult = payload
                if result.tool_logs:
                    self.tool_logs.extend(result.tool_logs)
                self._add_agent(result.answer)
                self.busy = False
                self.status = "Ready"
            elif kind == "tool_result":
                name, ok, output = payload
                prefix = f"TOOL {name} -> ok={ok}"
                self.tool_logs.append(prefix + "\n" + output)
                self._add_system(prefix + "\n" + output)
                self.busy = False
                self.status = "Ready"
            elif kind == "loop_result":
                rendered = render_loop_result(payload)
                self.tool_logs.append(rendered)
                self._add_system(rendered)
                self.busy = False
                self.status = "Ready"
            elif kind == "system":
                self._add_system(str(payload))
                self.busy = False
                self.status = "Ready"
            elif kind == "error":
                self._add_error(str(payload))
                self.busy = False
                self.status = "Error"

    def _add_user(self, text: str) -> None:
        self.messages.append(ChatLine("You", text, self._now()))

    def _add_agent(self, text: str) -> None:
        self.messages.append(ChatLine("Agent", text, self._now()))

    def _add_system(self, text: str) -> None:
        self.messages.append(ChatLine("System", text, self._now()))

    def _add_error(self, text: str) -> None:
        self.messages.append(ChatLine("Error", text, self._now()))

    def _now(self) -> str:
        return time.strftime("%H:%M:%S")

    def _draw(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 10 or w < 50:
            stdscr.addnstr(0, 0, "Terminal too small for Evolva Workbench", max(0, w - 1))
            stdscr.refresh()
            return

        input_h = 3
        status_h = 1
        title_h = 7
        body_h = h - input_h - status_h - title_h
        tool_w = min(42, max(32, w // 3)) if self.show_tools and self.tool_logs and w >= 120 else 0
        chat_w = w - tool_w

        self._draw_title(0, w)
        self._draw_chat(title_h, 0, body_h, chat_w)
        if tool_w:
            self._draw_tools(title_h, chat_w, body_h, tool_w)
        self._draw_status(h - input_h - status_h, w)
        self._draw_input(h - input_h, w)
        stdscr.refresh()

    def _draw_title(self, y: int, w: int) -> None:
        icon = [
            "╭───────●",
            "│  ╭───●",
            "│  ╰───●",
            "●──╮",
            "│  ╰───●",
            "╰───────●",
        ]
        brand_x = 2 if w >= 72 else 1
        text_x = 20 if w >= 72 else 14
        version = self._project_version()
        model = self._model_label()
        provider = self._provider_label()
        cwd = self._path_label(max(12, w - text_x - 2))
        title = f"E V O L A  Agent Workbench"
        subtitle = f"v{version} · " + (f"{provider}_{model}" if provider != "local rule-mode" else "local_rule-mode")
        for idx, row in enumerate(icon):
            self.stdscr.addnstr(y + idx, brand_x, row[: max(1, w - brand_x - 1)], max(1, w - brand_x - 1), self._color(8, curses.A_BOLD))
        self.stdscr.addnstr(y + 1, text_x, title[: max(1, w - text_x - 1)], max(1, w - text_x - 1), self._color(8, curses.A_BOLD))
        self.stdscr.addnstr(y + 2, text_x, subtitle[: max(1, w - text_x - 1)], max(1, w - text_x - 1), self._color(7))
        self.stdscr.addnstr(y + 3, text_x, cwd[: max(1, w - text_x - 1)], max(1, w - text_x - 1), self._color(7))
        self.stdscr.addnstr(y + 6, 0, "─" * max(0, w - 1), w - 1, self._color(8))

    def _draw_chat(self, y: int, x: int, h: int, w: int) -> None:
        lines: list[tuple[str, int]] = []
        for msg in self.messages:
            color = self._role_color(msg.role)
            prefix = self._role_label(msg.role)
            wrapped = self._wrap(msg.text, max(10, w - len(prefix) - 2))
            for idx, part in enumerate(wrapped):
                lines.append(((prefix if idx == 0 else " " * len(prefix)) + part, color))
            lines.append(("", 0))
        if not lines:
            self._draw_empty_chat(y, x, h, w)
            return
        visible = lines[max(0, len(lines) - h - self.scroll) : max(0, len(lines) - self.scroll) if self.scroll else len(lines)]
        start = max(0, h - len(visible))
        for idx, (line, color) in enumerate(visible[-h:]):
            attr = self._color(color) if color else curses.A_NORMAL
            self.stdscr.addnstr(y + start + idx, x, line.ljust(w), w - 1, attr)
        if self.scroll:
            marker = f"-- scrolled {self.scroll} --"
            self.stdscr.addnstr(y, x + max(0, w - len(marker) - 1), marker, len(marker), self._color(3))

    def _draw_tools(self, y: int, x: int, h: int, w: int) -> None:
        for row in range(h):
            self._safe_addch(y + row, x, getattr(curses, "ACS_VLINE", "│"), self._color(6))
        title = " Trace / Tool Stream "
        self.stdscr.addnstr(y, x + 2, title.ljust(w - 3), w - 3, self._color(4, curses.A_BOLD))
        raw_lines: list[str] = []
        for log in self.tool_logs[-20:]:
            raw_lines.extend(self._wrap(log, max(10, w - 3)))
            raw_lines.append("-" * max(1, w - 3))
        if not raw_lines:
            raw_lines = ["No tool calls yet.", "", "Run /tools, /mcp, /repo", "or ask Evolva to act."]
        visible = raw_lines[-(h - 1) :]
        for i, line in enumerate(visible, start=1):
            self.stdscr.addnstr(y + i, x + 2, line.ljust(w - 3), w - 3, self._color(4 if self.tool_logs else 7))

    def _draw_status(self, y: int, w: int) -> None:
        state = "THINKING" if self.busy else "READY"
        if self.status and self.status not in {"Ready", "ready", ""}:
            state = self.status
        left = f"  {state} · {self._provider_label()} · {self._model_label()} · tools:{'on' if self.show_tools else 'off'}"
        right = f"{self._token_estimate()} tokens  "
        line = left
        available = max(0, w - len(right) - 1)
        self.stdscr.addnstr(y, 0, line[:available].ljust(available), available, self._color(7))
        self.stdscr.addnstr(y, max(0, w - len(right) - 1), right[: max(0, w - 1)], max(0, min(len(right), w - 1)), self._color(7))

    def _draw_input(self, y: int, w: int) -> None:
        self.stdscr.addnstr(y, 0, "─" * max(0, w - 1), w - 1, self._color(7))
        prompt = "You › "
        self.stdscr.addnstr(y + 1, 1, prompt, max(1, w - 2), self._color(8, curses.A_BOLD))
        width = max(1, w - len(prompt) - 1)
        display = self.input_text[-width:]
        placeholder = "What's on your mind?" if not display else display
        if self.config_wizard is not None and self.config_wizard["fields"][self.config_wizard["index"]] == "api_key" and display:
            placeholder = "*" * min(len(display), width)
        attr = curses.A_NORMAL if display else self._color(7)
        self.stdscr.addnstr(y + 1, 1 + len(prompt), placeholder.ljust(width), width, attr)
        self.stdscr.move(y + 1, min(w - 2, 1 + len(prompt) + len(display)))
        self.stdscr.addnstr(y + 2, 0, "─" * max(0, w - 1), w - 1, self._color(7))

    def _wrap(self, text: str, width: int) -> list[str]:
        out: list[str] = []
        for raw in text.splitlines() or [""]:
            if not raw:
                out.append("")
                continue
            out.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [raw[:width]])
        return out

    def _role_color(self, role: str) -> int:
        return {"You": 7, "Agent": 8, "System": 7, "Error": 5}.get(role, 0)

    def _role_label(self, role: str) -> str:
        return {"You": "❯ ", "Agent": "⏺ ", "System": "• ", "Error": "✕ "}.get(role, f"{role.upper()} ")

    def _draw_empty_chat(self, y: int, x: int, h: int, w: int) -> None:
        if h <= 3 or w <= 70:
            return
        hero = "Evolva is a local-first Agent Harness. Start with /config wizard, /repo build, /dream, or /help."
        hint = "F4 config · F2 model · ^R trace · ^X context · ^T tools · /help"
        self.stdscr.addnstr(y + max(1, h // 2 - 1), x + 2, hero[: max(1, w - 4)], max(1, w - 4), self._color(8, curses.A_BOLD))
        self.stdscr.addnstr(y + h - 1, x + 2, hint[: max(1, w - 4)], max(1, w - 4), self._color(7))

    def _safe_addch(self, y: int, x: int, ch: Any, attr: int = 0) -> None:
        try:
            self.stdscr.addch(y, x, ch, attr)
        except curses.error:
            pass

    def _project_version(self) -> str:
        if self._cached_version is not None:
            return self._cached_version
        try:
            self._cached_version = importlib.metadata.version("evolva")
        except importlib.metadata.PackageNotFoundError:
            self._cached_version = "0.1.0"
        return self._cached_version

    def _provider_label(self) -> str:
        if not self.agent.llm.available:
            return "local rule-mode"
        base_url = self.agent.config.base_url.rstrip("/")
        if "openai" in base_url.lower():
            return "openai"
        if "ark" in base_url.lower() or "volc" in base_url.lower():
            return "ark"
        return base_url.split("//")[-1].split("/")[0] or "provider"

    def _model_label(self) -> str:
        return self.agent.config.model if self.agent.llm.available else "rule-mode"

    def _path_label(self, width: int) -> str:
        path = str(self.agent.config.root)
        home = os.path.expanduser("~")
        if path.startswith(home):
            path = "~" + path[len(home):]
        if len(path) <= width:
            return path
        return "…" + path[-max(1, width - 1):]

    def _token_estimate(self) -> int:
        text = "\n".join(msg.text for msg in self.messages) + "\n" + self.input_text
        # Fast local approximation for the footer; exact provider tokenization is intentionally optional.
        return max(0, len(text) // 4)


def run_tui(assume_yes: bool = False, show_tools: bool = True) -> int:
    """Run Evolva's default inline TUI without taking over the full terminal."""

    return EvolvaInlineTUI(assume_yes=assume_yes, show_tools=show_tools).run()


def run_fullscreen_tui(assume_yes: bool = False, show_tools: bool = True) -> int:
    """Run the legacy curses renderer for users that explicitly want a full-screen TUI."""

    return EvolvaTUI(assume_yes=assume_yes, show_tools=show_tools).run()


class EvolvaInlineTUI:
    """Non-fullscreen terminal workbench inspired by modern Ink-style CLIs.

    The renderer keeps Evolva inside the normal terminal scrollback instead of
    clearing the whole screen. It reuses the same command and agent runtime as
    the curses TUI, but prints compact header/message/input blocks inline.
    """

    def __init__(self, assume_yes: bool = False, show_tools: bool = True):
        self.app = EvolvaTUI(assume_yes=assume_yes, show_tools=show_tools)
        self.show_tools = show_tools
        self._printed_messages = 0
        self._interrupt_armed = False

    def run(self) -> int:
        self._print_header()
        if not self.app.agent.llm.available:
            print(self._dim("local mode · use /config wizard or F4 in fullscreen mode to connect a model"))
        while True:
            try:
                line = input(self._primary("› ")).strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                if self._interrupt_armed:
                    print(f"\n{self._dim('bye · Evolva session closed')}")
                    return 0
                self._interrupt_armed = True
                print(f"\n{self._dim('Press Ctrl+C again to exit, or type /exit.')}")
                continue
            if not line:
                continue
            self._interrupt_armed = False
            if line in {"/exit", "/quit"}:
                return 0
            if line == "/config wizard":
                self._config_wizard()
                continue
            if line.startswith("/"):
                self.app._handle_command(line)
                self._wait_for_background()
                self._flush_messages()
                continue
            print(self._user(line))
            self.app.busy = True
            self.app.status = "thinking"
            try:
                result = self.app.agent.chat(line)
            except Exception as exc:
                print(self._error(f"Agent error: {exc}"))
                self.app.busy = False
                continue
            self.app.busy = False
            if self.show_tools and result.tool_logs:
                for log in result.tool_logs:
                    print(self._tool(log))
            print(self._agent(result.answer))

    def _print_header(self) -> None:
        version = self.app._project_version()
        provider = self.app._provider_label()
        model = self.app._model_label()
        subtitle = f"{provider}_{model}" if provider != "local rule-mode" else "local_rule-mode"
        cwd = self.app._path_label(96)
        icon = ["╭───────●", "│  ╭───●", "│  ╰───●", "●──╮", "│  ╰───●", "╰───────●"]
        width = self._workbench_width()
        inner = width - 4
        rows = [
            f"{icon[0]:<14} E V O L A  Agent Workbench  v{version}",
            f"{icon[1]:<14} {subtitle}",
            f"{icon[2]:<14} {cwd}",
            f"{icon[3]:<14} Trace · Eval · Dream · Loop · MCP · Memory · Guardrails",
            f"{icon[4]:<14} /model  /mcp  /trace context latest  /loop run dream-loop",
            f"{icon[5]:<14} F2 model · F4 config · Ctrl+R trace · Ctrl+X context",
        ]
        print()
        print(self._primary("╭─ Evolva TUI Workbench " + "─" * max(0, width - 25) + "╮"))
        for row in rows:
            print(self._primary("│ ") + self._fit(row, inner) + self._primary(" │"))
        print(self._primary("╰" + "─" * (width - 2) + "╯"))

    def _flush_messages(self) -> None:
        for msg in self.app.messages[self._printed_messages :]:
            if msg.role == "You":
                print(self._user(msg.text))
            elif msg.role == "Agent":
                print(self._agent(msg.text))
            elif msg.role == "Error":
                print(self._error(msg.text))
            else:
                print(self._system(msg.text))
        self._printed_messages = len(self.app.messages)

    def _wait_for_background(self) -> None:
        while self.app.busy:
            self.app._drain_queue()
            time.sleep(0.05)
        self.app._drain_queue()

    def _config_wizard(self) -> None:
        print(self._system("Provider setup wizard. Values are saved to local git-ignored runtime config."))
        values: dict[str, Any] = {}
        model = input(f"model [{self.app.agent.config.model}]: ").strip()
        base_url = input(f"base_url [{self.app.agent.config.base_url}]: ").strip()
        temperature = input(f"temperature [{self.app.agent.config.temperature}]: ").strip()
        api_key = input("api_key [keep current]: ").strip()
        if model:
            values["model"] = model
        if base_url:
            values["base_url"] = base_url
        if temperature:
            values["temperature"] = float(temperature)
        if api_key:
            values["api_key"] = api_key
        if not values:
            print(self._dim("No changes."))
            return
        save_runtime_config(values, self.app.agent.config.runtime_config_file)
        self.app.agent.update_llm_config(**values)
        print(self._system(f"Provider config saved. model={self.app.agent.config.model}, api_key={mask_secret(self.app.agent.config.api_key)}"))

    def _terminal_width(self) -> int:
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 96

    def _workbench_width(self) -> int:
        """Return a stable content width for the inline workbench."""
        return min(118, max(72, self._terminal_width() - 2))

    def _fit(self, text: str, width: int) -> str:
        if len(text) > width:
            text = text[: max(0, width - 1)] + "…"
        return text.ljust(width)

    def _wrap_text(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for raw in text.splitlines() or [""]:
            if not raw:
                lines.append("")
                continue
            lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [raw[:width]])
        return lines

    def _panel(self, title: str, text: str, *, accent: bool = True) -> str:
        width = self._workbench_width()
        inner = width - 4
        paint = self._primary if accent else self._dim
        label = f" {title} "
        lines = [paint("╭─" + label + "─" * max(0, width - len(label) - 3) + "╮")]
        for part in self._wrap_text(text, inner):
            lines.append(paint("│ ") + self._fit(part, inner) + paint(" │"))
        lines.append(paint("╰" + "─" * (width - 2) + "╯"))
        return "\n".join(lines)

    def _ansi(self, code: str, text: str) -> str:
        if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
            return text
        return f"\033[{code}m{text}\033[0m"

    def _primary(self, text: str) -> str:
        return self._ansi("38;5;220;1", text)

    def _dim(self, text: str) -> str:
        return self._ansi("90", text)

    def _user(self, text: str) -> str:
        return f"{self._ansi('97;1', 'You ›')} {text}"

    def _agent(self, text: str) -> str:
        return self._panel("Evolva", text, accent=True)

    def _system(self, text: str) -> str:
        return self._panel("System", text, accent=False)

    def _tool(self, text: str) -> str:
        return self._panel("Trace / Tool Stream", text, accent=False)

    def _error(self, text: str) -> str:
        return self._panel("Error", text, accent=False)
