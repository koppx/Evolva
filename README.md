<p align="center">
  <img src="assets/evolva-poster.jpeg" alt="Evolva poster - Local Self-Evolving Agent Harness" width="680" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>Production-grade · Local-first · Self-Evolving Agent Harness</strong><br />
  面向真实工程场景的 Agent 运行底座：把仓库理解、工具执行、Trace 回放、Eval 基准、Guardrails 与自我进化收敛到一个可审计的闭环。
</p>

<p align="center">
  <a href="README.en.md">English</a> · <a href="#快速开始">快速开始</a> · <a href="#核心能力">核心能力</a> · <a href="#自我进化从运行证据到能力资产">自我进化</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="TUI-first" src="https://img.shields.io/badge/TUI--first-Workbench-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

## 为什么是 Evolva

Evolva 不是停留在对话层的 Agent Shell，而是一个面向工程化 Agent 的 **local-first harness**。它关注的不是“单次回答有多聪明”，而是 Agent 在真实仓库中如何稳定理解上下文、调用工具、留下证据、通过评测，并把失败转化为下一次执行的能力增益。

它的核心闭环是：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

这意味着 Evolva 每次执行都不只是产生结果，还会留下可追踪的运行记录、可复现的 Eval 依据和可沉淀的经验资产。它更像一套开放的 Agent 控制平面：透明、可扩展、可审计，并且默认服务于长期演进。

## 定位

Evolva 的定位是一个可组合、可观测、可持续演进的 Agent Harness。它把工程 Agent 的关键能力拆成清晰模块，让开发者可以在本地理解、扩展和验证每一次推理与执行：

- **Repo-aware**：通过仓库索引、上下文、记忆和 Skill 建立可检索的工程上下文。
- **Traceable**：每次工具调用、策略决策、失败信息和最终输出都进入 Trace，便于回放与审计。
- **Evaluable**：JSONL Eval Harness 把 Agent 行为变成可回归的测试资产。
- **Self-improving**：从反馈、Trace 模式和 Eval 失败样本中提炼 lesson，再进入长期记忆与 Skill。
- **Local-first**：默认在本地文件系统和沙箱中运行，核心能力不绑定云服务。

## 快速开始

Evolva 的主入口是一个本地 TUI 工作台。安装后直接运行 `evolva`，进入同一个界面完成对话、工具调用、MCP 接入、Trace 查看、模型切换、Workflow 编排和自我进化。

```bash
git clone git@github.com:koppx/Evolva.git
cd Evolva
python3 -m pip install -e ".[dev]"

# 可选：任意 OpenAI-compatible endpoint
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"

# 默认进入 TUI 工作台
evolva
```

进入 TUI 后，直接使用 Slash Commands：

```text
/model gpt-4o-mini                      # 切换模型
/repo build                             # 构建仓库索引
/repo search SelfEvolutionEngine        # 搜索代码符号/片段
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .
/mcp tools filesystem                   # 查看 MCP tools
/trace list                             # 查看最近运行
/dream --min-confidence 0.8             # 离线反思与防漂移分析
/evolve audit                           # 查看自进化覆盖
```

保留少量脚本化入口用于 CI、自动化和一次性任务：

```bash
evolva ask "分析当前仓库并给出可验证的优化计划"
evolva eval evals/tasks/smoke.jsonl --yes
evolva dream --json
```

未配置 `OPENAI_API_KEY` 时，Evolva 会进入有限规则模式；本地工具、记忆、技能、Todo、Trace、Workflow、Eval 等基础能力仍可离线运行，便于测试与二次开发。

## 核心能力

Evolva 的能力不是孤立模块，而是围绕“可执行、可观测、可评测、可进化”的闭环设计。

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| **LangGraph Runtime** | 显式 `StateGraph` 节点：`prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **TUI Workbench** | 默认产品入口，集成对话、工具日志、Trace、模型切换、MCP、Workflow 与自我进化 | `evolva` |
| **Tools** | 文件、Shell、Python、Web、Todo、Memory、Context、Policy、MCP、多 Agent 委派 | `/tools` / `/run` |
| **Repo Index** | 本地语义仓库索引，按符号、引用、路径和代码片段检索 | `/repo build` / `/repo search` |
| **Memory / Skills** | 长期记忆、偏好、经验教训、Markdown playbook | `/memory` / `/skills` |
| **MCP** | 在 TUI 内通过 `/mcp add` 接入 stdio MCP server，并用 `/mcp tools` / `mcp_call` 调用 | `/mcp` |
| **Workflow** | JSON 工作流编排 role agent、agent call、tool node，TUI 内直接 `/workflow <json>` | `/workflow` |
| **Trace / Replay** | 记录 prompt、工具调用、policy 决策、耗时、错误与输出，TUI 内查看上下文 | `/trace` |
| **Eval Harness** | JSONL 任务集，覆盖文本、正则、产物、记忆、上下文和工具错误，适合 CI/回归 | `evolva eval ...` |
| **Guardrails / Sandbox** | 路径沙箱、危险命令拦截、风险分级、secret 检测、确认门禁 | `/policy` |
| **Self-Evolution** | 从反馈、Trace、Eval 失败中提炼 lesson，并写入 Memory / Skill | `/evolve` / `/dream` |
| **Dreaming** | 本地后台反思循环：Evidence → Hypothesis → Critique → Action，生成可审计报告并可选择性沉淀高置信经验 | `/dream` |

## 架构总览

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva architecture" width="100%" />
</p>

Evolva 的架构围绕三条主线展开：

1. **Reasoning & State**：TUI Workbench 是默认产品入口；脚本化 CLI 作为自动化通道进入 Evolva Core，由 LangGraph `StateGraph` 管理运行状态，并统一装配 Memory、Skills、Todo、Context 与 Repo Index。
2. **Guarded Execution**：工具调用先经过 Policy 与 Sandbox，再访问文件、Shell、Python、Web、MCP、Workflow 与 Sub Agents，默认保留风险决策与执行证据。
3. **Feedback Loop**：Trace 记录行为，Eval 检查回归，Self-Evolution 将反馈、失败模式和高价值经验沉淀为长期记忆与可复用 Skill。

## 自我进化：从运行证据到能力资产

Evolva 的自我进化不是一句宣传语，而是一条可检查、可回放、可审计的状态更新链路：

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

TUI 内示例：

```text
/evolve audit
/evolve 以后写 Python 文件后自动运行语法检查和 pytest
/evolve trace
/evolve apply-trace
/evolve apply-eval
/dream
/dream apply --min-confidence 0.8
```

它会把反馈或失败模式提炼成带 **category / confidence / evidence / fingerprint** 的 lesson，写入长期记忆，并可生成 Markdown Skill，让后续任务自动带上这些经验。`evolve audit` 会汇总 lesson 覆盖、已进化技能、Trace/Eval 待处理 proposal 和下一步建议，避免自我进化变成不可控的 prompt 堆叠。

`dream` 是 Evolva 的本地 Dreaming 循环：它借鉴“后台反思/离线复盘”这类公开可观察的 Agent 工作流，但实现完全 local-first，不依赖云端或额外 LLM。它会扫描最近 Trace、最新 Eval 报告和当前 Memory/Skill 覆盖，执行 **Evidence → Hypothesis → Critique → Action**：先收集证据，再生成可证伪假设，随后用确定性的 drift guard 拒绝低置信、重复或缺少证据的建议，最后写入 `evolva/dreams/*.json` 审计报告；加上 `--apply` 后，只把通过质量门的高置信 proposal 写入 Memory / Skill。

## TUI 工作台入口

Evolva 的日常使用围绕 TUI 内的 Slash Commands 展开，避免把用户暴露在一堆 `python3 -m ...` 子命令里。命令行子命令保留给自动化、CI 和脚本集成。

```bash
# 产品主入口
evolva

# 如果只想使用传统行式交互
evolva --chat
```

TUI 内常用路径：

```text
/model [name]                         查看/切换模型
/repo build                           构建仓库索引
/repo search <query>                  搜索代码符号、引用和片段
/mcp                                  查看已接入的 MCP server
/mcp add <name> <command> [args...]   接入一个 stdio MCP server
/mcp tools [server]                   查看 MCP tools
/run mcp_call {"server":"...","tool":"...","arguments":{}}
/trace list                           查看最近运行
/trace context latest                 查看最新上下文/Prompt 事件
/workflow <json>                      运行 workflow spec
/evolve audit                         查看自进化覆盖
/dream --min-confidence 0.8           运行 Dreaming 防漂移分析
```

脚本化/CI 入口仅用于自动化与回归基线：

```bash
evolva ask "分析当前仓库并给出可验证的优化计划"
evolva eval evals/tasks/smoke.jsonl --yes
evolva dream --json
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
/trace context <run_id>   查看 trace 中的上下文/Prompt 事件
/model [name]              查看或切换当前模型
/policy                   查看 guardrail 策略
/repo build               构建本地仓库索引
/repo search <query>      搜索代码符号、引用和片段
/mcp                      查看 MCP servers
/mcp add <name> <cmd...>  接入 stdio MCP server
/mcp remove <name>        移除 MCP server 配置
/mcp tools [server]       查看 MCP tools
/image <path|url> [text]  对图片提问
/evolve [feedback]        基于反馈自我进化
/dream                    运行离线 Dreaming 反思报告
/dream --min-confidence n  调整 drift-guard 置信阈值
/dream apply              应用高置信 Dreaming 建议
/workflow <json>          运行 workflow spec
/run <tool> <json>        直接调用工具
/exit                     退出
```

</details>

## Workflow 编排

```json
{
  "id": "verified_python_task",
  "nodes": [
    {"id": "plan", "type": "role", "role": "planner", "task": "规划一个可验证的 Python 工程任务"},
    {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/verified_task.py", "content": "print('hello from Evolva')\n"}},
    {"id": "run", "type": "tool", "tool": "shell", "args": {"command": "python3 evolva/workspace/verified_task.py"}}
  ]
}
```

## Eval Harness

```json
{"id":"tool_write_read_001","input":"创建 hello.py 并运行","expected_artifacts":["evolva/workspace/hello.py"],"expected_contains":["hello"],"scorers":["no_tool_error"]}
```

支持 `expected_contains`、`forbidden_contains`、`expected_regex`、`expected_artifacts`、`expected_memory`、`expected_context`、`max_duration_ms`、`no_tool_error` 等检查项。

## TUI 工作台预览

<p align="center">
  <img src="assets/tui-mockup.svg" alt="Evolva TUI mockup" width="100%" />
</p>

TUI 支持常见工作台快捷键：

| 快捷键 | 作用 |
| --- | --- |
| `F2` | 准备 `/model` 命令，快速切换模型 |
| `Ctrl+R` | 查看最近 Trace |
| `Ctrl+X` | 查看最新 Trace 的上下文 / Prompt 事件 |
| `Ctrl+T` | 显示 / 隐藏工具日志面板 |
| `PgUp` / `PgDn` | 滚动聊天窗口 |
| `Tab` | 补全常用 Slash Command |

## Workflow / MCP / Memory 闭环

<p align="center">
  <img src="assets/workflow-mcp-memory.svg" alt="Evolva workflow MCP memory" width="100%" />
</p>

## 安全与可审计执行

Evolva 是本地优先的 Agent，具备文件、Shell 和 Python 执行能力，因此把安全边界作为运行时的一等公民：

- **Sandbox root**：文件工具统一通过 workspace sandbox 解析路径，阻止路径逃逸。
- **Dangerous command denylist**：拦截 `rm -rf /`、`git reset --hard`、`mkfs`、`shutdown` 等高危片段。
- **Policy engine**：对 Shell / Python、网络、路径、secret pattern 进行风险分级。
- **Confirmation gate**：非 `--yes` 模式下，Shell / Python / MCP 等高风险工具需要确认。
- **Trace audit**：关键决策、工具调用、失败信息和最终回答都会进入 trace，便于审计和复盘。

## 质量基线

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
```

## 工程结构

```text
evolva/
  cli.py                     `evolva` console 入口，默认启动 TUI
  tui.py                     TUI 工作台
  agent/core.py              Agent 对外门面
  agent/langgraph_runtime.py LangGraph StateGraph 运行时
  agent/evolution.py         lesson + skill 自进化引擎
  agent/evolution_analyzer.py Trace / Eval 进化分析器
  agent/dream.py             离线 Dream 反思循环
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
  <strong>Evolva</strong> · Local-first, inspectable, self-evolving Agent Harness.<br />
  如果你也在构建可评测、可回放、可进化的 Agent 系统，欢迎 Star：<strong>koppx/Evolva</strong>
</p>
