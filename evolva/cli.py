from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

from evolva.agent.core import EvolvaAgent
from evolva.agent.dream import DreamEngine
from evolva.agent.evolution_analyzer import EvalEvolutionAnalyzer, TraceEvolutionAnalyzer, apply_proposals, render_analysis, render_reports
from evolva.config import AgentConfig
from evolva.eval.harness import EvalHarness, render_results
from evolva.maintenance.optimizer import run_daily_optimization
from evolva.tui import run_tui
from evolva.workflow.engine import WorkflowEngine


HELP = """
Commands:
  /help                Show this help
  /tools               List tools
  /skills              List skills
  /memory [query]      Show/search memory
  /memory stats        Show memory counts by kind
  /memory recent [n]   Show recent memories
  /context [query]     Show/search persistent context
  /todo                Show todo list
  /todo add <title>    Add a todo
  /todo done <id>      Mark a todo done
  /agents              List role agents
  /trace list          List recent traces
  /trace show <run>    Show a trace
  /trace context <run> Show trace context/prompt events
  /model [name]        Show or switch model for subsequent turns
  /policy              Show guardrail policy
  /repo build          Build local repository index
  /repo search <query> Search symbols, references, and code chunks
  /mcp                 List MCP servers
  /mcp add <name> <cmd...>
                       Add a stdio MCP server to the local workspace
  /mcp remove <name>   Remove a local MCP server config
  /mcp tools [server]  List MCP tools
  /image <path|url> [text]
                       Ask with one image
  /evolve [feedback]   Turn feedback into memory + skill
  /evolve status       Show evolution status
  /evolve audit        Audit lessons, skills, traces, and eval proposals
  /evolve trace        Analyze traces for evolution proposals
  /evolve apply-trace  Analyze traces and apply proposals
  /evolve eval [json]  Analyze eval failures for proposals
  /evolve apply-eval [json]
                       Analyze eval failures and apply proposals
  /dream               Run offline trace/eval/memory reflection
  /dream apply         Apply high-confidence dream proposals
  /dream --min-confidence 0.8
                       Raise the Dreaming drift-guard threshold
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
        if query in {"stats", "stat", "status"}:
            print(agent.memory.render_stats())
        elif query.startswith("recent"):
            parts = query.split()
            limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            print(agent.memory.render_items(limit=limit))
        elif query.startswith("search "):
            print(agent.memory.render_items(query=query.removeprefix("search ").strip(), limit=10))
        else:
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
        elif rest.startswith("context "):
            print(agent.tracer.render_context(rest.removeprefix("context ").strip()))
        else:
            print("Usage: /trace list | /trace show <run_id> | /trace context <run_id>")
        return True
    if line.startswith("/model"):
        name = line.removeprefix("/model").strip()
        if not name:
            print(f"Current model: {agent.config.model}")
        else:
            print(f"Switched model: {agent.set_model(name)}")
        return True
    if line == "/policy":
        print(agent.policy.as_tool_result().output)
        return True
    if line.startswith("/repo"):
        rest = line.removeprefix("/repo").strip()
        if rest in {"", "build"}:
            result = agent._call_tool("repo_index_build", {})
        elif rest.startswith("search "):
            result = agent._call_tool("repo_index_search", {"query": rest.removeprefix("search ").strip()})
        else:
            print("Usage: /repo build | /repo search <query>")
            return True
        print(result.output)
        return True
    if line.startswith("/mcp"):
        rest = line.removeprefix("/mcp").strip()
        if not rest:
            print(agent._call_tool("mcp_servers", {}).output)
        elif rest.startswith("add "):
            parts = shlex.split(rest.removeprefix("add ").strip())
            if len(parts) < 2:
                print("Usage: /mcp add <name> <command> [args...]")
            else:
                print(agent._call_tool("mcp_add_server", {"name": parts[0], "command": parts[1], "args": parts[2:]}).output)
        elif rest.startswith("remove "):
            name = rest.removeprefix("remove ").strip()
            print(agent._call_tool("mcp_remove_server", {"name": name}).output)
        elif rest.startswith("tools"):
            server = rest.removeprefix("tools").strip()
            print(agent._call_tool("mcp_tools", {"server": server}).output)
        else:
            print("Usage: /mcp | /mcp add <name> <command> [args...] | /mcp remove <name> | /mcp tools [server] | /run mcp_call {...}")
        return True
    if line.startswith("/image"):
        rest = line.removeprefix("/image").strip()
        if not rest:
            print("Usage: /image <path-or-url> [question]")
            return True
        parts = shlex.split(rest)
        image = parts[0]
        question = " ".join(parts[1:]) or "请分析这张图片。"
        result = agent.chat(question, image_sources=[image])
        print(result.answer)
        return True
    if line.startswith("/evolve"):
        feedback = line.removeprefix("/evolve").strip()
        if feedback in {"status", "stats"}:
            print(agent.evolution.render_status())
            return True
        if feedback in {"audit", "health"}:
            trace_analysis = TraceEvolutionAnalyzer(agent.tracer).analyze()
            eval_analysis = EvalEvolutionAnalyzer(agent.config.eval_results_dir).analyze_file()
            print(agent.evolution.render_audit(trace_analysis=trace_analysis, eval_analysis=eval_analysis))
            return True
        if feedback in {"trace", "analyze", "analyze-traces"}:
            print(render_analysis(TraceEvolutionAnalyzer(agent.tracer).analyze()))
            return True
        if feedback in {"apply-trace", "apply-traces"}:
            analysis = TraceEvolutionAnalyzer(agent.tracer).analyze()
            print(render_analysis(analysis))
            print(render_reports(apply_proposals(agent.evolution, analysis.proposals)))
            return True
        if feedback.startswith("eval") or feedback.startswith("from-eval"):
            parts = shlex.split(feedback)
            apply = parts[0] in {"from-eval", "apply-eval"}
            path = agent.sandbox.resolve(parts[1]) if len(parts) > 1 else None
            analysis = EvalEvolutionAnalyzer(agent.config.eval_results_dir).analyze_file(path)
            print(render_analysis(analysis))
            if apply:
                print(render_reports(apply_proposals(agent.evolution, analysis.proposals)))
            return True
        report = agent.evolution.evolve(feedback, task="manual CLI feedback")
        actions = "\n".join(f"- {action}" for action in report.actions)
        print(
            f"已进化：{report.summary()}\n"
            f"置信度：{report.confidence:.2f}，记忆写入：{report.memory_written}\n"
            f"动作：\n{actions}\n"
            f"技能：{report.skill_name} ({report.skill_path})"
        )
        return True
    if line.startswith("/dream"):
        rest = line.removeprefix("/dream").strip()
        parts = shlex.split(rest) if rest else []
        apply = bool(parts and parts[0] in {"apply", "--apply"})
        limit = 20
        report_path = None
        min_confidence = None
        for idx, part in enumerate(parts):
            if part in {"--limit", "-n"} and idx + 1 < len(parts):
                limit = int(parts[idx + 1])
            elif part in {"--report", "-r"} and idx + 1 < len(parts):
                report_path = agent.sandbox.resolve(parts[idx + 1])
            elif part in {"--min-confidence", "--threshold"} and idx + 1 < len(parts):
                min_confidence = float(parts[idx + 1])
        engine = DreamEngine(agent)
        report = engine.run(trace_limit=limit, eval_report=report_path, apply=apply, min_confidence=min_confidence)
        print(engine.render(report))
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
    result = agent.chat(args.message, image_sources=args.image or None)
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
    if args.trace_cmd == "context":
        print(agent.tracer.render_context(args.run_id))
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


def mcp_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=args.yes)
    if args.mcp_cmd == "servers":
        print(agent._call_tool("mcp_servers", {}).output)
        return 0
    if args.mcp_cmd == "add":
        result = agent._call_tool("mcp_add_server", {"name": args.name, "command": args.command, "args": args.args})
        print(result.output)
        return 0 if result.ok else 1
    if args.mcp_cmd == "remove":
        result = agent._call_tool("mcp_remove_server", {"name": args.name})
        print(result.output)
        return 0 if result.ok else 1
    if args.mcp_cmd == "tools":
        print(agent._call_tool("mcp_tools", {"server": args.server or ""}).output)
        return 0
    if args.mcp_cmd == "call":
        try:
            arguments: dict[str, Any] = json.loads(args.arguments or "{}")
        except json.JSONDecodeError as exc:
            print(f"JSON error: {exc}")
            return 2
        result = agent._call_tool("mcp_call", {"server": args.server, "tool": args.tool, "arguments": arguments})
        print(result.output)
        return 0 if result.ok else 1
    raise SystemExit("unknown mcp command")


def evolve_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=True)
    if args.evolve_cmd == "status":
        print(agent.evolution.render_status())
        return 0
    if args.evolve_cmd == "audit":
        trace_analysis = TraceEvolutionAnalyzer(agent.tracer).analyze(limit=args.limit)
        eval_analysis = EvalEvolutionAnalyzer(agent.config.eval_results_dir).analyze_file(args.report)
        print(agent.evolution.render_audit(trace_analysis=trace_analysis, eval_analysis=eval_analysis))
        if args.show_proposals:
            print(render_analysis(trace_analysis))
            print(render_analysis(eval_analysis))
        return 0
    if args.evolve_cmd == "trace":
        analysis = TraceEvolutionAnalyzer(agent.tracer).analyze(limit=args.limit)
        print(render_analysis(analysis))
        if args.apply:
            print(render_reports(apply_proposals(agent.evolution, analysis.proposals)))
        return 0
    if args.evolve_cmd == "eval":
        analysis = EvalEvolutionAnalyzer(agent.config.eval_results_dir).analyze_file(args.report)
        print(render_analysis(analysis))
        if args.apply:
            print(render_reports(apply_proposals(agent.evolution, analysis.proposals)))
        return 0
    if args.evolve_cmd == "feedback":
        report = agent.evolution.evolve(args.feedback, task="manual CLI feedback")
        print(render_reports([report]))
        return 0
    raise SystemExit("unknown evolve command")


def optimize_cmd(args: argparse.Namespace) -> int:
    report, path, rendered = run_daily_optimization(AgentConfig().root, apply=args.apply, write=True)
    print(rendered)
    if path:
        print(f"Report: {path}")
    if args.fail_on_items and any(item.severity in {"high", "medium"} and not item.fixed for item in report.items):
        return 1
    return 0


def dream_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=True)
    report_path = args.report
    engine = DreamEngine(agent)
    report = engine.run(trace_limit=args.limit, eval_report=report_path, apply=args.apply, min_confidence=args.min_confidence)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(engine.render(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evolva",
        description="Open Evolva's TUI workbench by default. Subcommands are reserved for automation and CI.",
    )
    parser.add_argument("--chat", action="store_true", help="Start plain line-based chat instead of the default TUI")
    parser.add_argument("--yes", action="store_true", help="Approve shell/python tools without prompting in default TUI mode")
    parser.add_argument("--no-tools", action="store_true", help="Hide the TUI tool log panel at startup")
    sub = parser.add_subparsers(dest="cmd", required=False, metavar="{ask,trace,eval,evolve,optimize,dream,workflow,mcp}")
    once_p = sub.add_parser("ask", help="Automation: ask one question and exit")
    once_p.add_argument("message")
    once_p.add_argument("--image", action="append", help="Attach an image path or URL; can be repeated")
    once_p.add_argument("--yes", action="store_true")
    once_p.add_argument("--show-tools", action="store_true")
    once_p.set_defaults(func=once)

    trace_p = sub.add_parser("trace", help="Automation: inspect or replay execution traces")
    trace_sub = trace_p.add_subparsers(dest="trace_cmd", required=True)
    trace_list = trace_sub.add_parser("list", help="List recent traces")
    trace_list.add_argument("--limit", type=int, default=20)
    trace_list.set_defaults(func=trace_cmd)
    trace_show = trace_sub.add_parser("show", help="Show one trace")
    trace_show.add_argument("run_id")
    trace_show.set_defaults(func=trace_cmd)
    trace_context = trace_sub.add_parser("context", help="Show prompt/context events for one trace")
    trace_context.add_argument("run_id")
    trace_context.set_defaults(func=trace_cmd)
    trace_replay = trace_sub.add_parser("replay", help="Replay a trace user prompt")
    trace_replay.add_argument("run_id")
    trace_replay.set_defaults(func=trace_cmd)

    eval_p = sub.add_parser("eval", help="Automation: run jsonl eval tasks")
    eval_p.add_argument("tasks", type=lambda s: __import__("pathlib").Path(s))
    eval_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during eval")
    eval_p.set_defaults(func=eval_cmd)

    evolve_p = sub.add_parser("evolve", help="Automation: inspect or apply self-evolution proposals")
    evolve_sub = evolve_p.add_subparsers(dest="evolve_cmd", required=True)
    evolve_status = evolve_sub.add_parser("status", help="Show evolution status")
    evolve_status.set_defaults(func=evolve_cmd)
    evolve_audit = evolve_sub.add_parser("audit", help="Audit self-evolution coverage and pending proposals")
    evolve_audit.add_argument("--limit", type=int, default=20, help="Trace run limit for proposal analysis")
    evolve_audit.add_argument("--report", nargs="?", type=lambda s: __import__("pathlib").Path(s), help="Eval report JSON; defaults to latest")
    evolve_audit.add_argument("--show-proposals", action="store_true", help="Print trace/eval proposal details")
    evolve_audit.set_defaults(func=evolve_cmd)
    evolve_trace = evolve_sub.add_parser("trace", help="Analyze traces for evolution proposals")
    evolve_trace.add_argument("--limit", type=int, default=20)
    evolve_trace.add_argument("--apply", action="store_true", help="Apply generated proposals as lessons/skills")
    evolve_trace.set_defaults(func=evolve_cmd)
    evolve_eval = evolve_sub.add_parser("eval", help="Analyze eval report failures for evolution proposals")
    evolve_eval.add_argument("report", nargs="?", type=lambda s: __import__("pathlib").Path(s), help="Eval report JSON; defaults to latest")
    evolve_eval.add_argument("--apply", action="store_true", help="Apply generated proposals as lessons/skills")
    evolve_eval.set_defaults(func=evolve_cmd)
    evolve_feedback = evolve_sub.add_parser("feedback", help="Turn direct feedback into a lesson/skill")
    evolve_feedback.add_argument("feedback")
    evolve_feedback.set_defaults(func=evolve_cmd)

    optimize_p = sub.add_parser("optimize", help="Automation: scan project health and list safe optimization opportunities")
    optimize_p.add_argument("--apply", action="store_true", help="Apply conservative auto-fixes such as stale badge updates and local cache cleanup")
    optimize_p.add_argument("--fail-on-items", action="store_true", help="Exit non-zero when medium/high unfixed items remain")
    optimize_p.set_defaults(func=optimize_cmd)

    dream_p = sub.add_parser("dream", help="Automation: run Evolva's local trace/eval/memory reflection loop")
    dream_p.add_argument("--apply", action="store_true", help="Apply high-confidence proposals as Memory/Skill lessons")
    dream_p.add_argument("--limit", type=int, default=20, help="Recent trace run limit")
    dream_p.add_argument("--report", type=lambda s: __import__("pathlib").Path(s), help="Eval report JSON; defaults to latest")
    dream_p.add_argument("--min-confidence", type=float, default=None, help="Minimum confidence for automatic Dreaming promotion")
    dream_p.add_argument("--json", action="store_true", help="Print the full Dream report JSON")
    dream_p.set_defaults(func=dream_cmd)

    workflow_p = sub.add_parser("workflow", help="Automation: run a JSON workflow spec")
    workflow_p.add_argument("spec", type=lambda s: __import__("pathlib").Path(s))
    workflow_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during workflow")
    workflow_p.set_defaults(func=workflow_cmd)

    mcp_p = sub.add_parser("mcp", help="Automate MCP stdio servers; in daily use prefer TUI /mcp")
    mcp_sub = mcp_p.add_subparsers(dest="mcp_cmd", required=True)
    mcp_servers_p = mcp_sub.add_parser("servers", help="List configured MCP servers")
    mcp_servers_p.add_argument("--yes", action="store_true")
    mcp_servers_p.set_defaults(func=mcp_cmd)
    mcp_add_p = mcp_sub.add_parser("add", help="Persist a stdio MCP server config")
    mcp_add_p.add_argument("name")
    mcp_add_p.add_argument("command")
    mcp_add_p.add_argument("args", nargs=argparse.REMAINDER)
    mcp_add_p.add_argument("--yes", action="store_true")
    mcp_add_p.set_defaults(func=mcp_cmd)
    mcp_remove_p = mcp_sub.add_parser("remove", help="Remove a configured MCP server")
    mcp_remove_p.add_argument("name")
    mcp_remove_p.add_argument("--yes", action="store_true")
    mcp_remove_p.set_defaults(func=mcp_cmd)
    mcp_tools_p = mcp_sub.add_parser("tools", help="List MCP tools")
    mcp_tools_p.add_argument("server", nargs="?")
    mcp_tools_p.add_argument("--yes", action="store_true")
    mcp_tools_p.set_defaults(func=mcp_cmd)
    mcp_call_p = mcp_sub.add_parser("call", help="Call an MCP tool")
    mcp_call_p.add_argument("server")
    mcp_call_p.add_argument("tool")
    mcp_call_p.add_argument("arguments", nargs="?", default="{}", help="JSON arguments")
    mcp_call_p.add_argument("--yes", action="store_true", help="Approve MCP tool call without prompting")
    mcp_call_p.set_defaults(func=mcp_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "chat", False) and not getattr(args, "cmd", None):
        return chat(argparse.Namespace(yes=args.yes, show_tools=False))
    if not hasattr(args, "func"):
        return tui(argparse.Namespace(yes=args.yes, no_tools=args.no_tools))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
