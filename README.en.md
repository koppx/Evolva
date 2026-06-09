<p align="center">
  <img src="assets/evolva-poster.jpeg" alt="Evolva poster - Local Self-Evolving Agent Harness" width="680" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>Production-oriented · Local-first · Self-Evolving Agent Harness</strong><br />
  A local agent runtime foundation that connects repository context, tool execution, Trace/Replay, Eval baselines, Guardrails, and Self-Evolution into one auditable loop.
</p>

<p align="center">
  <a href="README.md">中文</a> · <a href="#quick-start">Quick Start</a> · <a href="#capability-map">Capability Map</a> · <a href="#self-evolution">Self-Evolution</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="TUI-first" src="https://img.shields.io/badge/TUI--first-Workbench-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

## Why Evolva

Evolva is not a chatbot wrapper. It is a **local-first harness** for engineering agents that need to understand repository context, execute tools safely, preserve evidence, pass evals, and turn failures into reusable capability assets.

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

Every run is designed to leave behind inspectable traces, reproducible eval signals, and reusable lessons. Evolva is a modular agent control plane: transparent, extensible, auditable, and built for long-term improvement.

## Quick Start

Evolva is TUI-first. After installation, run `evolva` to open the local workbench for chat, tool execution, MCP onboarding, Trace inspection, model switching, Workflow orchestration, and Self-Evolution.

```bash
git clone git@github.com:koppx/Evolva.git
cd Evolva
python3 -m pip install -e ".[dev]"

# Optional: any OpenAI-compatible endpoint
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"

# Default product entry: TUI workbench
evolva
```

Inside the TUI, use Slash Commands:

```text
/model gpt-4o-mini
/repo build
/repo search SelfEvolutionEngine
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .
/mcp tools filesystem
/trace list
/dream --min-confidence 0.8
/evolve audit
```


Without `OPENAI_API_KEY`, Evolva falls back to a limited local rule-based mode. Local tools, memory, skills, todo, traces, workflows, and evals remain available for offline testing and extension.

## Positioning

Evolva is a composable, observable, and continuously improving Agent Harness. It decomposes engineering-agent behavior into modules that can be inspected, extended, and validated locally:

- **Repo-aware**: builds searchable engineering context from repository index, memory, context, todo, and skills.
- **Traceable**: persists tool calls, policy decisions, failures, context events, and final outputs for replay and audit.
- **Evaluable**: turns agent behavior into JSONL regression assets through Eval Harness.
- **Self-improving**: distills feedback, trace patterns, and eval failures into long-term memory and Markdown skills.
- **Local-first**: runs against local files and sandboxed execution by default, without mandatory cloud dependencies.

## Capability Map

| Capability | What it does | Entry |
| --- | --- | --- |
| **LangGraph Runtime** | Explicit `StateGraph` nodes: `prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **TUI Workbench** | Default product entry for chat, tool logs, Trace, model switching, MCP, Workflow, and Self-Evolution | `evolva` |
| **Tools** | File, shell, Python, web, todo, memory, context, policy, MCP, delegation | `/tools` / `/run` |
| **Repo Index** | Local semantic repository index for symbols, references, paths, and code chunks | `/repo build` / `/repo search` |
| **Memory / Skills** | Long-term facts, preferences, lessons, Markdown playbooks | `/memory` / `/skills` |
| **MCP** | Add stdio MCP servers inside the TUI with `/mcp add`, then inspect/call tools via `/mcp tools` and `mcp_call` | `/mcp` |
| **Workflow** | JSON workflow specs with role agents, agent calls, and tool nodes, launched from the TUI | `/workflow` |
| **Trace / Replay** | Prompts, tool calls, policy decisions, latency, errors, outputs, inspectable in the TUI | `/trace` |
| **Eval Harness** | JSONL tasks with text, regex, artifacts, memory, context, and tool-error checks | `evolva eval ...` |
| **Guardrails / Sandbox** | Path sandbox, dangerous command denylist, risk scoring, secret detection, approvals | `/policy` |
| **Self-Evolution** | Turns feedback, trace patterns, and eval failures into memory and skills | `/evolve` / `/dream` |
| **Dreaming** | Local background reflection: Evidence → Hypothesis → Critique → Action, with auditable reports and optional high-confidence promotion | `/dream` |

## Architecture

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva architecture" width="100%" />
</p>

Evolva is organized into three lanes:

1. **Reasoning & State**: the TUI Workbench is the default product entry. The scriptable CLI remains an automation path into Evolva Core, where the LangGraph runtime manages state and assembles Memory, Skills, Todo, Context, and Repo Index.
2. **Guarded Execution**: tool calls pass through Policy and Sandbox before reaching files, shell, Python, web, MCP, workflows, and sub agents.
3. **Feedback Loop**: Trace records behavior, Eval checks regressions, and Evolution distills feedback into long-term memory and reusable skills.

## Self-Evolution

Evolva's evolution loop is a concrete state update pipeline:

```text
Feedback / Trace Pattern / Eval Failure
        ↓
Reflection
        ↓
Dream Report
        ↓
Long-term Memory
        ↓
Markdown Skill
        ↓
Future Prompt Context
```

TUI examples:

```text
/evolve audit
/evolve After editing Python files, run syntax checks and pytest.
/evolve trace
/evolve apply-trace
/evolve apply-eval
/dream
/dream apply --min-confidence 0.8
```

The resulting lessons include **category / confidence / evidence / fingerprint**, are persisted in memory, and can be materialized as Markdown skills for future context injection. `evolve audit` summarizes lesson coverage, evolved skills, pending Trace/Eval proposals, and recommended next steps.

`dream` is Evolva's local Dreaming loop. It is inspired by publicly observable background-reflection workflows, but remains fully local-first and does not require an extra cloud service or LLM. It scans recent traces, the latest eval report, and current Memory/Skill coverage, then runs **Evidence → Hypothesis → Critique → Action**: collect signals, generate falsifiable hypotheses, reject low-confidence/duplicate/weak-evidence items with deterministic drift guards, and write an auditable `evolva/dreams/*.json` report. With `--apply`, only high-confidence proposals pass through the Self-Evolution quality gate into Memory / Skill.

## TUI Workbench

Daily usage is centered on Slash Commands inside the TUI. The command-line subcommands remain for automation, CI, and one-shot scripting.

```bash
# Main product entry
evolva

# Traditional line-based chat, if needed
evolva --chat
```

Common TUI flows:

```text
/model [name]                         Show/switch model
/repo build                           Build repository index
/repo search <query>                  Search code symbols, references, and chunks
/mcp                                  List configured MCP servers
/mcp add <name> <command> [args...]   Add a stdio MCP server
/mcp tools [server]                   List MCP tools
/run mcp_call {"server":"...","tool":"...","arguments":{}}
/trace list                           List recent runs
/trace context latest                 Inspect latest context/prompt events
/workflow <json>                      Run a workflow spec
/evolve audit                         Inspect self-evolution coverage
/dream --min-confidence 0.8           Run Dreaming drift-guard analysis
```

> For daily use, remember only `evolva`. The scriptable interface is for maintainers and CI: `evolva eval ...` runs JSONL regression evals, and `evolva dream --json` exports a machine-readable Dreaming report.

<details>
<summary><strong>Interactive Slash Commands</strong></summary>

```text
/help                     Show help
/tools                    List tools
/skills                   List skills
/memory [query]           Show or search long-term memory
/memory stats             Show memory statistics
/memory recent [n]        Show recent memories
/context [query]          Show persistent context
/todo                     Show todo list
/todo add <title>         Add a todo
/todo done <id>           Mark a todo as done
/agents                   List role agents
/trace list               List recent traces
/trace show <run_id>      Show one trace
/trace context <run_id>   Show context / prompt events from a trace
/model [name]             Show or switch the active model
/policy                   Show guardrail policy
/repo build               Build the local repository index
/repo search <query>      Search code symbols, references, and chunks
/mcp                      List MCP servers
/mcp add <name> <cmd...>  Add a stdio MCP server
/mcp remove <name>        Remove an MCP server config
/mcp tools [server]       List MCP tools
/image <path|url> [text]  Ask with an image
/evolve [feedback]        Turn feedback into memory + skill
/dream                    Run an offline Dreaming reflection report
/dream --min-confidence n  Tune the drift-guard confidence threshold
/dream apply              Apply high-confidence Dreaming proposals
/workflow <json>          Run a workflow spec
/run <tool> <json>        Call a tool directly
/exit                     Quit
```

</details>

## Workflow Example

```json
{
  "id": "verified_python_task",
  "nodes": [
    {"id": "plan", "type": "role", "role": "planner", "task": "Plan a verifiable Python engineering task"},
    {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/verified_task.py", "content": "print('hello from Evolva')\n"}},
    {"id": "run", "type": "tool", "tool": "shell", "args": {"command": "python3 evolva/workspace/verified_task.py"}}
  ]
}
```

## Eval Example

```json
{"id":"tool_write_read_001","input":"Create hello.py and run it","expected_artifacts":["evolva/workspace/hello.py"],"expected_contains":["hello"],"scorers":["no_tool_error"]}
```

Supported checks include `expected_contains`, `forbidden_contains`, `expected_regex`, `expected_artifacts`, `expected_memory`, `expected_context`, `max_duration_ms`, and `no_tool_error`.

## TUI Preview

<p align="center">
  <img src="assets/tui-mockup.svg" alt="Evolva TUI mockup" width="100%" />
</p>

TUI supports common workstation shortcuts:

| Shortcut | Action |
| --- | --- |
| `F2` | Prepare `/model` for quick model switching |
| `Ctrl+R` | Show recent traces |
| `Ctrl+X` | Show context / prompt events from the latest trace |
| `Ctrl+T` | Show / hide tool logs |
| `PgUp` / `PgDn` | Scroll chat history |
| `Tab` | Complete common slash commands |

## Workflow / MCP / Memory

<p align="center">
  <img src="assets/workflow-mcp-memory.svg" alt="Evolva workflow MCP memory" width="100%" />
</p>

## Safety Model

Evolva is local-first and can execute file, shell, and Python operations, so it ships with multiple guardrails by default:

- **Sandbox root**: file tools resolve paths through the workspace sandbox to prevent path escape.
- **Dangerous command denylist**: blocks patterns such as `rm -rf /`, `git reset --hard`, `mkfs`, and `shutdown`.
- **Policy engine**: scores shell / Python, network, path, and secret-pattern risks.
- **Confirmation gate**: shell, Python, and MCP tools can require approval unless `--yes` is set.
- **Trace audit**: decisions, tool calls, failures, and final answers are persisted for review.

## Development

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
```

## Project Structure

```text
evolva/
  cli.py                     `evolva` console entry, defaults to TUI
  tui.py                     TUI workbench
  agent/core.py              public agent facade
  agent/langgraph_runtime.py LangGraph StateGraph runtime
  agent/dream.py             offline Dream reflection loop
  agent/evolution.py         lesson + skill evolution engine
  agent/evolution_analyzer.py trace / eval evolution analyzer
  agent/images.py            local/URL image input
  agent/mcp.py               stdio MCP client
  agent/memory.py            long-term memory
  agent/policy.py            guardrails and risk decisions
  agent/sandbox.py           workspace sandbox and execution
  tools/builtin.py           built-in tool registry
  eval/harness.py            JSONL eval runner
  workflow/engine.py         workflow DAG engine
assets/
  evolva-poster.jpeg        README hero poster
  architecture.svg
  tui-mockup.svg
  workflow-mcp-memory.svg
```

---

<p align="center">
  <strong>Evolva</strong> · Local-first, inspectable, self-evolving Agent Harness.<br />
  If you are building evaluable, replayable, self-improving agent systems, star <strong>koppx/Evolva</strong>.
</p>
