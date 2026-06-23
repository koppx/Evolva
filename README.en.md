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

| Capability | What it does | Entry |
| --- | --- | --- |
| **LangGraph Runtime** | Explicit `StateGraph` nodes: `prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **TUI Workbench** | Default product entry for chat, tool logs, Trace, model switching, MCP, Workflow, and Self-Evolution | `evolva` |
| **Tools** | File, shell, Python, web, todo, memory, context, policy, MCP, delegation | `/tools` / `/run` |
| **Repo Index** | Local semantic repository index with file manifests, incremental reuse, stale detection, and skipped-file diagnostics | `/repo build` / `/repo status` / `/repo search` |
| **Memory / Skills** | Long-term facts, preferences, lessons, and Markdown playbooks with evidence/status governance | `/memory` / `/skills` |
| **MCP** | Add stdio MCP servers inside the TUI with `/mcp add`, then inspect/call tools via `/mcp tools` and `mcp_call` | `/mcp` |
| **Workflow** | JSON workflow specs with role agents, agent calls, and tool nodes, launched from the TUI | `/workflow` |
| **Trace / Replay** | Prompts, tool calls, policy decisions, latency, errors, outputs, inspectable in the TUI | `/trace` |
| **Eval Harness** | JSONL tasks with text, regex, artifacts, memory, context, and tool-error checks | CI / Regression |
| **Guardrails / Sandbox** | Path sandbox, dangerous command denylist, risk scoring, secret detection, approvals | `/policy` |
| **Self-Evolution** | Turns feedback, trace patterns, and eval failures into memory and skills | `/evolve` / `/dream` |
| **Dreaming** | Local self-evolution research loop: Evidence → Hypothesis → Candidate → Verifier → Promotion, with auditable reports and an improvement backlog | `/dream` |

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

The resulting lessons include **category / confidence / evidence / fingerprint**, are persisted in memory, and can be materialized as Markdown skills for future context injection. `evolve audit` summarizes lesson coverage, evolved skills, pending Trace/Eval proposals, and recommended next steps.

`dream` is Evolva's local self-evolution research loop. It scans recent traces, the latest eval report, and current Memory/Skill coverage, then runs **Evidence → Hypothesis → Candidate → Verifier → Promotion**. Accepted hypotheses become `DreamCandidate` records with affected surfaces, risk, proposed change, and verifier metadata, then land in the runtime home, by default `.evolva/dreams/backlog.json`, as an improvement backlog. By default, `/dream apply` stages high-confidence candidates for verifier review but does not write Memory / Skill. Durable promotion happens through `/dream verify --promote` after local Eval, Trace, or manual verifiers pass. Set `EVOLVA_DREAM_REQUIRE_VERIFICATION=0` only when you intentionally want the legacy immediate-apply behavior.

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

Workflow is the low-level DAG execution format. Each run persists status, node outputs, and errors under the runtime home; resume can reuse successful unchanged nodes by fingerprint so a long DAG does not need to restart from zero after a late failure.

MCP tool discovery persists server schemas in `mcp/tools-cache.json` under the runtime home. If a server is temporarily unavailable, Evolva can degrade to the cached schema. `/mcp health [server]` and `evolva mcp health` report status, tool count, latency, cache age, and errors, and emit `mcp.health` / `mcp.error` metrics.

Memory / Skill governance separates historical retention from prompt injection. Memory is injected only when it is `active` and meets `EVOLVA_MEMORY_CONTEXT_MIN_CONFIDENCE`; `draft`, `quarantined`, and `rolled_back` items remain auditable but do not influence agent behavior. Skills are injected only when their manifest status is `active`; `draft`, `disabled`, `deprecated`, and `quarantined` skills remain traceable but are not selected automatically. Governance tools include `memory_status`, `memory_audit`, `skill_status`, and `skill_audit`.

Repo Index builds persist a file manifest, chunk counts, reused-file counts, and skipped-file reasons. Search checks the manifest for staleness, rebuilds only changed files, and reuses unchanged chunks. Runtime artifact directories such as `.evolva/`, legacy `evolva/*` state, and test runtime layouts are ignored so Trace, Memory, and Policy audit writes do not invalidate code search.

Multi-agent is a governed role-collaboration layer, not an unbounded autonomous cluster. `delegate_agent` / `collaborate` validate roles, de-duplicate roles, respect `EVOLVA_MULTI_AGENT_MAX_ROLES`, and return structured reports with `run_id`, per-role status, latency, fallback, error details, and `tool_calls`. Sub-agents can call tools from their role allowlist, but every call goes through the main agent's Policy / approval / Sandbox / Trace path. Defaults are intentionally conservative: planner can inspect status, memory, and todos; researcher can read files and search the repo index; coder and reviewer can read/search plus run governed `python_exec`. `EVOLVA_MULTI_AGENT_TOOL_STEPS` controls per-role tool steps. File writes, shell, MCP calls, and recursive delegation are not in the default sub-agent scope. Failed LLM calls degrade to local fallback output and emit `multi_agent.run`, `multi_agent.role`, and `multi_agent.fallback` metrics.

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
- **Sandbox backend**: local workspace execution is the default; Docker backend can enforce network, read-only root, CPU, memory, and pids limits.
- **Writable roots**: set `EVOLVA_SANDBOX_WRITABLE_ROOTS` to narrow writable paths, for example to only allow `.evolva/workspace`.
- **Failure rollback**: failed shell / Python executions roll back files under snapshot roots. Tune with `EVOLVA_SANDBOX_SNAPSHOT_ROOTS` and `EVOLVA_SANDBOX_MAX_SNAPSHOT_BYTES`.
- **Dangerous command denylist**: blocks patterns such as `rm -rf /`, `git reset --hard`, `mkfs`, and `shutdown`.
- **Policy engine**: scores shell / Python, network, path, and secret-pattern risks. Set `EVOLVA_POLICY_FILE` to load profile rules, denied capabilities, and command denylists.
- **Policy audit**: decisions are written to `policy/audit.jsonl` under runtime home, by default `.evolva/policy/audit.jsonl`, so tool allow/deny/confirmation decisions are reviewable.
- **Confirmation gate**: shell, Python, and MCP tools can require approval unless `--yes` is set.
- **Trace audit**: decisions, tool calls, failures, and final answers are persisted for review.

## Development

Evolva checks can be wired into CI to protect the Trace / Eval / Self-Evolution regression baseline.

Security evals verify policy audit rows, MCP timeout metrics, sandbox rollback metrics, and secret redaction so production safety signals remain regression-tested.

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
