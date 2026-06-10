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
  <a href="https://github.com/koppx/Evolva/stargazers">
    <img alt="GitHub stars" src="https://img.shields.io/github/stars/koppx/Evolva?style=for-the-badge&logo=github&label=Stars&color=EAD58B&labelColor=0B0B0F" />
  </a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="TUI-first" src="https://img.shields.io/badge/TUI--first-Workbench-EAD58B?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-9F7A30?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
</p>

---

## 为什么是 Evolva

Evolva 是面向工程化 Agent 的 **local-first harness**：围绕真实仓库中的上下文组织、工具执行、证据留存、回归评测和能力沉淀，提供一套可落地的本地 Agent 运行底座。

它的核心闭环是：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

在 Evolva 中，每次执行都会生成可追踪的运行记录、可复现的 Eval 依据和可沉淀的经验资产。它是一套开放的 Agent 控制平面：透明、可扩展、可审计，并且默认服务于长期演进。

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
/repo search evolution                  # 搜索代码符号/片段
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .
/mcp tools filesystem                   # 查看 MCP tools
/trace list                             # 查看最近运行
/dream --min-confidence 0.8             # 运行 Dreaming 质量门分析
/evolve audit                           # 查看自进化覆盖
```

即使暂未配置 `OPENAI_API_KEY`，Evolva 仍可先以本地模式运行工具、记忆、技能、Todo、Trace、Workflow、Eval 等基础能力，便于本地验证与扩展。

## 核心能力

Evolva 的能力围绕“可执行、可观测、可评测、可进化”的闭环组织。

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| **LangGraph Runtime** | 显式 `StateGraph` 节点：`prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **TUI Workbench** | 默认产品入口，集成对话、工具日志、Trace、模型切换、MCP、Workflow 与自我进化 | `evolva` |
| **Tools** | 文件、Shell、Python、Web、Todo、Memory、Context、Policy、MCP、多 Agent 委派 | `/tools` / `/run` |
| **Repo Index** | 本地语义仓库索引，按符号、引用、路径和代码片段检索 | `/repo build` / `/repo search` |
| **Memory / Skills** | 带 evidence / status / version 的长期记忆，以及带 manifest trigger 的 Markdown playbook | `/memory` / `/skills` |
| **MCP** | 在 TUI 内通过 `/mcp add` 接入 stdio MCP server，并用 `/mcp tools` / `mcp_call` 调用 | `/mcp` |
| **Workflow** | JSON DAG 编排 role agent、agent call、tool node，支持依赖声明、循环检测与错误门控 | `/workflow` |
| **Trace / Replay** | 记录 prompt、工具调用、policy 决策、耗时、错误与输出，TUI 内查看上下文 | `/trace` |
| **Eval Harness** | JSONL 任务集 + baseline gate，覆盖文本、正则、产物、记忆、上下文和工具错误，适合 CI/回归 | CI / Regression |
| **Guardrails / Sandbox** | 路径沙箱、backend 抽象、危险命令拦截、风险分级、secret 检测、确认门禁 | `/policy` |
| **Self-Evolution** | 从反馈、Trace、Eval 失败中提炼 lesson，并写入 Memory / Skill | `/evolve` / `/dream` |
| **Dreaming** | 本地自进化研究循环：Evidence → Hypothesis → Candidate → Verifier → Promotion，生成可审计报告与候选改进 Backlog | `/dream` |

## 架构总览

<p align="center">
  <img src="assets/architecture.svg" alt="Evolva architecture" width="100%" />
</p>

Evolva 的架构围绕三条主线展开：

1. **Reasoning & State**：TUI Workbench 是默认产品入口；Evolva Core 由 LangGraph `StateGraph` 管理运行状态，并统一装配 Memory、Skills、Todo、Context 与 Repo Index。
2. **Guarded Execution**：工具调用先经过 Policy 与 Sandbox，再访问文件、Shell、Python、Web、MCP、Workflow 与 Sub Agents，默认保留风险决策与执行证据。
3. **Feedback Loop**：Trace 记录行为，Eval 检查回归，Self-Evolution 将反馈、失败模式和高价值经验沉淀为长期记忆与可复用 Skill。

## 自我进化：从运行证据到能力资产

<p align="center">
  <img src="assets/evolva-dreaming-loop.jpeg" alt="Evolva Dreaming Loop" width="100%" />
</p>

Evolva 的自我进化是一条可检查、可回放、可审计的状态更新链路：

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
Staged Promotion
        ↓
Long-term Memory / Markdown Skill
```

TUI 内示例：

```text
/evolve audit
/evolve 以后写 Python 文件后自动运行语法检查和 pytest
/evolve trace
/evolve apply-trace
/evolve apply-eval
/dream
/dream backlog
/dream apply --min-confidence 0.8
```

它会把反馈或失败模式提炼成带 **category / confidence / evidence / fingerprint** 的 lesson，写入长期记忆，并可生成 Markdown Skill，让后续任务自动带上这些经验。`evolve audit` 会汇总 lesson 覆盖、已进化技能、Trace/Eval 待处理 proposal 和下一步建议，避免自我进化变成不可控的 prompt 堆叠。

`dream` 是 Evolva 的本地自进化研究循环：它会扫描最近 Trace、最新 Eval 报告和当前 Memory/Skill 覆盖，执行 **Evidence → Hypothesis → Candidate → Verifier → Promotion**。流程会先收集证据，再生成可证伪假设；通过 drift guard 后的假设会进入 `DreamCandidate`，携带 affected surfaces、risk、proposed change 和 verifier，并写入 `evolva/dreams/backlog.json` 形成候选改进池。加上 `apply` 后，Evolva 只会把通过质量门的高置信候选分阶段沉淀为 Memory / Skill，后续仍可通过 `/dream verify` 调用 Eval 或 Trace verifier 做回归确认，并把通过验证的候选推进为 verified/promoted。

## TUI 工作台入口

Evolva 的日常使用围绕 TUI Workbench 展开：对话、工具调用、MCP 接入、Trace 检索、模型切换、Workflow 编排和自我进化都收敛在同一套 Slash Commands 中。

```bash
evolva
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
/dream --min-confidence 0.8           运行 Dreaming 质量门分析
/dream backlog                        查看候选改进 Backlog
/dream verify                         运行候选改进 Verifier
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
/dream                    运行 Dreaming 质量门报告
/dream backlog            查看候选改进 Backlog
/dream verify             运行候选改进 Verifier
/dream --min-confidence n  调整 drift-guard 置信阈值
/dream apply              应用高置信 Dreaming 建议
/workflow <json>          运行 workflow spec
/run <tool> <json>        直接调用工具
/exit                     退出
```

</details>

## Workflow 编排

Workflow 支持显式 `depends_on`，可以描述真正的 DAG；未声明依赖的旧规格仍按顺序执行，便于兼容已有工作流。执行前会检查重复节点、缺失依赖和循环依赖，执行结果会进入 Context 与 Trace，作为后续 Eval / Dream 的证据来源。

```json
{
  "id": "evolution_audit_flow",
  "nodes": [
    {"id": "repo", "depends_on": [], "type": "tool", "tool": "repo_index_search", "args": {"query": "SelfEvolutionEngine DreamEngine"}},
    {"id": "policy", "depends_on": [], "type": "tool", "tool": "policy_info", "args": {}},
    {"id": "review", "depends_on": ["repo", "policy"], "type": "role", "role": "reviewer", "task": "基于 {{repo}} 和 {{policy}} 评审当前自我进化安全边界"}
  ]
}
```

## Eval Harness

Eval Harness 不只是跑一次任务，而是把 Agent 行为固化为可回归的质量基线。CI 会运行单元测试、语法检查和 JSONL eval，并用 baseline gate 拦截分数下降、任务缺失和通过项回退。

```bash
evolva eval evals/tasks/smoke.jsonl --yes \
  --baseline evals/baselines/smoke.json \
  --min-score 1.0 \
  --no-regression
```

JSONL 任务支持 `expected_contains`、`forbidden_contains`、`expected_regex`、`expected_artifacts`、`expected_memory`、`expected_context`、`max_duration_ms`、`no_tool_error` 等检查项。baseline 位于 `evals/baselines/`，CI 配置位于 `.github/workflows/ci.yml`。

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
- **Sandbox backend**：执行层通过 backend 接口隔离，默认本地 workspace backend，后续可扩展到更强隔离实现。
- **Dangerous command denylist**：拦截 `rm -rf /`、`git reset --hard`、`mkfs`、`shutdown` 等高危片段。
- **Policy engine**：对 Shell / Python、网络、路径、secret pattern 进行风险分级。
- **Confirmation gate**：非 `--yes` 模式下，Shell / Python / MCP 等高风险工具需要确认。
- **Trace audit**：关键决策、工具调用、失败信息和最终回答都会进入 trace，便于审计和复盘。

## 质量基线

Evolva 的评测与工程检查已经按照 CI 质量门组织，用于守住 Trace / Eval / Self-Evolution 的回归基线。

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall evolva tests
python3 -m pytest -q
evolva eval evals/tasks/smoke.jsonl --yes --baseline evals/baselines/smoke.json --min-score 1.0 --no-regression
evolva eval evals/tasks/repo_index.jsonl --yes --baseline evals/baselines/repo_index.json --min-score 1.0 --no-regression
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
  agent/memory.py            带 evidence/status/version 的长期记忆
  agent/policy.py            guardrails 与风险决策
  agent/sandbox.py           workspace sandbox 与 backend 执行抽象
  tools/builtin.py           内置工具注册
  eval/harness.py            JSONL eval runner
  workflow/engine.py         workflow DAG engine
evals/
  baselines/                 Eval-as-CI 回归基线
.github/workflows/ci.yml     单测 + Eval gate
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
