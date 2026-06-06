from __future__ import annotations

import curses
import json
import os
import shlex
import textwrap
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

from evolva.agent.evolution_analyzer import EvalEvolutionAnalyzer, TraceEvolutionAnalyzer, apply_proposals, render_analysis, render_reports
from evolva.agent.core import EvolvaAgent, TurnResult
from evolva.config import AgentConfig


TUI_HELP = """
TUI keys:
  Enter          Send message or command
  Ctrl+L         Clear screen messages
  Ctrl+T         Toggle tool log panel
  Ctrl+R         Show recent traces
  Ctrl+X         Show latest trace context events
  F2             Prepare /model command
  PgUp/PgDn      Scroll chat
  Up/Down        Navigate input history
  Esc            Cancel current input line
  /exit          Quit

Commands:
  /help, /tools, /skills, /memory [query|stats|recent n], /context [query], /todo, /agents, /trace [list|show|context], /model [name], /policy, /mcp, /image <path|url> [text], /evolve [feedback|status|audit|trace|apply-trace|eval|apply-eval], /run <tool> <json>
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
        self.scroll = 0
        self.status = "Ready"
        self.busy = False
        self.queue: Queue[tuple[str, Any]] = Queue()
        self.confirmation_prompt: str | None = None
        self.confirmation_event: threading.Event | None = None
        self.confirmation_answer: bool | None = None
        self.stdscr: Any = None

    def run(self) -> int:
        return curses.wrapper(self._main)

    def _main(self, stdscr: Any) -> int:
        self.stdscr = stdscr
        curses.curs_set(1)
        curses.use_default_colors()
        self._init_colors()
        stdscr.keypad(True)
        stdscr.timeout(100)
        self._add_system("Evolva TUI started. Type /help for commands, /exit to quit.")
        if not self.agent.llm.available:
            self._add_system("未检测到 OPENAI_API_KEY，当前使用有限规则模式。")

        while True:
            self._drain_queue()
            self._draw()
            ch = stdscr.getch()
            if ch == -1:
                continue
            if self._handle_key(ch) is False:
                return 0

    def _init_colors(self) -> None:
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, -1)    # user
        curses.init_pair(2, curses.COLOR_GREEN, -1)   # agent
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # system/status
        curses.init_pair(4, curses.COLOR_MAGENTA, -1) # tools
        curses.init_pair(5, curses.COLOR_RED, -1)     # errors

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

    def _handle_key(self, ch: int) -> bool | None:
        if self.confirmation_event is not None:
            if ch in (ord("y"), ord("Y")):
                self.confirmation_answer = True
                self.status = "Tool approved."
                self.confirmation_event.set()
            elif ch in (ord("n"), ord("N"), 27, curses.KEY_ENTER, 10, 13):
                self.confirmation_answer = False
                self.status = "Tool denied."
                self.confirmation_event.set()
            return None
        if self.busy:
            if ch in (curses.KEY_PPAGE,):
                self.scroll += 3
            elif ch in (curses.KEY_NPAGE,):
                self.scroll = max(0, self.scroll - 3)
            return None

        if ch in (10, 13, curses.KEY_ENTER):
            line = self.input_text.strip()
            self.input_text = ""
            self.history_index = None
            if not line:
                return None
            self.history.append(line)
            if line in {"/exit", "/quit"}:
                return False
            self._submit(line)
            return None
        if ch == 12:  # Ctrl+L
            self.messages.clear()
            self.tool_logs.clear()
            self.scroll = 0
            self.status = "Cleared."
            return None
        if ch == 20:  # Ctrl+T
            self.show_tools = not self.show_tools
            self.status = "Tool panel " + ("on" if self.show_tools else "off")
            return None
        if ch == 18:  # Ctrl+R
            self._show_recent_traces()
            return None
        if ch == 24:  # Ctrl+X
            self._show_latest_trace_context()
            return None
        if ch == curses.KEY_F2:
            self.input_text = "/model "
            self.status = "Type a model name, then Enter. Use /model to view current model."
            return None
        if ch == 10:  # unreachable due Enter branch, kept for clarity
            return None
        if ch == 27:  # Esc
            self.input_text = ""
            self.status = "Input cleared."
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self.input_text = self.input_text[:-1]
            return None
        if ch == curses.KEY_PPAGE:
            self.scroll += 5
            return None
        if ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 5)
            return None
        if ch == curses.KEY_UP:
            if self.history:
                if self.history_index is None:
                    self.history_index = len(self.history) - 1
                else:
                    self.history_index = max(0, self.history_index - 1)
                self.input_text = self.history[self.history_index]
            return None
        if ch == curses.KEY_DOWN:
            if self.history_index is not None:
                self.history_index += 1
                if self.history_index >= len(self.history):
                    self.history_index = None
                    self.input_text = ""
                else:
                    self.input_text = self.history[self.history_index]
            return None
        if ch == 9:  # Tab quick complete common slash commands
            self._complete_command()
            return None
        if 32 <= ch <= 0x10FFFF:
            try:
                self.input_text += chr(ch)
            except ValueError:
                pass
        return None

    def _complete_command(self) -> None:
        commands = ["/help", "/tools", "/skills", "/memory", "/context", "/todo", "/agents", "/trace", "/model", "/policy", "/repo", "/mcp", "/image", "/evolve", "/run", "/exit"]
        matches = [c for c in commands if c.startswith(self.input_text)]
        if len(matches) == 1:
            self.input_text = matches[0] + (" " if matches[0] not in {"/help", "/tools", "/skills", "/exit"} else "")
            self.status = f"Completed {matches[0]}"
        elif matches:
            self.status = "Matches: " + ", ".join(matches)

    def _submit(self, line: str) -> None:
        self.scroll = 0
        self._add_user(line)
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
                elif rest.startswith("tools"):
                    server = rest.removeprefix("tools").strip()
                    self._add_system(self.agent._call_tool("mcp_tools", {"server": server}).output)
                else:
                    self._add_system("Usage: /mcp | /mcp tools [server] | /run mcp_call {...}")
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
            self._add_system(f"Current model: {self.agent.config.model}\nAvailable shortcuts: {choices}\nSwitch with /model <name> or F2.")
            return
        if value in {"next", "cycle"}:
            value = self._next_model()
        switched = self.agent.set_model(value)
        self.status = f"Model switched to {switched}"
        self._add_system(f"Switched model: {switched}")

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
        if h < 8 or w < 40:
            stdscr.addnstr(0, 0, "Terminal too small for Evolva TUI", max(0, w - 1))
            stdscr.refresh()
            return

        input_h = 3
        status_h = 1
        title_h = 1
        body_h = h - input_h - status_h - title_h
        tool_w = min(48, max(30, w // 3)) if self.show_tools and w >= 90 else 0
        chat_w = w - tool_w

        self._draw_title(0, w)
        self._draw_chat(1, 0, body_h, chat_w)
        if tool_w:
            self._draw_tools(1, chat_w, body_h, tool_w)
        self._draw_status(h - input_h - status_h, w)
        self._draw_input(h - input_h, w)
        stdscr.refresh()

    def _draw_title(self, y: int, w: int) -> None:
        model = self.agent.config.model if self.agent.llm.available else "rule-mode"
        title = f" Evolva TUI | model={model} | F2 model | Ctrl+R traces | Ctrl+X ctx | Ctrl+T tools | /help "
        self.stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
        self.stdscr.addnstr(y, 0, title.ljust(w), w - 1)
        self.stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

    def _draw_chat(self, y: int, x: int, h: int, w: int) -> None:
        lines: list[tuple[str, int]] = []
        for msg in self.messages:
            color = self._role_color(msg.role)
            prefix = f"[{msg.ts}] {msg.role}: "
            wrapped = self._wrap(prefix + msg.text, max(10, w - 2))
            for part in wrapped:
                lines.append((part, color))
            lines.append(("", 0))
        visible = lines[max(0, len(lines) - h - self.scroll) : max(0, len(lines) - self.scroll) if self.scroll else len(lines)]
        start = max(0, h - len(visible))
        for idx, (line, color) in enumerate(visible[-h:]):
            attr = curses.color_pair(color) if color else curses.A_NORMAL
            self.stdscr.addnstr(y + start + idx, x, line.ljust(w), w - 1, attr)
        if self.scroll:
            marker = f"-- scrolled {self.scroll} --"
            self.stdscr.addnstr(y, x + max(0, w - len(marker) - 1), marker, len(marker), curses.color_pair(3))

    def _draw_tools(self, y: int, x: int, h: int, w: int) -> None:
        for row in range(h):
            self.stdscr.addch(y + row, x, curses.ACS_VLINE)
        title = " Tool Logs "
        self.stdscr.addnstr(y, x + 1, title.ljust(w - 2), w - 2, curses.color_pair(4) | curses.A_BOLD)
        raw_lines: list[str] = []
        for log in self.tool_logs[-20:]:
            raw_lines.extend(self._wrap(log, max(10, w - 3)))
            raw_lines.append("-" * max(1, w - 3))
        visible = raw_lines[-(h - 1) :]
        for i, line in enumerate(visible, start=1):
            self.stdscr.addnstr(y + i, x + 1, line.ljust(w - 2), w - 2, curses.color_pair(4))

    def _draw_status(self, y: int, w: int) -> None:
        left = " BUSY " if self.busy else " READY "
        status = f"{left} {self.status}"
        self.stdscr.addnstr(y, 0, status.ljust(w), w - 1, curses.color_pair(3) | curses.A_REVERSE)

    def _draw_input(self, y: int, w: int) -> None:
        prompt = "You> "
        self.stdscr.addnstr(y, 0, prompt, w - 1, curses.A_BOLD)
        width = max(1, w - len(prompt) - 1)
        display = self.input_text[-width:]
        self.stdscr.addnstr(y, len(prompt), display.ljust(width), width)
        self.stdscr.move(y, min(w - 2, len(prompt) + len(display)))
        hint = "Enter send | Tab complete | F2 model | Ctrl+R traces | Ctrl+X trace ctx | Esc clear"
        self.stdscr.addnstr(y + 1, 0, hint.ljust(w), w - 1, curses.color_pair(3))

    def _wrap(self, text: str, width: int) -> list[str]:
        out: list[str] = []
        for raw in text.splitlines() or [""]:
            if not raw:
                out.append("")
                continue
            out.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [raw[:width]])
        return out

    def _role_color(self, role: str) -> int:
        return {"You": 1, "Agent": 2, "System": 3, "Error": 5}.get(role, 0)


def run_tui(assume_yes: bool = False, show_tools: bool = True) -> int:
    return EvolvaTUI(assume_yes=assume_yes, show_tools=show_tools).run()
