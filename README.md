<p align="center">
  <img src="assets/evolva-poster.jpeg" alt="Evolva poster - Local Self-Evolving Agent Harness" width="680" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>Local-first · Traceable · Evaluable · Self-Evolving Agent Harness</strong><br />
  面向真实工程落地的 Agent Infra：统一仓库理解、工具执行、Loop 编排、Trace 回放、Eval 基准、Guardrails 与自我进化，形成可审计、可回归、可持续演进的运行闭环。
</p>

<p align="center">
  <a href="README.en.md">English</a> · <a href="#快速开始">快速开始</a> · <a href="#核心能力">核心能力</a> · <a href="#loop-engineering">Loop Engineering</a> · <a href="#自我进化从运行证据到能力资产">自我进化</a>
</p>

<p align="center">
  <a href="https://github.com/koppx/Evolva/stargazers">
    <img alt="GitHub stars" src="https://img.shields.io/github/stars/koppx/Evolva?style=for-the-badge&logo=github&label=Stars&color=EAD58B&labelColor=0B0B0F&cacheSeconds=1800" />
  </a>
  <img alt="Local First" src="https://img.shields.io/badge/Local--First-Agent%20Harness-2E8B57?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-FFF0B3?style=for-the-badge&labelColor=0B0B0F" />
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Runtime-D6A84F?style=for-the-badge&labelColor=0B0B0F" />
</p>

<p align="center">
  <img src="assets/tui-mockup.svg" alt="Evolva TUI Workbench preview" width="100%" />
</p>

<p align="center">
  <em>TUI-first Agent Workbench：模型配置、工具执行、Trace 上下文、MCP、Loop、Dreaming 都在同一个本地工作台内完成。</em>
</p>

---

## 为什么是 Evolva

Evolva 是面向工程化 Agent 的 **local-first harness**：围绕真实仓库中的上下文组织、工具执行、证据留存、回归评测和能力沉淀，提供一套可落地的本地 Agent 运行底座。

它的核心闭环是：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

在 Evolva 中，复杂任务不是一次性聊天，而是可重复运行、可设质量门、可回放复盘、可沉淀经验的 **Agent Loop**。每次执行都会生成可追踪的运行记录、可复现的 Eval 依据和可沉淀的经验资产。它是一套开放的 Agent 控制平面：透明、可扩展、可审计，并且默认服务于长期演进。

## 定位

Evolva 的定位是一个可组合、可观测、可持续演进的 Agent Harness。它把工程 Agent 的关键能力拆成清晰模块，让开发者可以在本地接入自己的模型、工具、评测数据与安全策略，并验证每一次推理与执行：

- **Repo-aware**：通过仓库索引、上下文、记忆和 Skill 建立可检索的工程上下文。
- **Traceable**：每次工具调用、策略决策、失败信息和最终输出都进入 Trace，便于回放与审计。
- **Evaluable**：JSONL Eval Harness 把 Agent 行为变成可回归的测试资产。
- **Self-improving**：从反馈、Trace 模式和 Eval 失败样本中提炼 lesson，再进入长期记忆与 Skill。
- **Local-first**：默认在本地文件系统和沙箱中运行，核心能力不绑定云服务。

## 快速开始

Evolva 的主入口是一个本地 TUI 工作台。安装后直接运行 `evolva`，进入同一个界面完成对话、工具调用、MCP 接入、Trace 查看、模型切换、Loop/Workflow 编排和自我进化。

```bash
git clone git@github.com:koppx/Evolva.git
cd Evolva
uv sync
uv run evolva

# 安装为本地命令（可选）
uv pip install -e .
evolva

# 或使用 pipx 从 GitHub 安装后直接运行
pipx install git+https://github.com/koppx/Evolva.git
evolva
```

首次进入 TUI 后，直接在工作台里配置模型，不需要手动 export 环境变量。API key 会写入本地 git-ignored runtime config，并在界面中脱敏展示：

```text
/config wizard                         # 交互式配置 model / base_url / api_key / temperature
F4                                     # 快速唤起配置入口
/config                                # 查看当前 provider 配置，AK 只显示脱敏状态
/config set model <model>              # 单独切换模型
/config set base_url https://...       # 配置 OpenAI-compatible endpoint
/config set api_key <api-key>          # 保存到本地 git-ignored runtime config，界面中会脱敏
/model                                 # 查看当前模型与 provider
```

配置会保存到本地 `evolva/runtime/config.json`，该目录默认被 `.gitignore` 忽略；如果不配置模型，Evolva 仍可先以本地规则模式使用工具、记忆、Trace、Workflow、Eval 等能力。

日常使用围绕 Slash Commands：

```text
/config wizard                         # 配置模型与 AK
/model <model>                         # 切换模型
/repo build                             # 构建仓库索引
/repo search evolution                  # 搜索代码符号/片段
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem .
/mcp tools filesystem                   # 查看 MCP tools
/trace list                             # 查看最近运行
/loop list                              # 查看可复用 Agent Loops
/loop 做一个响应式 landing page，有 hero、pricing、FAQ
                                       # 一句话生成 Loop 草案，不会直接执行
/loop revise 增加移动端验收和暗色模式检查
/loop confirm                          # strict validate + dry-run
/loop execute                          # 仅 confirm 通过后执行
/loop save landing-page-loop            # 保存为可复用 Loop
/loop run dream-loop                    # 运行 Dream 证据闭环
/dream --min-confidence 0.8             # 运行 Dreaming 质量门分析
/evolve audit                           # 查看自进化覆盖
```

## 核心能力

Evolva 的能力围绕“可执行、可观测、可评测、可进化”的闭环组织。

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| **LangGraph Runtime** | 显式 `StateGraph` 节点：`prepare -> llm -> tool -> observe -> persist -> auto_evolve` | `evolva/agent/langgraph_runtime.py` |
| **TUI Workbench** | 默认产品入口，集成对话、工具日志、Trace、模型切换、MCP、Workflow 与自我进化 | `evolva` |
| **Loop Engineering** | 将重复任务抽象为可运行、可设 Gate、可回放、可进化的 Agent Loop | `/loop` |
| **Tools** | 文件、Shell、Python、Web、Todo、Memory、Context、Policy、MCP、多 Agent 委派 | `/tools` / `/run` |
| **Repo Index** | 本地语义仓库索引，按符号、引用、路径和代码片段检索 | `/repo build` / `/repo search` |
| **Memory / Skills** | 带 evidence / status / version 的长期记忆，以及带 manifest trigger 的 Markdown playbook | `/memory` / `/skills` |
| **MCP** | 在 TUI 内通过 `/mcp add` 接入 stdio MCP server，并用 `/mcp tools` / `mcp_call` 调用 | `/mcp` |
| **Workflow** | JSON DAG 编排 role agent、agent call、tool node，支持依赖声明、循环检测与错误门控 | `evolva workflow` / Slash Command |
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
2. **Loop Orchestration**：高频任务通过 `/loop` 固化为阶段、依赖、质量门和产物，底层可复用 Workflow / Tool / Dream / Eval。
3. **Guarded Execution**：工具调用先经过 Policy 与 Sandbox，再访问文件、Shell、Python、Web、MCP、Workflow 与 Sub Agents，默认保留风险决策与执行证据。
4. **Feedback Loop**：Trace 记录行为，Eval 检查回归，Self-Evolution 将反馈、失败模式和高价值经验沉淀为长期记忆与可复用 Skill。

## Loop Engineering

Evolva 把复杂 Agent 工作建模为 **Loop**，而不是散落的提示词或一次性脚本。Loop 是产品级运行单元：它描述触发方式、阶段、依赖、质量门和产物，运行后自动生成 Trace / Context / Loop Run Report，并可继续喂给 Dream 与 Eval 形成改进证据。

<p align="center">
  <img src="assets/loop-engineering.jpeg" alt="Loop Engineering end-to-end engineering loop" width="100%" />
</p>

Loop Engineering 的核心不是让 Agent 无限自治，而是把一句话需求先转成**可审阅、可验证、可回放**的工程闭环：LLM 负责理解和拆解需求，Evolva 负责安全清洗、用户确认、dry-run、质量门、执行预算和审计证据。

内置 Loop：

| Loop | 作用 |
| --- | --- |
| `dream-loop` | 收集 Trace/Eval/Memory 证据，生成 Dream Candidate，并通过 verifier 控制沉淀。 |
| `repo-improvement-loop` | 构建仓库索引，扫描改进面，再把证据送入 Dream。 |
| `eval-regression-loop` | 运行回归检查，把失败样本转化为可验证的改进候选。 |
| `release-readiness-loop` | 发布前检查 CLI、测试、Trace 与 Dream 状态。 |

TUI 内使用：

```text
/loop list
/loop show dream-loop
/loop validate dream-loop
/loop dry-run dream-loop
/loop run dream-loop
/loop run repo-improvement-loop
```

也可以用自然语言直接生成一次性的工程闭环：

```text
/loop 帮我做一个网页，介绍 AI 简历生成器，包含上传入口、示例预览、价格卡片、FAQ，移动端适配
```

这不会立刻改代码。Evolva 会先生成一个可确认的 Loop Draft，包含：

- 需求理解与 intent 类型；
- 阶段拆解；
- 检查点；
- 命令候选和 shell allowlist；
- 风险与开放问题；
- 有界执行预算，例如 `max_repair_rounds`、`max_duration_seconds`、`max_tool_calls`。

确认流程：

```text
/loop show-draft        # 查看当前草案和生成的 LoopSpec
/loop revise <反馈>     # 修改阶段、检查点或验收要求
/loop approve <确认说明> # 回答开放问题/接受默认方案，进入再次确认
/loop confirm           # 只做 strict validate / dry-run，不执行
/loop execute           # confirm 通过后才执行
/loop save <name>       # 保存为 evolva/loops/<id>.json
/loop cancel            # 放弃当前草案
```

CLI 自动化也支持同样能力：

```bash
evolva loop plan "做一个响应式 landing page，有 hero、pricing、FAQ" --show-spec
# `--show-spec` 也可以放在自然语言需求前：evolva loop plan --show-spec "做一个响应式 landing page"
evolva loop revise "增加移动端验收"
evolva loop approve "做产品官网 landing page，使用占位素材，不接后端"
evolva loop confirm
evolva loop save landing-page-loop
evolva loop execute --json
```

CLI 中可使用 `evolva loop --yes run <loop> --resume` 从最近失败运行恢复。

为了让 Loop 能直接承载真实工程流水线，Loop 运行现在默认具备几项落地能力：

- **运行前校验 / Dry-run**：`/loop validate <loop>` 与 `evolva loop dry-run <loop>` 会在不执行 phase 的情况下检查依赖顺序、Gate 引用、必填命令、工具是否存在、命令 allowlist、timeout/retries 与 Policy 拦截结果。
- **LLM-first Intent-to-Loop Planner**：`/loop <自然语言需求>` 会优先调用当前配置的 LLM，把需求拆成目标、阶段 DAG、检查点、命令候选、风险和执行预算；LLM 只生成草案，不会直接执行。草案会经过 sanitizer/validator（过滤危险命令、修正依赖、限制预算）后展示给用户确认；未配置模型或 LLM 输出不可解析时，才降级到 heuristic fallback，保证仍可离线开箱使用。
- **确认后执行，不靠猜**：如果一句话需求仍有开放问题，`/loop approve <确认说明>` 可以把用户补充写入 assumptions/revisions，清空开放问题并重新生成 LoopSpec；执行失败会自动恢复到 `ready_to_run`，用户可修正后重试。
- **非修改阶段直连 LLM**：设计、复核、最终报告等非修改 phase 默认使用 direct LLM 输出，不进入可调用工具的 agent loop，避免在 todo/context 工具上消耗步骤；上下文扫描和实施阶段仍保留完整工具能力。
- **有界执行**：生成的 LoopSpec 会携带 `execution_limits`，限制 phase 数、修复轮次、重试次数、总时长、工具调用、命令运行和文件修改规模，避免无限循环；运行器会在执行中硬性拦截超预算的 phase/gate，而不是只做静态校验。
- **仓库自适应验证**：Planner 会根据本地仓库特征选择可运行的低风险验证命令，例如有 `package.json` 时优先 npm build/test/lint，有 Python 工程或 tests 时优先 pytest；不会在非 Node 仓库里默认强跑 `npm run build`。
- **命令白名单**：所有 `shell` phase 和 `command_success` gate 必须通过 `command_allowlist`、phase/gate `allowlist` 或前缀通配规则显式放行，同时仍会经过 Evolva Policy 与 Sandbox。未声明 allowlist 的 Loop 会在运行前失败，而不是隐式执行本地命令。
- **Trace 生命周期**：独立执行 `LoopRunner.run()` 会自动创建 Trace；嵌套在 Agent 对话中的 Loop 会复用当前 Trace，避免覆盖上层审计链路。Loop Report 会记录 `trace_run_id`。
- **真实质量门**：`command_success` Gate 会通过 Evolva 的 `shell` 工具和确认/策略路径实际执行命令，并把命令、cwd、输出摘要写入 Gate 结果。
- **工程执行控制**：Phase 支持 `timeout` 与 `retries`。对于 `shell` / `python_exec` 工具阶段，若 args 未显式设置 timeout，会自动下发 phase timeout；每次尝试都会写入运行报告。
- **失败恢复**：CLI 支持 `evolva loop --yes run <loop> --resume`，会从同一 Loop 最近失败运行中复用 fingerprint 匹配的成功 phase 输出，避免长流程从头重跑；不匹配的 phase 会重新执行。

Loop spec 示例：

```json
{
  "id": "engineering-check-loop",
  "command_allowlist": [
    ".venv/bin/python -m pytest -q*"
  ],
  "phases": [
    {
      "id": "tests",
      "type": "tool",
      "tool": "shell",
      "args": {"command": ".venv/bin/python -m pytest -q"},
      "timeout": 180,
      "retries": 1
    }
  ],
  "gates": [
    {
      "after": "tests",
      "type": "command_success",
      "command": ".venv/bin/python -m pytest -q tests/test_loops.py",
      "cwd": ".",
      "timeout": 120
    }
  ]
}
```

命令 allowlist 支持三种匹配：完整命令精确匹配、可执行文件名匹配（如 `python3`）、以及以 `*` 结尾的前缀匹配（如 `.venv/bin/python -m pytest -q*`）。建议生产环境优先使用完整命令或窄前缀，并把 destructive 命令继续交给 Policy/Sandbox 拦截。

Loop 与 Workflow 的边界：Workflow 更像底层 DAG 执行格式；Loop 是面向真实工程习惯的闭环抽象，强调 gate、trace、eval、dream 和长期能力沉淀。

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

Evolva 的日常使用围绕 TUI Workbench 展开：对话、工具调用、MCP 接入、Trace 检索、模型切换、Loop/Workflow 编排和自我进化都收敛在同一套 Slash Commands 中。
默认界面基于 **Textual** 渲染，提供持久对话区、Trace / Tool Stream 侧栏、状态栏和快捷键；依赖缺失时会自动回退到轻量 inline 模式。

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
/loop list                            查看内置与工作区 Agent Loops
/loop show <loop>                     查看 Loop 阶段、Gate 和产物
/loop validate <loop>                 运行前校验 Loop spec
/loop run <loop>                      运行 Loop 并写入 Trace/Context/Loop Report
/workflow path/to/workflow.json        运行 workflow spec
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
/model [name]             查看或切换当前模型
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
/dream --min-confidence n 调整 drift-guard 置信阈值
/dream apply              应用高置信 Dreaming 建议
/loop list                查看 Agent Loops
/loop show <loop>         查看 Loop spec
/loop validate <loop>     运行前校验 Loop spec
/loop run <loop>          运行 Loop
/workflow <json-spec-path> 运行 workflow spec
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

JSONL 任务不再绑定单一 checklist，而是进入可插拔 Scorer Registry：内置 `contains`、`not_contains`、`regex`、`artifact_exists`、`artifact_contains`、`artifact_manifest`、`json_match`、`memory_contains`、`context_contains`、`trace_event`、`trace_schema`、`tool_sequence`、`command`、`latency`、`no_tool_error` 等评测算子。每个 check 都会产出 dimension、weight、evidence、expected/actual，并汇总为 weighted score，便于业务方继续接入自定义 rule-based scorer 或 LLM-as-judge。baseline 位于 `evals/baselines/`，CI 配置位于 `.github/workflows/ci.yml`。

Trace 与 artifact 也进入同一套回归体系：Evolva trace 使用 `trace.v1` schema，为每个事件分配 `event_id`、`span_id`、`parent_id`，方便 TUI/可视化层构建 timeline/DAG；写文件等产物会同步进入 `evolva/artifacts/manifest.jsonl`，记录 path、sha256、producer、run_id 与 event_id，让 Eval、Replay、Dream 能基于同一份可审计证据工作。


## 演进路线

Evolva 不把所有业务场景包装成一个固定“万能分数”，而是把 Agent Infra 的关键机制做成可检查、可替换、可扩展的工程层。当前路线聚焦四类生产化方向：

| 方向 | 当前能力 | 后续演进 |
| --- | --- | --- |
| Eval Score | Scorer Registry、多维 weighted score，内置 artifact / trace / command / tool sequence 算子 | 支持更多业务自定义 scorer、LLM-as-judge adapter、跨任务聚合报表 |
| Trace | `trace.v1` 事件具备 ID/span/parent，可支撑 timeline/DAG | 增强查询索引、跨 run 聚合、交互式可视化 |
| Sandbox / Artifact | workspace sandbox、policy gate、artifact manifest、sha256/provenance | 扩展容器/进程级隔离、资源限额、网络策略 |
| Repo / MCP / Loop | Repo Index、stdio MCP、Loop/Dream 证据闭环 | 增量索引、HTTP/SSE MCP、server health、tool schema cache、更多 verifier |

业务侧的评测数据、领域 scorer、私有工具和安全策略都可以在这套 harness 上组合，形成自己的本地 Agent Infra。

## TUI 快捷键

TUI 支持常见工作台快捷键：

| 快捷键 | 作用 |
| --- | --- |
| `F2` | 准备 `/model` 命令，快速切换模型 |
| `Ctrl+R` | 查看最近 Trace |
| `Ctrl+X` | 查看最新 Trace 的上下文 / Prompt 事件 |
| `Ctrl+T` | 显示 / 隐藏工具日志面板 |
| `PgUp` / `PgDn` | 滚动聊天窗口 |
| `Tab` | 补全常用 Slash Command |
| `Esc` | 清空当前输入 |
| `Ctrl+C` | 优雅退出 Textual TUI |

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
PYTHONPYCACHEPREFIX=.pycache uv run python -m compileall evolva tests
uv run pytest -q
evolva eval evals/tasks/smoke.jsonl --yes --baseline evals/baselines/smoke.json --min-score 1.0 --no-regression
evolva eval evals/tasks/repo_index.jsonl --yes --baseline evals/baselines/repo_index.json --min-score 1.0 --no-regression
evolva eval evals/tasks/scorers.jsonl --yes --baseline evals/baselines/scorers.json --min-score 1.0 --no-regression
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
