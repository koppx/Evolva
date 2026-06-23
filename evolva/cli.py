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
from evolva.eval.benchmark import benchmark_smoke_report, render_benchmark_smoke_report, run_benchmark_sample, write_benchmark_report
from evolva.tools import benchmark as benchmark_tools
from evolva.agent.mcp_presets import parse_env_pairs
from evolva.eval.harness import EvalHarness, render_gate, render_results
from evolva.loops import LoopDraftSession, LoopRunner, render_confirmed_draft, render_loop_draft, render_loop_result, render_loop_specs, render_loop_validation, validate_loop_spec
from evolva.loops.planner import is_natural_language_loop
from evolva.maintenance.optimizer import run_daily_optimization
from evolva.tui import run_fullscreen_tui, run_tui
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
  /metrics             Show recent runtime metrics
  /metrics alerts      Show recent alert events
  /metrics prometheus  Export metrics in Prometheus text format
  /model [name]        Show or switch model for subsequent turns
  /sandbox             Show sandbox backend info
  /sandbox smoke       Run fixed sandbox backend smoke check
  /policy              Show guardrail policy
  /repo build          Build local repository index
  /repo status         Show repository index freshness and skipped files
  /repo search <query> Search symbols, references, and code chunks
  /mcp                 List MCP servers
  /mcp add <name> <cmd...>
                       Add a stdio MCP server to the local workspace
  /mcp remove <name>   Remove a local MCP server config
  /mcp tools [server]  List MCP tools
  /mcp health [server] Check MCP health and schema cache status
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
  /dream backlog       Show staged Dream improvement candidates
  /dream status        Show Dream gate and promotion status
  /dream verify        Run candidate verifiers against local eval/trace evidence
  /dream verify --promote
                       Promote verified Dream candidates
  /dream apply         Stage high-confidence dream proposals
  /dream --min-confidence 0.8
                       Raise the Dreaming drift-guard threshold
  /loop list           List repeatable agent loops
  /loop show <loop>    Show a loop spec
  /loop validate <loop>
                       Validate a loop spec before running it
  /loop dry-run <loop> Validate loop spec, tool availability, and policy
  /loop run <loop>     Run a loop and record trace evidence
  /loop <request>      Plan a new Loop from natural language; does not execute
  /loop revise <text>  Revise the active draft
  /loop approve <text> Resolve open questions with a confirmation note
  /loop confirm        Validate/dry-run active draft
  /loop execute        Execute only after confirm succeeds
  /loop save <name>    Save active draft as reusable Loop
  /loop cancel         Clear active draft
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
    if line.startswith("/metrics"):
        rest = line.removeprefix("/metrics").strip()
        if rest in {"", "list"}:
            print(agent.observability.render_metrics())
        elif rest in {"alerts", "alert"}:
            print(agent.observability.render_alerts())
        elif rest in {"prometheus", "export"}:
            print(agent.observability.render_prometheus(), end="")
        else:
            print("Usage: /metrics | /metrics alerts | /metrics prometheus")
        return True
    if line.startswith("/sandbox"):
        rest = line.removeprefix("/sandbox").strip()
        if rest in {"", "info"}:
            print(agent.sandbox.describe())
        elif rest == "smoke":
            result = agent.sandbox.smoke_check()
            print(result.output)
        else:
            print("Usage: /sandbox | /sandbox smoke")
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
        elif rest == "status":
            result = agent._call_tool("repo_index_status", {})
        elif rest.startswith("search "):
            result = agent._call_tool("repo_index_search", {"query": rest.removeprefix("search ").strip()})
        else:
            print("Usage: /repo build | /repo status | /repo search <query>")
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
        elif rest.startswith("health"):
            server = rest.removeprefix("health").strip()
            print(agent._call_tool("mcp_health", {"server": server}).output)
        else:
            print("Usage: /mcp | /mcp add <name> <command> [args...] | /mcp remove <name> | /mcp tools [server] | /mcp health [server] | /run mcp_call {...}")
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
        engine = DreamEngine(agent)
        if parts and parts[0] in {"status", "health"}:
            print(engine.render_status())
            return True
        if parts and parts[0] in {"backlog", "candidates"}:
            print(engine.render_backlog())
            return True
        if parts and parts[0] == "verify":
            limit = 20
            tasks_path = None
            promote = "--promote" in parts
            for idx, part in enumerate(parts):
                if part in {"--limit", "-n"} and idx + 1 < len(parts):
                    limit = int(parts[idx + 1])
                elif part in {"--tasks", "--eval"} and idx + 1 < len(parts):
                    tasks_path = agent.sandbox.resolve(parts[idx + 1])
            print(engine.render_verification(engine.verify_backlog(tasks_path=tasks_path, limit=limit, promote=promote)))
            return True
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
        report = engine.run(trace_limit=limit, eval_report=report_path, apply=apply, min_confidence=min_confidence)
        print(engine.render(report))
        return True
    if line.startswith("/loop"):
        rest = line.removeprefix("/loop").strip()
        runner = LoopRunner(agent)
        session = LoopDraftSession.for_agent(agent)
        if rest in {"", "list"}:
            print(render_loop_specs(runner.list_specs()))
            return True
        if rest == "help":
            print("Usage: /loop <request> | /loop plan <request> | /loop revise <feedback> | /loop approve <confirmation> | /loop show-draft | /loop confirm | /loop execute | /loop save <name> | /loop cancel | /loop list/show/validate/dry-run/run")
            return True
        if is_natural_language_loop(rest) or rest.startswith("plan "):
            request = rest.removeprefix("plan ").strip() if rest.startswith("plan ") else rest
            print(render_loop_draft(session.plan(request, agent=agent)))
            return True
        if rest == "show-draft":
            print(render_loop_draft(session.require_draft(), show_spec=True))
            return True
        if rest.startswith("revise "):
            print(render_loop_draft(session.revise(rest.removeprefix("revise ").strip())))
            return True
        if rest.startswith("approve") or rest.startswith("accept"):
            parts = rest.split(maxsplit=1)
            confirmation = parts[1].strip() if len(parts) > 1 else "用户确认按当前默认方案继续执行。"
            print(render_loop_draft(session.accept_review(confirmation)))
            return True
        if rest == "confirm":
            print(render_confirmed_draft(session.confirm(agent=agent)))
            return True
        if rest == "execute":
            draft = session.require_draft()
            if draft.status != "ready_to_run":
                print("Active Loop draft is not ready. Run `/loop confirm` first and resolve validation/open-question issues.")
                return True
            session.mark_running()
            result = runner.run(draft.loop_spec)
            if result.ok:
                session.mark_completed()
            else:
                session.restore_ready()
            print(render_loop_result(result))
            return True
        if rest.startswith("save"):
            path = session.save_loop(rest.removeprefix("save").strip())
            print(f"Saved Loop spec: {path}")
            return True
        if rest == "cancel":
            session.clear()
            print("Cancelled active Loop draft.")
            return True
        if rest.startswith("show "):
            spec = runner.load(rest.removeprefix("show ").strip())
            print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
            return True
        if rest.startswith("validate "):
            spec = runner.load(rest.removeprefix("validate ").strip())
            print(render_loop_validation(spec, agent=agent, strict_policy=True))
            return True
        if rest.startswith("dry-run "):
            spec = runner.load(rest.removeprefix("dry-run ").strip())
            validation = validate_loop_spec(spec, agent=agent, strict_policy=True)
            lines = [f"Loop dry-run: {spec.id}", f"- Status: {'ok' if validation.ok else 'failed'}"]
            lines.extend(f"- Warning: {warning}" for warning in validation.warnings)
            lines.extend(f"- Error: {error}" for error in validation.errors)
            if validation.ok:
                lines.append("- Execution: not run")
            print("\n".join(lines))
            return True
        if rest.startswith("run "):
            print(render_loop_result(runner.run(rest.removeprefix("run ").strip())))
            return True
        print("Usage: /loop <request> | /loop plan <request> | /loop revise <feedback> | /loop approve <confirmation> | /loop show-draft | /loop confirm | /loop execute | /loop save <name> | /loop cancel | /loop list/show/validate/dry-run/run")
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
    runner = run_fullscreen_tui if getattr(args, "fullscreen", False) else run_tui
    return runner(assume_yes=args.yes, show_tools=not args.no_tools)


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


def metrics_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=True)
    if args.metrics_cmd == "list":
        print(agent.observability.render_metrics(limit=args.limit))
        return 0
    if args.metrics_cmd == "alerts":
        print(agent.observability.render_alerts(limit=args.limit))
        return 0
    if args.metrics_cmd == "prometheus":
        print(agent.observability.render_prometheus(), end="")
        return 0
    raise SystemExit("unknown metrics command")


def sandbox_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=True)
    if args.sandbox_cmd == "info":
        print(agent.sandbox.describe())
        return 0
    if args.sandbox_cmd == "smoke":
        result = agent.sandbox.smoke_check(timeout=args.timeout)
        print(result.output)
        return 0 if result.ok else 1
    raise SystemExit("unknown sandbox command")


def eval_cmd(args: argparse.Namespace) -> int:
    harness = EvalHarness(AgentConfig(), assume_yes=args.yes)
    results = harness.run_file(args.tasks)
    print(render_results(results))
    gate = harness.gate(
        results,
        baseline_path=args.baseline,
        min_score=args.min_score,
        no_regression=args.no_regression,
        name=args.tasks.stem,
    )
    if args.baseline or args.min_score is not None or args.no_regression:
        print(render_gate(gate))
    return 0 if gate.ok else 1


def benchmark_cmd(args: argparse.Namespace) -> int:
    config = AgentConfig()
    if args.benchmark_cmd == "health":
        result = benchmark_tools.benchmark_tool_health(config.mcp_config_file)
        if args.json:
            print(json.dumps(result.data, ensure_ascii=False, indent=2))
        else:
            print(result.output)
        return 0 if result.ok else 1
    if args.benchmark_cmd == "inspect-file":
        path = args.path
        result = benchmark_tools.file_to_text(path, max_chars=args.max_chars, max_rows=args.max_rows)
        extra: dict[str, Any] = {"preview": result.data}
        if args.deep:
            suffix = path.suffix.lower()
            if suffix in benchmark_tools.IMAGE_EXTENSIONS:
                ocr = benchmark_tools.ocr_image(path, language=args.language, max_chars=args.max_chars, timeout=args.timeout)
                extra["ocr"] = ocr.data
            elif suffix in benchmark_tools.AUDIO_EXTENSIONS:
                transcript = benchmark_tools.audio_transcribe(path, model=args.model, language=args.language if args.language != "eng" else "", max_chars=args.max_chars, timeout=args.timeout)
                extra["transcript"] = transcript.data
            elif suffix in benchmark_tools.VIDEO_EXTENSIONS:
                probe = benchmark_tools.video_probe(path, timeout=min(args.timeout, 120))
                extra["probe"] = probe.data
                if args.frames_dir:
                    frames = benchmark_tools.video_extract_frames(path, args.frames_dir, every_seconds=args.every_seconds, max_frames=args.max_frames, timeout=args.timeout)
                    extra["frames"] = frames.data
            elif suffix == ".pdf":
                pdf = benchmark_tools.pdf_extract_external(path, max_chars=args.max_chars, timeout=args.timeout)
                extra["pdf"] = pdf.data
        if args.json:
            print(json.dumps(extra, ensure_ascii=False, indent=2))
        else:
            print(result.output)
            for key in ["ocr", "transcript", "probe", "frames", "pdf"]:
                if key in extra and isinstance(extra[key], dict):
                    text = extra[key].get("text") or extra[key].get("summary") or extra[key].get("error") or ""
                    if text:
                        print(f"\n--- {key} ---\n{text}")
        return 0 if result.ok else 1
    if args.benchmark_cmd == "smoke":
        report = benchmark_smoke_report(args.metadata, args.attachments, limit=args.limit, max_chars=args.max_chars)
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_smoke_report(report))
        if args.output:
            path = write_benchmark_report(report, args.output)
            print(f"Report: {path}")
        return 1 if args.strict and (report.missing_attachments or report.preview_failed) else 0
    if args.benchmark_cmd == "run":
        rows = run_benchmark_sample(
            config,
            args.metadata,
            args.attachments,
            limit=args.limit,
            level=args.level,
            run_agent=args.run_agent,
            include_answers=args.include_answers,
            max_attachment_chars=args.max_attachment_chars,
            assume_yes=args.yes,
        )
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for item in rows:
                print(f"\n--- benchmark {item.get('task_id')} level={item.get('level')} ---")
                if args.run_agent:
                    print(item.get("answer", ""))
                    if item.get("exact_match") is not None:
                        print(f"exact_match={item.get('exact_match')}")
                else:
                    print(item.get("prompt", ""))
        return 0
    raise SystemExit("unknown benchmark command")


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
    if args.mcp_cmd == "presets":
        print(agent._call_tool("mcp_presets", {}).output)
        return 0
    if args.mcp_cmd == "add-preset":
        try:
            env = parse_env_pairs(args.env)
        except ValueError as exc:
            print(str(exc))
            return 2
        result = agent._call_tool("mcp_add_preset", {"preset": args.preset, "name": args.name or "", "env": env})
        print(result.output)
        return 0 if result.ok else 1
    if args.mcp_cmd == "add":
        try:
            raw_args = list(args.args or [])
            raw_env = list(getattr(args, "env", []) or [])
            cleaned_args: list[str] = []
            i = 0
            while i < len(raw_args):
                if raw_args[i] == "--env" and i + 1 < len(raw_args):
                    raw_env.append(raw_args[i + 1])
                    i += 2
                    continue
                cleaned_args.append(raw_args[i])
                i += 1
            env = parse_env_pairs(raw_env)
        except ValueError as exc:
            print(str(exc))
            return 2
        result = agent._call_tool("mcp_add_server", {"name": args.name, "command": args.command, "args": cleaned_args, "env": env})
        print(result.output)
        return 0 if result.ok else 1
    if args.mcp_cmd == "remove":
        result = agent._call_tool("mcp_remove_server", {"name": args.name})
        print(result.output)
        return 0 if result.ok else 1
    if args.mcp_cmd == "tools":
        print(agent._call_tool("mcp_tools", {"server": args.server or ""}).output)
        return 0
    if args.mcp_cmd == "health":
        print(agent._call_tool("mcp_health", {"server": args.server or "", "refresh": bool(args.refresh)}).output)
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
    engine = DreamEngine(agent)
    if getattr(args, "dream_cmd", None) == "backlog":
        print(engine.render_backlog(limit=args.limit))
        return 0
    if getattr(args, "dream_cmd", None) == "verify":
        results = engine.verify_backlog(tasks_path=args.tasks, limit=args.limit, promote=args.promote)
        if args.json:
            print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
        else:
            print(engine.render_verification(results))
        return 0 if all(item.ok for item in results) else 1
    report_path = args.report
    report = engine.run(trace_limit=args.limit, eval_report=report_path, apply=args.apply, min_confidence=args.min_confidence)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(engine.render(report))
    return 0


def loop_cmd(args: argparse.Namespace) -> int:
    agent = EvolvaAgent(AgentConfig(), assume_yes=args.yes)
    runner = LoopRunner(agent)
    session = LoopDraftSession.for_agent(agent)
    if args.loop_cmd == "list":
        print(render_loop_specs(runner.list_specs()))
        return 0
    if args.loop_cmd == "plan":
        draft = session.plan(_loop_text(args, "request"), agent=agent)
        print(render_loop_draft(draft, show_spec=args.show_spec))
        return 0
    if args.loop_cmd == "show-draft":
        print(render_loop_draft(session.require_draft(), show_spec=args.show_spec))
        return 0
    if args.loop_cmd == "revise":
        draft = session.revise(_loop_text(args, "feedback"))
        print(render_loop_draft(draft, show_spec=args.show_spec))
        return 0
    if args.loop_cmd in {"approve", "accept"}:
        draft = session.accept_review(_loop_text(args, "confirmation") or "用户确认按当前默认方案继续执行。")
        print(render_loop_draft(draft, show_spec=args.show_spec))
        return 0
    if args.loop_cmd == "confirm":
        draft = session.confirm(agent=agent)
        print(render_confirmed_draft(draft))
        return 0 if draft.status == "ready_to_run" else 1
    if args.loop_cmd == "execute":
        draft = session.require_draft()
        if draft.status != "ready_to_run":
            print("Active Loop draft is not ready. Run `evolva loop confirm` first and resolve validation/open-question issues.")
            return 1
        session.mark_running()
        result = runner.run(draft.loop_spec)
        if result.ok:
            session.mark_completed()
        else:
            session.restore_ready()
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_loop_result(result))
        return 0 if result.ok else 1
    if args.loop_cmd == "save":
        path = session.save_loop(args.name or "")
        print(f"Saved Loop spec: {path}")
        return 0
    if args.loop_cmd == "cancel":
        session.clear()
        print("Cancelled active Loop draft.")
        return 0
    if args.loop_cmd == "show":
        spec = runner.load(args.loop_id)
        print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.loop_cmd == "validate":
        try:
            spec = runner.load(args.loop_id)
            print(render_loop_validation(spec, agent=agent, strict_policy=True))
            return 0
        except Exception as exc:
            print(f"Loop validation: {args.loop_id}\n- Status: failed\n- Error: {exc}")
            return 1
    if args.loop_cmd == "dry-run":
        spec = runner.load(args.loop_id)
        validation = validate_loop_spec(spec, agent=agent, strict_policy=True)
        print(f"Loop dry-run: {spec.id}")
        print(f"- Status: {'ok' if validation.ok else 'failed'}")
        for warning in validation.warnings:
            print(f"- Warning: {warning}")
        for error in validation.errors:
            print(f"- Error: {error}")
        if validation.ok:
            print("- Execution: not run")
        return 0 if validation.ok else 1
    if args.loop_cmd == "run":
        result = runner.run(args.loop_id, resume=args.resume)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_loop_result(result))
        return 0 if result.ok else 1
    raise SystemExit("unknown loop command")


def _loop_text(args: argparse.Namespace, field: str) -> str:
    """Return natural-language text from argparse positional fragments.

    `loop plan` and `loop revise` intentionally accept free-form text.  Use
    `nargs="+"` (not REMAINDER) in the parser so options such as
    `--show-spec` work both before and after the request, then join the text
    fragments here for the planner/session API.
    """

    value = getattr(args, field, "")
    if isinstance(value, list):
        return " ".join(value).strip()
    return str(value or "").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evolva",
        description="Open Evolva's TUI workbench by default. Subcommands are reserved for automation and CI.",
    )
    parser.add_argument("--chat", action="store_true", help="Start plain line-based chat instead of the default TUI")
    parser.add_argument("--yes", action="store_true", help="Approve shell/python tools without prompting in default TUI mode")
    parser.add_argument("--no-tools", action="store_true", help="Hide the TUI tool log panel at startup")
    parser.add_argument("--fullscreen", action="store_true", help="Use the legacy full-screen curses TUI")
    sub = parser.add_subparsers(dest="cmd", required=False, metavar="{tui,ask,trace,metrics,sandbox,eval,benchmark,evolve,optimize,dream,loop,workflow,mcp}")
    tui_p = sub.add_parser("tui", help="Open the Evolva TUI workbench explicitly")
    tui_p.add_argument("--yes", action="store_true", help="Approve shell/python tools without prompting")
    tui_p.add_argument("--no-tools", action="store_true", help="Hide the tool log panel at startup")
    tui_p.add_argument("--fullscreen", action="store_true", help="Use the legacy full-screen curses TUI")
    tui_p.set_defaults(func=tui)

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

    metrics_p = sub.add_parser("metrics", help="Automation: inspect local runtime metrics and alerts")
    metrics_sub = metrics_p.add_subparsers(dest="metrics_cmd", required=True)
    metrics_list = metrics_sub.add_parser("list", help="List recent metrics")
    metrics_list.add_argument("--limit", type=int, default=20)
    metrics_list.set_defaults(func=metrics_cmd)
    metrics_alerts = metrics_sub.add_parser("alerts", help="List recent alert events")
    metrics_alerts.add_argument("--limit", type=int, default=20)
    metrics_alerts.set_defaults(func=metrics_cmd)
    metrics_prometheus = metrics_sub.add_parser("prometheus", help="Export metrics as Prometheus text")
    metrics_prometheus.set_defaults(func=metrics_cmd)

    sandbox_p = sub.add_parser("sandbox", help="Automation: inspect and smoke-test the configured sandbox backend")
    sandbox_sub = sandbox_p.add_subparsers(dest="sandbox_cmd", required=True)
    sandbox_info = sandbox_sub.add_parser("info", help="Show sandbox backend configuration")
    sandbox_info.set_defaults(func=sandbox_cmd)
    sandbox_smoke = sandbox_sub.add_parser("smoke", help="Run fixed smoke check through the configured sandbox backend")
    sandbox_smoke.add_argument("--timeout", type=int, default=10)
    sandbox_smoke.set_defaults(func=sandbox_cmd)

    eval_p = sub.add_parser("eval", help="Automation: run jsonl eval tasks")
    eval_p.add_argument("tasks", type=lambda s: __import__("pathlib").Path(s))
    eval_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during eval")
    eval_p.add_argument("--baseline", type=lambda s: __import__("pathlib").Path(s), help="Compare against a checked-in eval baseline JSON")
    eval_p.add_argument("--min-score", type=float, help="Require the average eval score to be at least this value")
    eval_p.add_argument("--no-regression", action="store_true", help="Fail if any baseline task regresses")
    eval_p.set_defaults(func=eval_cmd)

    benchmark_p = sub.add_parser("benchmark", help="Automation: inspect and dry-run benchmark tasks")
    benchmark_sub = benchmark_p.add_subparsers(dest="benchmark_cmd", required=True)
    benchmark_health = benchmark_sub.add_parser("health", help="Report optional OCR/PDF/audio/video/web tools for stronger benchmark coverage")
    benchmark_health.add_argument("--json", action="store_true", help="Print JSON health report")
    benchmark_health.set_defaults(func=benchmark_cmd)
    benchmark_inspect = benchmark_sub.add_parser("inspect-file", help="Preview one benchmark-style attachment and optionally run deeper media/OCR/PDF tools")
    benchmark_inspect.add_argument("path", type=lambda s: __import__("pathlib").Path(s), help="Attachment path to inspect")
    benchmark_inspect.add_argument("--max-chars", type=int, default=20000, help="Text output budget")
    benchmark_inspect.add_argument("--max-rows", type=int, default=20, help="Table row preview budget")
    benchmark_inspect.add_argument("--deep", action="store_true", help="Run optional OCR/transcription/probe/PDF extraction when supported")
    benchmark_inspect.add_argument("--language", default="eng", help="OCR/Whisper language hint")
    benchmark_inspect.add_argument("--model", default="base", help="Whisper model name for --deep audio transcription")
    benchmark_inspect.add_argument("--timeout", type=int, default=120, help="External tool timeout in seconds")
    benchmark_inspect.add_argument("--frames-dir", type=lambda s: __import__("pathlib").Path(s), help="Directory for --deep video frame extraction")
    benchmark_inspect.add_argument("--every-seconds", type=float, default=10.0, help="Video frame interval for --frames-dir")
    benchmark_inspect.add_argument("--max-frames", type=int, default=12, help="Maximum video frames to extract")
    benchmark_inspect.add_argument("--json", action="store_true", help="Print JSON inspection report")
    benchmark_inspect.set_defaults(func=benchmark_cmd)
    benchmark_smoke = benchmark_sub.add_parser("smoke", help="Read benchmark metadata/attachments and report local readiness")
    benchmark_smoke.add_argument("--metadata", required=True, type=lambda s: __import__("pathlib").Path(s), help="benchmark metadata.csv path")
    benchmark_smoke.add_argument("--attachments", required=True, type=lambda s: __import__("pathlib").Path(s), help="benchmark attachment directory")
    benchmark_smoke.add_argument("--limit", type=int, default=0, help="Number of rows to inspect; 0 means all rows")
    benchmark_smoke.add_argument("--max-chars", type=int, default=4000, help="Attachment preview character budget per file")
    benchmark_smoke.add_argument("--json", action="store_true", help="Print JSON report")
    benchmark_smoke.add_argument("--strict", action="store_true", help="Exit non-zero if attachments are missing or previews fail")
    benchmark_smoke.add_argument("--output", type=lambda s: __import__("pathlib").Path(s), help="Directory to write benchmark_smoke_*.json")
    benchmark_smoke.set_defaults(func=benchmark_cmd)
    benchmark_run = benchmark_sub.add_parser("run", help="Build benchmark prompts, or run a small sample through the agent with --run-agent")
    benchmark_run.add_argument("--metadata", required=True, type=lambda s: __import__("pathlib").Path(s), help="benchmark metadata.csv path")
    benchmark_run.add_argument("--attachments", required=True, type=lambda s: __import__("pathlib").Path(s), help="benchmark attachment directory")
    benchmark_run.add_argument("--limit", type=int, default=1, help="Number of tasks to prepare/run")
    benchmark_run.add_argument("--level", help="Optional benchmark level filter, e.g. 1, 2, 3")
    benchmark_run.add_argument("--run-agent", action="store_true", help="Actually call EvolvaAgent; otherwise only print prompts")
    benchmark_run.add_argument("--include-answers", action="store_true", help="Include reference answers and exact-match fields for local evaluation")
    benchmark_run.add_argument("--max-attachment-chars", type=int, default=8000, help="Attachment text budget in prompts")
    benchmark_run.add_argument("--json", action="store_true", help="Print JSON rows")
    benchmark_run.add_argument("--yes", action="store_true", help="Approve tools during --run-agent")
    benchmark_run.set_defaults(func=benchmark_cmd)

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
    dream_sub = dream_p.add_subparsers(dest="dream_cmd", required=False)
    dream_backlog = dream_sub.add_parser("backlog", help="Show staged Dream improvement candidates")
    dream_backlog.add_argument("--limit", type=int, default=20, help="Candidate limit")
    dream_backlog.set_defaults(func=dream_cmd)
    dream_verify = dream_sub.add_parser("verify", help="Run candidate verifiers against local eval/trace evidence")
    dream_verify.add_argument("--tasks", type=lambda s: __import__("pathlib").Path(s), help="JSONL eval task file for eval verifiers")
    dream_verify.add_argument("--limit", type=int, default=20, help="Candidate and trace limit")
    dream_verify.add_argument("--promote", action="store_true", help="Promote verified candidates in the Dream backlog")
    dream_verify.add_argument("--json", action="store_true", help="Print verifier results as JSON")
    dream_verify.set_defaults(func=dream_cmd)
    dream_p.add_argument("--apply", action="store_true", help="Stage high-confidence proposals for verifier review")
    dream_p.add_argument("--limit", type=int, default=20, help="Recent trace run limit")
    dream_p.add_argument("--report", type=lambda s: __import__("pathlib").Path(s), help="Eval report JSON; defaults to latest")
    dream_p.add_argument("--min-confidence", type=float, default=None, help="Minimum confidence for automatic Dreaming promotion")
    dream_p.add_argument("--json", action="store_true", help="Print the full Dream report JSON")
    dream_p.set_defaults(func=dream_cmd)

    loop_p = sub.add_parser("loop", help="Automation: run repeatable agent loops; in daily use prefer TUI /loop")
    loop_p.add_argument("--yes", action="store_true", help="Approve shell/python tools during loop runs")
    loop_sub = loop_p.add_subparsers(dest="loop_cmd", required=True)
    loop_list = loop_sub.add_parser("list", help="List built-in and workspace loops")
    loop_list.set_defaults(func=loop_cmd)
    loop_plan = loop_sub.add_parser("plan", help="Create a Loop draft from a natural language request; does not execute")
    loop_plan.add_argument("--show-spec", action="store_true", help="Include generated LoopSpec JSON")
    loop_plan.add_argument("request", nargs="+")
    loop_plan.set_defaults(func=loop_cmd)
    loop_draft = loop_sub.add_parser("show-draft", help="Show the active generated Loop draft")
    loop_draft.add_argument("--show-spec", action="store_true", help="Include generated LoopSpec JSON")
    loop_draft.set_defaults(func=loop_cmd)
    loop_revise = loop_sub.add_parser("revise", help="Revise the active generated Loop draft")
    loop_revise.add_argument("--show-spec", action="store_true", help="Include generated LoopSpec JSON")
    loop_revise.add_argument("feedback", nargs="+")
    loop_revise.set_defaults(func=loop_cmd)
    loop_approve = loop_sub.add_parser("approve", help="Resolve open questions with a user confirmation note")
    loop_approve.add_argument("--show-spec", action="store_true", help="Include generated LoopSpec JSON")
    loop_approve.add_argument("confirmation", nargs="*")
    loop_approve.set_defaults(func=loop_cmd)
    loop_accept = loop_sub.add_parser("accept", help=argparse.SUPPRESS)
    loop_accept.add_argument("--show-spec", action="store_true", help=argparse.SUPPRESS)
    loop_accept.add_argument("confirmation", nargs="*")
    loop_accept.set_defaults(func=loop_cmd)
    loop_confirm = loop_sub.add_parser("confirm", help="Validate/dry-run the active generated Loop draft")
    loop_confirm.set_defaults(func=loop_cmd)
    loop_execute = loop_sub.add_parser("execute", help="Execute the active generated Loop after confirm")
    loop_execute.add_argument("--json", action="store_true", help="Print run result JSON")
    loop_execute.set_defaults(func=loop_cmd)
    loop_save = loop_sub.add_parser("save", help="Save active generated Loop draft as reusable JSON")
    loop_save.add_argument("name", nargs="?", default="")
    loop_save.set_defaults(func=loop_cmd)
    loop_cancel = loop_sub.add_parser("cancel", help="Cancel and clear active generated Loop draft")
    loop_cancel.set_defaults(func=loop_cmd)
    loop_show = loop_sub.add_parser("show", help="Show one loop spec as JSON")
    loop_show.add_argument("loop_id")
    loop_show.set_defaults(func=loop_cmd)
    loop_validate = loop_sub.add_parser("validate", help="Validate a loop by ID or JSON path")
    loop_validate.add_argument("loop_id")
    loop_validate.set_defaults(func=loop_cmd)
    loop_dry_run = loop_sub.add_parser("dry-run", help="Validate a loop, tool availability, command allowlist, and policy without executing phases")
    loop_dry_run.add_argument("loop_id")
    loop_dry_run.set_defaults(func=loop_cmd)
    loop_run = loop_sub.add_parser("run", help="Run a loop by ID or JSON path")
    loop_run.add_argument("loop_id")
    loop_run.add_argument("--json", action="store_true", help="Print run result JSON")
    loop_run.add_argument("--resume", action="store_true", help="Reuse successful outputs from the latest failed run of the same loop")
    loop_run.set_defaults(func=loop_cmd)

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
    mcp_add_p.add_argument("--env", action="append", default=[], help="Environment variable for the server, KEY=VALUE; may repeat")
    mcp_add_p.add_argument("--yes", action="store_true")
    mcp_add_p.add_argument("args", nargs=argparse.REMAINDER)
    mcp_add_p.set_defaults(func=mcp_cmd)
    mcp_presets_p = mcp_sub.add_parser("presets", help="List built-in browser/search/fetch MCP presets")
    mcp_presets_p.add_argument("--yes", action="store_true")
    mcp_presets_p.set_defaults(func=mcp_cmd)
    mcp_add_preset_p = mcp_sub.add_parser("add-preset", help="Persist a built-in MCP preset such as playwright or brave-search")
    mcp_add_preset_p.add_argument("preset")
    mcp_add_preset_p.add_argument("--name", default="", help="Optional server name; defaults to the preset name")
    mcp_add_preset_p.add_argument("--env", action="append", default=[], help="Environment variable for the server, KEY=VALUE; may repeat")
    mcp_add_preset_p.add_argument("--yes", action="store_true")
    mcp_add_preset_p.set_defaults(func=mcp_cmd)
    mcp_remove_p = mcp_sub.add_parser("remove", help="Remove a configured MCP server")
    mcp_remove_p.add_argument("name")
    mcp_remove_p.add_argument("--yes", action="store_true")
    mcp_remove_p.set_defaults(func=mcp_cmd)
    mcp_tools_p = mcp_sub.add_parser("tools", help="List MCP tools")
    mcp_tools_p.add_argument("server", nargs="?")
    mcp_tools_p.add_argument("--yes", action="store_true")
    mcp_tools_p.set_defaults(func=mcp_cmd)
    mcp_health_p = mcp_sub.add_parser("health", help="Check MCP server health and schema cache")
    mcp_health_p.add_argument("server", nargs="?")
    mcp_health_p.add_argument("--refresh", action="store_true", help="Bypass tool schema cache")
    mcp_health_p.add_argument("--yes", action="store_true")
    mcp_health_p.set_defaults(func=mcp_cmd)
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
        return tui(argparse.Namespace(yes=args.yes, no_tools=args.no_tools, fullscreen=args.fullscreen))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
