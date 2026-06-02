<p align="center">
  <img src="assets/readme-banner.svg" alt="Evolva banner" width="100%" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>Local Self-Evolving Agent Harness</strong><br />
  Build agents that remember, execute, inspect, evaluate, and evolve.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Agent" src="https://img.shields.io/badge/Agent-Harness-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="TUI" src="https://img.shields.io/badge/TUI-Ready-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

**Evolva** 是一个面向本地开发和 Agent 工程学习的 Agent Harness。它不只是一个 chatbot，而是把一个可落地 Agent 需要的执行链路拆成清晰模块：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

它内置 CLI / TUI、工具调用、长期记忆、Skills、MCP、Workflow、Trace、Eval、Guardrails、Sandbox、多 Agent 和自我进化机制，适合作为 Agent Harness 的学习样板和二次开发基础。

## Why Evolva

| Focus | What you get |
| --- | --- |
| **Agent Runtime** | 对话入口、上下文组装、工具选择、执行反馈和最终回答 |
| **State & Memory** | facts / preferences / lessons / context / todo 的持久化管理 |
| **Tooling Layer** | 文件、shell、Python、web、MCP、workflow 和多 Agent 编排 |
| **Engineering Loop** | trace 观测、eval 回归、policy 防护、失败反思和 skill 沉淀 |

## Quick Start

```bash
git clone git@github.com:koppx/Evolva.git
cd Evolva
python3 -m pip install -e ".[dev]"

# Optional: any OpenAI-compatible endpoint
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"

python3 -m evolva.cli chat
```

启动 TUI：

```bash
python3 -m evolva.cli tui
```

未配置 `OPENAI_API_KEY` 时，Evolva 会进入有限规则模式，仍可使用本地命令、记忆、技能、todo、trace、workflow 和工具调用。

## Architecture

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva agent architecture" width="100%" />
</p>

架构按三条主线组织：

1. **Reasoning & State**：CLI / TUI 进入 Evolva Core，Core 统一装配 Memory、Skills、Todo 和 Context。
2. **Guarded Execution**：所有执行能力经过 `Policy -> Sandbox -> Tools`，再扩展到 MCP、Workflow 和 Sub Agents。
3. **Feedback Loop**：Trace 记录过程，Eval 做回归检查，Evolution 将反馈沉淀为长期记忆和可复用技能。

## Capabilities

| Module | Capability |
| --- | --- |
| **CLI / TUI / Ask** | 交互式对话、终端 UI、单次提问 |
| **Image Input** | 支持 `--image` 和 `/image`，可接入视觉模型 |
| **Tools** | 文件、shell、Python、web、todo 等内置工具 |
| **Memory** | 长期记忆、偏好、经验、上下文持久化 |
| **Skills** | Markdown playbook，沉淀可复用执行经验 |
| **MCP** | stdio MCP client，接入外部工具生态 |
| **Workflow** | JSON 工作流，组合 agent / role / tool 节点 |
| **Trace** | 记录 prompt、policy、tool call、latency、final answer |
| **Eval** | JSONL 任务集，支持文本、正则、artifact、memory、context 等检查 |
| **Guardrails** | Policy、Sandbox、危险命令拦截、secret pattern 检测、确认机制 |
| **Self-Evolution** | 从反馈、失败、trace、eval 中提炼 lesson，并更新 Memory / Skills |

## Daily Usage

```bash
# Chat / TUI / one-shot ask
python3 -m evolva.cli chat
python3 -m evolva.cli tui
python3 -m evolva.cli ask "记住：写完 Python 后运行测试"
python3 -m evolva.cli ask "请描述这张图" --image evolva/workspace/example.png

# Trace / Eval / Workflow
python3 -m evolva.cli trace list
python3 -m evolva.cli eval evals/tasks/smoke.jsonl --yes
python3 -m evolva.cli workflow path/to/workflow.json --yes

# MCP
python3 -m evolva.cli mcp servers
python3 -m evolva.cli mcp tools filesystem
python3 -m evolva.cli mcp call filesystem list_directory '{"path":"."}' --yes

# Self-evolution
python3 -m evolva.cli evolve status
python3 -m evolva.cli evolve trace --apply
python3 -m evolva.cli evolve eval
```

<details>
<summary><strong>Interactive slash commands</strong></summary>

```text
/help                     查看帮助
/tools                    列出工具
/skills                   列出技能
/memory [query]           查看或搜索长期记忆
/memory stats             查看记忆统计
/memory recent [n]        查看最近记忆
/context [query]          查看持久上下文
/todo                     查看 TodoList
/todo add <title>         添加 todo
/todo done <id>           标记 todo 完成
/agents                   列出多 agent 角色
/trace list               查看最近 trace
/trace show <run_id>      查看单次 trace
/policy                   查看 guardrail 策略
/mcp                      查看 MCP servers
/mcp tools [server]       查看 MCP tools
/image <path|url> [text]  对图片提问
/evolve [feedback]        基于反馈自我进化
/workflow <json>          运行 workflow spec
/run <tool> <json>        直接调用工具
/exit                     退出
```

</details>

## Self-Evolution

Evolva 的自我进化不是一句口号，而是由可检查的状态变化组成：

```text
Feedback / Failure / Eval Result
        ↓
Reflection
        ↓
Long-term Memory
        ↓
Markdown Skill
        ↓
Future Prompt Context
```

你可以在对话中直接反馈：

```text
/evolve 以后写 Python 文件后自动运行语法检查和 pytest
```

Evolva 会将反馈提炼为 lesson，并在后续任务中通过 Memory / Skills 重新注入上下文。

## Workflow Example

```json
{
  "id": "demo_workflow",
  "nodes": [
    {"id": "plan", "type": "role", "role": "planner", "task": "规划一个 Python demo"},
    {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/demo.py", "content": "print('hello from Evolva')\n"}},
    {"id": "run", "type": "tool", "tool": "shell", "args": {"command": "python3 evolva/workspace/demo.py"}}
  ]
}
```

## Eval Example

```json
{
  "id": "tool_write_read_001",
  "input": "创建 hello.py 并运行",
  "expected_artifacts": ["evolva/workspace/hello.py"],
  "expected_contains": ["hello"],
  "scorers": ["no_tool_error"]
}
```

支持的检查项包括：`expected_contains`、`forbidden_contains`、`expected_regex`、`expected_artifacts`、`expected_memory`、`expected_context`、`max_duration_ms`、`no_tool_error`。

## TUI Preview

<p align="center">
  <img src="assets/tui-mockup.svg" alt="Evolva TUI mockup" width="100%" />
</p>

## Safety Model

Evolva 是本地 Agent，具备文件、shell 和 Python 执行能力，因此默认提供多层安全边界：

- **Sandbox root**：文件工具统一通过 sandbox 解析路径，阻止路径逃逸。
- **Dangerous command denylist**：拦截 `rm -rf /`、`git reset --hard`、`mkfs`、`shutdown` 等高危片段。
- **Policy engine**：对 shell / Python、网络、路径、secret pattern 进行风险分级。
- **Confirmation gate**：非 `--yes` 模式下，shell / Python / MCP 等高风险工具需要确认。
- **Trace audit**：关键决策、工具调用和失败信息都会进入 trace，便于审计和复盘。

## Development

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
```

## Project Structure

```text
evolva/
  cli.py                CLI / command entry
  tui.py                curses terminal UI
  agent/core.py         plan-act-observe-reflect loop
  agent/context.py      persistent context store
  agent/evolution.py    lesson + skill evolution engine
  agent/images.py       local/URL image input helpers
  agent/llm.py          OpenAI-compatible client
  agent/mcp.py          stdio MCP client
  agent/memory.py       long-term memory store
  agent/multi_agent.py  planner/researcher/coder/reviewer roles
  agent/policy.py       guardrails and risk decisions
  agent/sandbox.py      workspace sandbox and execution
  agent/skills.py       markdown skill library
  agent/todo.py         persistent todo list
  agent/tracing.py      trace record/show/replay
  tools/builtin.py      builtin tool registry
  eval/harness.py       JSONL eval runner
  workflow/engine.py    workflow DAG engine
assets/
  architecture.svg
  readme-banner.svg
  tui-mockup.svg
  workflow-mcp-memory.svg
```

---

<p align="center">
  <strong>Evolva</strong> · A compact harness for local, inspectable, self-evolving agents.
</p>
