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
  <a href="https://github.com/koppx/Evolva/stargazers">
    <img alt="GitHub stars" src="https://img.shields.io/github/stars/koppx/Evolva?style=for-the-badge&logo=github&label=Stars&color=EAD58B&labelColor=0B0B0F&cacheSeconds=1800" />
  </a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="TUI-first" src="https://img.shields.io/badge/TUI--first-Workbench-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

## Why Evolva

Evolva is a **local-first harness** for engineering agents: a runtime foundation for repository context, guarded tool execution, evidence preservation, regression evaluation, and capability distillation.

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

Every run produces inspectable traces, reproducible eval signals, and reusable lessons. Evolva is a modular agent control plane: transparent, extensible, auditable, and built for long-term improvement.

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
/repo status
/repo search evolution
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .
/mcp tools filesystem
/trace list
/dream --min-confidence 0.8
/evolve audit
```

Even without `OPENAI_API_KEY`, Evolva can run local tools, memory, skills, todo, traces, workflows, and evals for local validation and extension.

Runtime state is isolated from the Python package by default. Provider config, memory, context, todo, traces, metrics, artifacts, eval results, MCP server config, and repo index files live under `.evolva/`; set `EVOLVA_RUNTIME_HOME` to place them elsewhere.

## Positioning

Evolva is a composable, observable, and continuously improving Agent Harness. It decomposes engineering-agent behavior into modules that can be inspected, extended, and validated locally:

- **Repo-aware**: builds searchable engineering context from repository index, memory, context, todo, and skills.
- **Traceable**: persists tool calls, policy decisions, failures, context events, and final outputs for replay and audit.
- **Evaluable**: turns agent behavior into JSONL regression assets through Eval Harness.
- **Self-improving**: distills feedback, trace patterns, and eval failures into long-term memory and Markdown skills.
- **Local-first**: runs against local files and sandboxed execution by default, without mandatory cloud dependencies.

## Capability Map

| Capability | Reader-facing value | Entry |
| --- | --- | --- |
| **TUI Workbench** | One place for chat, tools, traces, model switching, and MCP onboarding | `evolva` |
| **Repo Index** | Let the agent search files, symbols, and code chunks by repository meaning | `/repo` |
| **Tools** | Call local tools under policy, sandbox, and trace controls | `/tools` / `/run` |
| **Workflow / Loop** | Save repeatable engineering tasks with gates, evidence, and resume | `/workflow` / `/loop` |
| **Trace / Replay** | Keep the proof trail for inputs, tools, decisions, failures, and outputs | `/trace` |
| **Eval Harness** | Turn agent behavior into regression tests | `evolva eval` |
| **Memory / Skills** | Promote only governed experience into future context | `/memory` / `/skills` |
| **Guardrails / Sandbox** | Keep local execution bounded, confirmable, and reviewable | `/policy` |
| **Self-Evolution** | Distill feedback and failures into reusable lessons | `/evolve` / `/dream` |

## Architecture

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva architecture" width="100%" />
</p>

Evolva is organized into three lanes:

1. **Reasoning & State**: the TUI Workbench is the default product entry. Evolva Core uses the LangGraph runtime to manage state and assemble Memory, Skills, Todo, Context, and Repo Index.
2. **Guarded Execution**: tool calls pass through Policy and Sandbox before reaching files, shell, Python, web, MCP, workflows, and sub agents.
3. **Feedback Loop**: Trace records behavior, Eval checks regressions, and Evolution distills feedback into long-term memory and reusable skills.

## Self-Evolution

<p align="center">
  <img src="assets/evolva-dreaming-loop.jpeg" alt="Evolva Dreaming Loop" width="100%" />
</p>

Evolva's evolution loop is a concrete state update pipeline:

```text
Feedback / Trace Pattern / Eval Failure
        ↓
Evidence
        ↓
Hypothesis
        ↓
Candidate + Verifier
        ↓
Dream Backlog
        ↓
Verified Promotion
        ↓
Long-term Memory / Markdown Skill
```

TUI examples:

```text
/evolve audit
/evolve After editing Python files, run syntax checks and pytest.
/evolve trace
/evolve apply-trace
/evolve apply-eval
/dream
/dream status
/dream backlog
/dream apply --min-confidence 0.8
/dream verify --promote
```

Evolva turns feedback and failure patterns into traceable lessons, then promotes useful ones into long-term memory or Markdown skills. `evolve audit` shows what has already been learned and which Trace / Eval findings still need attention.

`dream` is the more conservative path. It creates improvement candidates first, then requires verifier confirmation before anything becomes durable Memory / Skill. By default, `/dream apply` only stages candidates; `/dream verify --promote` performs the actual promotion.

## TUI Workbench

Daily usage is centered on the TUI Workbench: chat, tool execution, MCP onboarding, Trace inspection, model switching, Workflow orchestration, and Self-Evolution all converge into the same Slash Command surface.

```bash
evolva
```

Common TUI flows:

```text
/model [name]                         Show/switch model
/repo build                           Build repository index
/repo status                          Show index freshness and skipped-file diagnostics
/repo search <query>                  Search code symbols, references, and chunks
/mcp                                  List configured MCP servers
/mcp add <name> <command> [args...]   Add a stdio MCP server
/mcp tools [server]                   List MCP tools
/mcp health [server]                  Check MCP health and schema cache
/run mcp_call {"server":"...","tool":"...","arguments":{}}
/trace list                           List recent runs
/trace context latest                 Inspect latest context/prompt events
/workflow <json>                      Run a workflow spec
/evolve audit                         Inspect self-evolution coverage
/dream --min-confidence 0.8           Run Dreaming quality-gate analysis
/dream status                         Show Dream gate and promotion status
/dream backlog                        Show staged Dream improvement candidates
/dream verify                         Run candidate verifiers
/dream verify --promote               Promote passing candidates to Memory / Skill
```

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
/dream                    Run a Dreaming quality-gate report
/dream status             Show Dream gate and promotion status
/dream backlog            Show staged Dream improvement candidates
/dream verify             Run candidate verifiers
/dream verify --promote   Promote passing candidates to Memory / Skill
/dream --min-confidence n  Tune the drift-guard confidence threshold
/dream apply              Stage high-confidence Dreaming candidates
/workflow <json>          Run a workflow spec
/run <tool> <json>        Call a tool directly
/exit                     Quit
```

</details>

## Workflow Example

Workflow is the low-level DAG format for explicit dependencies and tool steps. Each run leaves state, outputs, and errors under the runtime home so later Eval / Dream passes can reuse the evidence.

MCP is treated as a production integration point: tool schemas are cached, temporary server failures can fall back to known schemas, and `/mcp health` shows status, latency, tool count, and errors.

Memory / Skill governance separates "stored for audit" from "allowed into the prompt." Draft, quarantined, and rolled-back items remain visible but do not influence agent behavior automatically.

Repo Index remembers what was indexed, what was skipped, and what can be reused. Runtime artifacts are ignored so traces and audit files do not constantly invalidate search.

Multi-agent is governed collaboration, not unbounded autonomy. The Task Router can classify the request first: simple questions stay single-agent, research tasks use researcher/reviewer, coding tasks use planner/coder/reviewer, and broad engineering tasks use the full role set. Automatic collaboration is off by default and can be enabled with `EVOLVA_MULTI_AGENT_AUTO_ROUTE=1`. Sub-agents only get low-side-effect read, search, and inspection tools by default; writes, shell/Python, MCP calls, and recursive delegation are outside the default scope.

```json
{
  "id": "evolution_audit_flow",
  "nodes": [
    {"id": "recall", "type": "tool", "tool": "recall", "args": {"query": "evolution"}},
    {"id": "policy", "type": "tool", "tool": "policy_info", "args": {}},
    {"id": "review", "type": "role", "role": "reviewer", "task": "Review the current self-evolution safety boundary using {{recall}} and {{policy}}"}
  ]
}
```

## Eval Example

```json
{"id":"policy_trace_001","input":"Run a tool-backed safety check task","expected_contains":["ok"],"scorers":["no_tool_error"]}
```

Each eval is an auditable behavior contract: the prompt, the expected outcome, and the evidence that proves the agent did the right thing.

Common checks fall into four buckets:

| Bucket | Examples |
| --- | --- |
| Output quality | contains, forbidden text, regex |
| Runtime evidence | trace events, tool sequence, latency |
| Artifact state | file existence, content, manifest provenance |
| Safety signals | policy audit, sandbox rollback, MCP timeout, secret redaction |

Baselines live in `evals/baselines/`; CI wiring lives in `.github/workflows/ci.yml`.

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

Evolva can touch files and run code, so safety is part of the default runtime rather than an optional layer:

| Boundary | Purpose |
| --- | --- |
| Path sandbox | Keep file access inside the project root |
| Writable roots | Write only to `.evolva/workspace` by default; extend deliberately |
| Failure rollback | Restore protected files after failed shell / Python runs |
| Dangerous command blocklist | Stop high-risk command patterns before execution |
| Policy audit | Record allow, deny, and confirmation decisions |
| Human confirmation | Require approval for high-risk tools outside `--yes` mode |
| Trace review | Keep tool calls, failures, and final outputs inspectable |

## Development

Evolva checks can be wired into CI to protect the Trace / Eval / Self-Evolution regression baseline. Security evals keep policy, MCP, sandbox, and redaction behavior from quietly regressing.

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
evolva eval evals/tasks/smoke.jsonl --yes
evolva dream --json
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
  eval/harness.py            JSONL regression harness
  workflow/engine.py         workflow DAG engine
assets/
  evolva-poster.jpeg        README hero poster
  architecture.svg
  tui-mockup.svg
  workflow-mcp-memory.svg
```

## Star History

<p align="center">
  <a href="https://www.star-history.com/#koppx/Evolva&Date">
    <img src="https://api.star-history.com/svg?repos=koppx/Evolva&type=Date" alt="Evolva Star History" width="100%" />
  </a>
</p>

---

<p align="center">
  <strong>Evolva</strong> · Local-first, inspectable, self-evolving Agent Harness.<br />
  If you are building evaluable, replayable, self-improving agent systems, star <strong>koppx/Evolva</strong>.
</p>
