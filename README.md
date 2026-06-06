<p align="center">
  <img src="assets/evolva-poster.jpeg" alt="Evolva poster - Local Self-Evolving Agent Harness" width="680" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>本地优先的 Self-Evolving Agent Harness</strong><br />
  用一个小而完整的项目，拆开 Agent 工程里的运行时、工具、记忆、评测、观测、安全与进化闭环。
</p>

<p align="center">
  <a href="README.en.md">English</a> · <a href="#快速开始">快速开始</a> · <a href="#能力地图">能力地图</a> · <a href="#自我进化">自我进化</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="CLI/TUI" src="https://img.shields.io/badge/CLI%20%2F%20TUI-Ready-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

## 为什么是 Evolva

很多 Agent 示例停留在 chatbot demo：能对话，但看不清工程上如何组织上下文、如何接工具、如何做 Trace / Eval、如何加安全边界，更看不到失败后如何沉淀经验。

**Evolva** 把这些能力压缩到一个可读、可跑、可测试的本地项目里：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

你可以把它当成一个 Agent Harness 学习样板，也可以直接在它之上扩展自己的本地 Agent 框架。

## 快速开始

```bash
git clone git@github.com:koppx/Evolva.git
cd Evolva
python3 -m pip install -e ".[dev]"

# 可选：任意 OpenAI-compatible endpoint
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"

python3 -m evolva.cli chat
```

更多入口：

```bash
# 终端 UI
python3 -m evolva.cli tui

# 单次提问
python3 -m evolva.cli ask "记住：写完 Python 后运行测试"

# 图片输入
python3 -m evolva.cli ask "描述这张图" --image evolva/workspace/example.png
```

未配置 `OPENAI_API_KEY` 时，Evolva 会进入有限规则模式；本地工具、记忆、技能、Todo、Trace、Workflow、Eval 等能力仍可使用。

## 能力地图

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| **LangGraph Runtime** | 显式 `StateGraph` 节点：`prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **CLI / TUI** | 交互对话、单次 ask、curses TUI | `python3 -m evolva.cli chat` / `tui` |
| **Tools** | 文件、Shell、Python、Web、Todo、Memory、Context、Policy、MCP、多 Agent 委派 | `/tools` / `/run` |
| **Repo Index** | 本地语义仓库索引，按符号、引用、路径和代码片段检索 | `/repo build` / `/repo search` |
| **Memory / Skills** | 长期记忆、偏好、经验教训、Markdown playbook | `/memory` / `/skills` |
| **MCP** | stdio MCP client，连接外部工具服务 | `python3 -m evolva.cli mcp ...` |
| **Workflow** | JSON 工作流编排 role agent、agent call、tool node | `python3 -m evolva.cli workflow ...` |
| **Trace / Replay** | 记录 prompt、工具调用、policy 决策、耗时、错误与输出 | `python3 -m evolva.cli trace ...` |
| **Eval Harness** | JSONL 任务集，覆盖文本、正则、产物、记忆、上下文和工具错误 | `python3 -m evolva.cli eval ...` |
| **Guardrails / Sandbox** | 路径沙箱、危险命令拦截、风险分级、secret 检测、确认门禁 | `/policy` |
| **Self-Evolution** | 从反馈、Trace、Eval 失败中提炼 lesson，并写入 Memory / Skill | `python3 -m evolva.cli evolve ...` |

## 架构

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva architecture" width="100%" />
</p>

Evolva 的结构可以按三条线理解：

1. **Reasoning & State**：CLI / TUI 进入 Evolva Core，由 LangGraph runtime 组织推理状态，并装配 Memory、Skills、Todo、Context。
2. **Guarded Execution**：工具调用先经过 Policy 和 Sandbox，再访问文件、Shell、Python、Web、MCP、Workflow 与 Sub Agents。
3. **Feedback Loop**：Trace 记录行为，Eval 检查回归，Evolution 将反馈和失败沉淀为长期记忆与技能。

## 自我进化

Evolva 的自我进化不是一句宣传语，而是可检查的状态更新链路：

```text
Feedback / Trace Pattern / Eval Failure
        ↓
Reflection
        ↓
Long-term Memory
        ↓
Markdown Skill
        ↓
Future Prompt Context
```

示例：

```bash
python3 -m evolva.cli evolve audit --show-proposals
python3 -m evolva.cli evolve feedback "以后写 Python 文件后自动运行语法检查和 pytest"
python3 -m evolva.cli evolve trace --apply
python3 -m evolva.cli evolve eval --apply
```

它会把反馈或失败模式提炼成带 **category / confidence / evidence / fingerprint** 的 lesson，写入长期记忆，并可生成 Markdown Skill，让后续任务自动带上这些经验。`evolve audit` 会汇总当前 lesson 覆盖、已进化技能、Trace/Eval 待处理 proposal 和下一步建议。

## 常用命令

```bash
# Chat / TUI / Ask
python3 -m evolva.cli chat
python3 -m evolva.cli tui
python3 -m evolva.cli ask "规划一个本地 Agent demo"

# Trace
python3 -m evolva.cli trace list
python3 -m evolva.cli trace show <run_id>
python3 -m evolva.cli trace replay <run_id>

# Eval
python3 -m evolva.cli eval evals/tasks/smoke.jsonl --yes

# Workflow
python3 -m evolva.cli workflow path/to/workflow.json --yes

# Repo Index
# 交互模式下：/repo build，然后 /repo search SelfEvolutionEngine evolve
python3 -m evolva.cli chat

# MCP
python3 -m evolva.cli mcp servers
python3 -m evolva.cli mcp tools filesystem
python3 -m evolva.cli mcp call filesystem list_directory '{"path":"."}' --yes

# Self-evolution
python3 -m evolva.cli evolve status
python3 -m evolva.cli evolve audit --show-proposals
python3 -m evolva.cli evolve trace --apply
python3 -m evolva.cli evolve eval --apply
```

<details>
<summary><strong>交互式 Slash Commands</strong></summary>

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
/repo build               构建本地仓库索引
/repo search <query>      搜索代码符号、引用和片段
/mcp                      查看 MCP servers
/mcp tools [server]       查看 MCP tools
/image <path|url> [text]  对图片提问
/evolve [feedback]        基于反馈自我进化
/workflow <json>          运行 workflow spec
/run <tool> <json>        直接调用工具
/exit                     退出
```

</details>

## Workflow 示例

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

## Eval 示例

```json
{"id":"tool_write_read_001","input":"创建 hello.py 并运行","expected_artifacts":["evolva/workspace/hello.py"],"expected_contains":["hello"],"scorers":["no_tool_error"]}
```

支持 `expected_contains`、`forbidden_contains`、`expected_regex`、`expected_artifacts`、`expected_memory`、`expected_context`、`max_duration_ms`、`no_tool_error` 等检查项。

## TUI 预览

<p align="center">
  <img src="assets/tui-mockup.svg" alt="Evolva TUI mockup" width="100%" />
</p>

## Workflow / MCP / Memory

<p align="center">
  <img src="assets/workflow-mcp-memory.svg" alt="Evolva workflow MCP memory" width="100%" />
</p>

## 安全模型

Evolva 是本地优先的 Agent，具备文件、Shell 和 Python 执行能力，因此默认提供多层安全边界：

- **Sandbox root**：文件工具统一通过 workspace sandbox 解析路径，阻止路径逃逸。
- **Dangerous command denylist**：拦截 `rm -rf /`、`git reset --hard`、`mkfs`、`shutdown` 等高危片段。
- **Policy engine**：对 Shell / Python、网络、路径、secret pattern 进行风险分级。
- **Confirmation gate**：非 `--yes` 模式下，Shell / Python / MCP 等高风险工具需要确认。
- **Trace audit**：关键决策、工具调用、失败信息和最终回答都会进入 trace，便于审计和复盘。

## 开发与测试

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
```

## 项目结构

```text
evolva/
  cli.py                     CLI 入口
  tui.py                     curses 终端 UI
  agent/core.py              Agent 对外门面
  agent/langgraph_runtime.py LangGraph StateGraph 运行时
  agent/evolution.py         lesson + skill 自进化引擎
  agent/evolution_analyzer.py Trace / Eval 进化分析器
  agent/images.py            本地/URL 图片输入
  agent/mcp.py               stdio MCP client
  agent/memory.py            长期记忆
  agent/policy.py            guardrails 与风险决策
  agent/sandbox.py           workspace sandbox 与执行
  tools/builtin.py           内置工具注册
  eval/harness.py            JSONL eval runner
  workflow/engine.py         workflow DAG engine
assets/
  evolva-poster.jpeg        README 顶部海报
  architecture.svg
  tui-mockup.svg
  workflow-mcp-memory.svg
```

---

<p align="center">
  <strong>Evolva</strong> · Local, inspectable, self-evolving agents.<br />
  如果这个项目对你有帮助，欢迎 Star：<strong>koppx/Evolva</strong>
</p>
