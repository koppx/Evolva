from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

from evolva.agent.core import EvolvaAgent
from evolva.config import AgentConfig
from evolva.eval.harness import EvalHarness, render_results
from evolva.tui import run_tui
from evolva.workflow.engine import WorkflowEngine


HELP = """
Commands:
  /help                Show this help
  /tools               List tools
  /skills              List skills
  /memory [query]      Show/search memory
  /context [query]     Show/search persistent context
  /todo                Show todo list
  /todo add <title>    Add a todo
  /todo done <id>      Mark a todo done
  /agents              List role agents
  /trace list          List recent traces
  /trace show <run>    Show a trace
  /policy              Show guardrail policy
  /evolve [feedback]   Turn feedback into memory + skill
  /workflow <json>     Run a workflow spec file
  /run <tool> <json>   Call a tool directly
  /exit                Quit
""".strip()


def print_block(title: str, body: str) -> None:
    print(f"\n--- {title} ---")
    print(body if body.strip() else "(empty)")


def handle_command(agent: EvolvaAgent, line: str) -> bool:
    if line in {"/exit", "/quit"}:
        return False
    if line == "/help":
        print(HELP)
        return True
    if line == "/tools":
        print(agent.tools.describe())
        return True
    if line == "/skills":
        skills = agent.skills.list()
        print("\n".join(f"- {s.name}: {s.path}" for s in skills) or "No skills")
        return True
    if line.startswith("/memory"):
        query = line.removeprefix("/memory").strip()
        print(agent.memory.context(query))
        return True
    if line.startswith("/context"):
        query = line.removeprefix("/context").strip()
        print(agent.context.render(query=query))
        return True
    if line.startswith("/todo"):
        rest = line.removeprefix("/todo").strip()
        if not rest:
            print(agent.todos.render(include_done=True))
        elif rest.startswith("add "):
            item = agent.todos.add(rest.removeprefix("add ").strip())
            print(f"Added todo #{item.id}: {item.title}")
        elif rest.startswith("done "):
            item = agent.todos.update(int(rest.removeprefix("done ").strip()), status="done")
            print(f"Done todo #{item.id}: {item.title}")
        else:
            print("Usage: /todo | /todo add <title> | /todo done <id>")
        return True
    if line == "/agents":
        print(agent.coordinator.list_roles())
        return True
    if line.startswith("/trace"):
        rest = line.removeprefix("/trace").strip()
        if rest in {"", "list"}:
            rows = agent.tracer.list_runs()
            print("\n".join(f"- {r['run_id']} status={r['status']} duration={r['duration_ms']}ms input={r['user_input']}" for r in rows) or "No traces")
        elif rest.startswith("show "):
            print(agent.tracer.render(rest.removeprefix("show ").strip()))
        else:
            print("Usage: /trace list | /trace show <run_id>")
        return True
    if line == "/policy":
        print(agent.policy.as_tool_result().output)
        return True
    if line.startswith("/evolve"):
        feedback = line.removeprefix("/evolve").strip()
        report = agent.evolution.evolve(feedback, task="manual CLI feedback")
        print(f"已进化：{report.lesson}\n技能：{report.skill_name} ({report.skill_path})")
        return True
    if line.startswith("/workflow"):
        path = line.removeprefix("/workflow").strip()
        if not path:
            print("Usage: /workflow <json-spec-path>")
            return True
        output = WorkflowEngine(agent).run_file(agent.sandbox.resolve(path))
        print("\n".join(output.logs))
        print(f"Workflow {output.workflow_id}: {'ok' if output.ok else 'failed'}")
        return True
    if line.startswith("/run"):
        rest = line.removeprefix("/run").strip()
        if not rest:
            print("Usage: /run <tool> <json>")
            return True
        try:
            name, args_text = rest.split(maxsplit=1)
            args: dict[str, Any] = json.loads(args_text)
        except ValueError:
            parts = shlex.split(rest)
            name = parts[0]
            args = {}
        except json.JSONDecodeError as exc:
            print(f"JSON error: {exc}")
            return True
        result = agent._call_tool(name, args)
        print(result.output)
        return True
    print("Unknown command. Use /help.")
    return True


def chat(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=args.yes)
    print("Evolva CLI. Type /help for commands, /exit to quit.")
    if not agent.llm.available:
        print("[提示] 未检测到 OPENAI_API_KEY，将使用有限规则模式。")
    while True:
        try:
            line = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(agent, line):
                return 0
            continue
        result = agent.chat(line)
        if args.show_tools and result.tool_logs:
            print_block("tool logs", "\n\n".join(result.tool_logs))
        print(f"\nAgent> {result.answer}")
    return 0


def once(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=args.yes)
    result = agent.chat(args.message)
    if args.show_tools and result.tool_logs:
        print_block("tool logs", "\n\n".join(result.tool_logs))
    print(result.answer)
    return 0


def tui(args: argparse.Namespace) -> int:
    return run_tui(assume_yes=args.yes, show_tools=not args.no_tools)


def trace_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=True)
    if args.trace_cmd == "list":
        rows = agent.tracer.list_runs(limit=args.limit)
        print("\n".join(f"{r['run_id']}\t{r['status']}\t{r['duration_ms']}ms\t{r['user_input']}" for r in rows) or "No traces")
        return 0
    if args.trace_cmd == "show":
        print(agent.tracer.render(args.run_id))
        return 0
    if args.trace_cmd == "replay":
        prompt = agent.tracer.replay_prompt(args.run_id)
        result = agent.chat(prompt)
        print(result.answer)
        return 0
    raise SystemExit("unknown trace command")


def eval_cmd(args: argparse.Namespace) -> int:
    harness = EvalHarness(AgentConfig(), assume_yes=args.yes)
    results = harness.run_file(args.tasks)
    print(render_results(results))
    return 0 if all(r.passed for r in results) else 1


def workflow_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=args.yes)
    result = WorkflowEngine(agent).run_file(args.spec)
    print("\n\n".join(result.logs))
    print(f"Workflow {result.workflow_id}: {'ok' if result.ok else 'failed'}")
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evolva")
    sub = parser.add_subparsers(dest="cmd", required=False)
    chat_p = sub.add_parser("chat", help="Start interactive chat")
    chat_p.add_argument("--yes", action="store_true", help="Approve shell/python tools without prompting")
    chat_p.add_argument("--show-tools", action="store_true", help="Print tool call logs")
    chat_p.set_defaults(func=chat)

    once_p = sub.add_parser("ask", help="Ask one question and exit")
    once_p.add_argument("message")
    once_p.add_argument("--yes", action="store_true")
    once_p.add_argument("--show-tools", action="store_true")
    once_p.set_defaults(func=once)

    tui_p = sub.add_parser("tui", help="Start terminal UI chat")
    tui_p.add_argument("--yes", action="store_true", help="Approve shell/python tools without prompting")
    tui_p.add_argument("--no-tools", action="store_true", help="Hide tool log panel at startup")
    tui_p.set_defaults(func=tui)

    trace_p = sub.add_parser("trace", help="Inspect or replay execution traces")
    trace_sub = trace_p.add_subparsers(dest="trace_cmd", required=True)
    trace_list = trace_sub.add_parser("list", help="List recent traces")
    trace_list.add_argument("--limit", type=int, default=20)
    trace_list.set_defaults(func=trace_cmd)
    trace_show = trace_sub.add_parser("show", help="Show one trace")
    trace_show.add_argument("run_id")
    trace_show.set_defaults(func=trace_cmd)
    trace_replay = trace_sub.add_parser("replay", help="Replay a trace user prompt")
    trace_replay.add_argument("run_id")
    trace_replay.set_defaults(func=trace_cmd)

    eval_p = sub.add_parser("eval", help="Run jsonl eval tasks")
    eval_p.add_argument("tasks", type=lambda s: __import__("pathlib").Path(s))
    eval_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during eval")
    eval_p.set_defaults(func=eval_cmd)

    workflow_p = sub.add_parser("workflow", help="Run a JSON workflow spec")
    workflow_p.add_argument("spec", type=lambda s: __import__("pathlib").Path(s))
    workflow_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during workflow")
    workflow_p.set_defaults(func=workflow_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["chat"] + (argv or []))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
