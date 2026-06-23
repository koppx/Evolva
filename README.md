<p align="center">
  <img src="assets/evolva-poster.jpeg" alt="Evolva poster - Local Self-Evolving Agent Harness" width="680" />
</p>

<h1 align="center">Evolva</h1>

<p align="center">
  <strong>把工程 Agent 跑在本地、留在证据里、管在边界内。</strong><br />
  Evolva 是一个 TUI-first 的本地 Agent 工作台：连接模型、仓库上下文、工具、MCP、Trace、Eval 和 Loop，让一次对话可以沉淀成可复查的工程执行记录。
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
  <em>一个本地工作台里完成模型配置、工具执行、Trace 复盘、MCP 接入和 Loop 编排。</em>
</p>

---

## 为什么做 Evolva

很多 Agent Demo 都能回答问题，但一到真实仓库就会遇到几件麻烦事：上下文散在文件里，工具执行缺少边界，失败后难复盘，改进也很难沉淀。Evolva 解决的是这条落地链路，而不是再做一个聊天壳。

它把一次任务拆成可检查的运行过程：

```text
Plan -> Act -> Observe -> Evaluate -> Evolve
```

复杂任务可以被保存成 Loop：有阶段、有质量门、有 Trace、有产物记录。跑完以后，失败原因、工具调用、策略决策和可复用经验都会留下来，下一次不是从零开始。

## 定位

Evolva 更像一个本地 Agent 控制台，而不是云端平台。你可以接入自己的 OpenAI-compatible 模型、MCP server、私有工具和评测数据，在本地完成调试、回放、回归和能力沉淀：

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

配置默认保存到本地 `.evolva/runtime/config.json`，`.evolva/` 会被 `.gitignore` 忽略；也可以用 `EVOLVA_RUNTIME_HOME` 指向独立的运行态目录。如果不配置模型，Evolva 仍可先以本地规则模式使用工具、记忆、Trace、Workflow、Eval 等能力。

日常使用围绕 Slash Commands：

```text
/config wizard                         # 配置模型与 AK
/model <model>                         # 切换模型
/repo build                             # 构建仓库索引
/repo status                            # 查看索引新鲜度、文件 manifest 和 skipped 诊断
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

Evolva 的功能按真实使用路径组织：先让 Agent 看懂仓库，再安全执行工具，最后把证据沉淀成可回归的资产。

| 能力 | 你能得到什么 | 入口 |
| --- | --- | --- |
| **TUI Workbench** | 一个界面里完成对话、工具执行、Trace 查看、模型切换和 MCP 接入 | `evolva` |
| **Repo Index** | 让 Agent 能按仓库语义搜索文件、符号和代码片段 | `/repo` |
| **Tools** | 受控调用文件、Python、Shell、Web、Todo、Memory、MCP 和子 agent | `/tools` / `/run` |
| **Loop Engineering** | 把重复工程任务保存成可确认、可运行、可恢复的流程 | `/loop` |
| **Workflow** | 用 JSON 描述更底层的 DAG 执行流程 | `/workflow` |
| **Trace / Replay** | 留下每次执行的证据：输入、工具、策略、错误、输出 | `/trace` |
| **Eval Harness** | 把 Agent 行为变成可回归的 JSONL 测试资产 | `evolva eval` |
| **Memory / Skills** | 只让经过治理的经验进入上下文，避免记忆污染 | `/memory` / `/skills` |
| **Guardrails / Sandbox** | 给本地执行加路径边界、风险判断、确认和回滚 | `/policy` |
| **Self-Evolution** | 从反馈、Trace 和 Eval 失败中沉淀可复用经验 | `/evolve` / `/dream` |

## 架构总览

<p align="center">
  <img src="assets/architecture.png" alt="Evolva architecture" width="100%" />
</p>

架构上只有三件事：

1. **运行入口**：TUI 负责对话、Slash Command、模型配置和 Trace 查看；Core Runtime 负责编排 plan / act / observe。
2. **执行边界**：所有文件、Shell、Python、MCP、Workflow 调用都先经过 Policy 和 Sandbox，风险决策会被记录。
3. **证据回流**：Trace 记录过程，Eval 做回归，Evolution 把稳定经验写回 Memory / Skills，让下一次执行更有上下文。

## Loop Engineering

Evolva 把复杂任务建模为 **Loop**，不是把一串 prompt 和脚本散落在聊天记录里。Loop 描述阶段、依赖、质量门和产物；执行后会生成 Trace、Context 和 Loop Run Report，也可以继续进入 Eval / Dream 做回归和改进。

<p align="center">
  <img src="assets/loop-engineering.jpeg" alt="Loop Engineering end-to-end engineering loop" width="100%" />
</p>

Loop Engineering 的核心不是“让 Agent 自己乱跑”，而是把一句话需求先变成一份可审阅的执行草案。LLM 负责拆解意图，Evolva 负责清洗命令、确认风险、dry-run、预算限制和证据留存。

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

- 需求理解；
- 阶段拆解；
- 检查点；
- 可能需要执行的命令；
- 风险与开放问题；
- 执行预算，例如最多跑多久、最多修几轮、最多调几次工具。

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

为了能承载真实工程任务，Loop 默认有几条底线：

| 机制 | 作用 |
| --- | --- |
| 先确认再执行 | 自然语言需求会先变成草案，用户确认后才运行 |
| Dry-run | 执行前检查依赖、命令、工具、预算和策略风险 |
| 有界运行 | 限制轮次、时长、工具调用和文件改动规模 |
| 命令白名单 | 需要显式允许的命令才会被执行 |
| 失败恢复 | 失败后可以 resume，复用已经成功且未变化的阶段 |
| 证据留存 | 每次运行都会留下 Trace 和 Loop Report |

Loop spec 可以很小，例如只描述一个测试阶段：

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

Loop 与 Workflow 的边界也很简单：Workflow 更像底层 DAG；Loop 更像面向工程工作的闭环任务，强调确认、质量门、证据和可恢复执行。

## 自我进化：从运行证据到能力资产

<p align="center">
  <img src="assets/evolva-dreaming-loop.jpeg" alt="Evolva Dreaming Loop" width="100%" />
</p>

Evolva 的自我进化不是自动改代码，而是一条保守的经验沉淀链路：

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

TUI 内示例：

```text
/evolve audit
/evolve 以后写 Python 文件后自动运行语法检查和 pytest
/evolve trace
/evolve apply-trace
/evolve apply-eval
/dream
/dream status
/dream backlog
/dream apply --min-confidence 0.8
/dream verify --promote
```

它会把反馈或失败模式整理成可追溯的 lesson，再沉淀到长期记忆或 Markdown Skill。`evolve audit` 用来检查哪些经验已经沉淀、哪些 Trace / Eval 失败还在等待处理。

`dream` 是更保守的一层：它先生成候选改进，再要求 verifier 通过后才能提升为长期能力。默认情况下，`/dream apply` 只暂存高置信候选，不直接写入 Memory / Skill；真正沉淀需要 `/dream verify --promote`。

## TUI 工作台入口

日常使用从 TUI 开始：对话、工具调用、MCP 接入、Trace 检索、模型切换、Loop/Workflow 编排都收敛在同一套 Slash Commands 中。
默认界面基于 **Textual** 渲染，提供持久对话区、Trace / Tool Stream 侧栏、状态栏和快捷键；依赖缺失时会自动回退到轻量 inline 模式。

```bash
evolva
```

TUI 内常用路径：

```text
/model [name]                         查看/切换模型
/repo build                           构建仓库索引
/repo status                          查看索引状态和 skipped 文件原因
/repo search <query>                  搜索代码符号、引用和片段
/mcp                                  查看已接入的 MCP server
/mcp add <name> <command> [args...]   接入一个 stdio MCP server
/mcp tools [server]                   查看 MCP tools
/mcp health [server]                  查看 MCP 健康状态和 schema cache
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
/dream status                         查看 Dream gate 与提升状态
/dream backlog                        查看候选改进 Backlog
/dream verify                         运行候选改进 Verifier
/dream verify --promote               验证通过后提升为 Memory / Skill
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
/dream status             查看 Dream gate 与提升状态
/dream backlog            查看候选改进 Backlog
/dream verify             运行候选改进 Verifier
/dream verify --promote   验证通过后提升为 Memory / Skill
/dream --min-confidence n 调整 drift-guard 置信阈值
/dream apply              暂存高置信 Dreaming 候选，等待 verifier
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

Workflow 是 Evolva 的底层 DAG 执行格式，适合描述明确的依赖关系和工具步骤。运行结果会进入 Context 与 Trace，后续 Eval / Dream 可以继续复用这些证据。

MCP 接入也按生产使用来处理：工具列表会缓存，server 短暂不可用时可以降级展示已有 schema；`/mcp health` 用来查看连接状态、工具数量、延迟和错误。

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

Eval Harness 用 JSONL 把 Agent 行为固化成回归样本。CI 会运行单元测试、语法检查和 eval gate，用 baseline 拦住分数下降、任务缺失和通过项回退。

```bash
evolva eval evals/tasks/smoke.jsonl --yes \
  --baseline evals/baselines/smoke.json \
  --min-score 1.0 \
  --no-regression
```

每条 eval 都是一条可审计的行为契约：输入是什么、期待什么、哪些证据算通过。Scorer Registry 负责把这些契约拆成独立检查，并汇总成 weighted score。

常用检查分四类：

| 类别 | 适合验证 |
| --- | --- |
| 文本结果 | 包含 / 禁止包含 / 正则匹配 |
| 运行证据 | trace event、trace schema、tool sequence、latency |
| 产物状态 | artifact 是否存在、内容是否匹配、manifest 是否记录来源 |
| 安全信号 | policy audit、sandbox rollback、MCP timeout、secret redaction |

每个 check 都会记录 dimension、weight、evidence、expected / actual。业务侧可以继续接自定义 rule-based scorer 或 LLM-as-judge，而不用重写整套评测框架。

Trace 和 artifact 也在同一套回归体系里：Trace 使用 `trace.v1` schema，产物写入 `.evolva/artifacts/manifest.jsonl`，Eval、Replay、Dream 都能基于同一份证据工作。

baseline 位于 `evals/baselines/`，CI 配置位于 `.github/workflows/ci.yml`。

Memory / Skill 治理把“保留下来”和“进入 prompt”分开。草稿、隔离和回滚状态的内容仍可审计，但不会自动影响 Agent 行为。

Repo Index 会记住哪些文件参与了索引、哪些被跳过、哪些可以复用。运行态目录默认排除，避免 Trace、Memory、Policy audit 的写入让索引反复失效。

Multi-agent 是受控协作，不是无边界自治。Task Router 会先判断任务类型：简单问题继续单 agent，调研任务走 researcher/reviewer，编码任务走 planner/coder/reviewer，复杂工程任务才会启动完整角色组。子 agent 可以调用角色允许范围内的工具，但仍然走主 agent 的 Policy、审批、Sandbox 和 Trace。默认只开放偏安全的读和检查能力；写文件、Shell、MCP 调用和递归 delegation 不在默认范围内。


## 演进路线

Evolva 不追求一个虚高的“万能分数”。它更关心每个关键能力是否可检查、可替换、可持续改进：

| 方向 | 当前能力 | 后续演进 |
| --- | --- | --- |
| Eval | 把行为变成可回归样本 | 更丰富的业务 scorer 和聚合报表 |
| Trace | 留下完整运行证据 | 更强的查询、聚合和可视化 |
| Sandbox | 控制本地执行风险 | 更细的资源、网络和隔离策略 |
| Repo / MCP / Loop | 连接仓库、工具和闭环任务 | 更强的外部工具接入和 verifier |

业务侧的评测数据、领域 scorer、私有工具和安全策略都可以接到这套本地 harness 上，形成自己的 Agent 运行底座。

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
  <img src="assets/workflow-mcp-memory.png" alt="Evolva workflow MCP memory" width="100%" />
</p>

## 安全与可审计执行

Evolva 能执行文件、Shell 和 Python，所以安全边界不是附加功能，而是默认运行方式：

| 边界 | 作用 |
| --- | --- |
| 路径沙箱 | 文件访问必须落在 workspace 范围内 |
| 可写范围 | 可以把写入限制到指定目录 |
| 失败回滚 | Shell / Python 失败后回滚受保护文件 |
| 危险命令拦截 | 阻止高危命令片段进入执行 |
| 策略审计 | 每次允许、拒绝、要求确认都会留下记录 |
| 人工确认 | 高风险工具在非 `--yes` 模式下需要确认 |
| Trace 复盘 | 工具调用、失败信息和最终输出都可回看 |

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
  architecture.png
  tui-mockup.svg
  workflow-mcp-memory.png
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
  如果你也在构建可评测、可回放、可进化的 Agent 系统，欢迎 Star：<strong>koppx/Evolva</strong>
</p>

## Benchmark readiness

Evolva includes a generic local readiness path for inspecting benchmark-style metadata CSV files and attachment folders before doing a full benchmark run.

```bash
# Check optional OCR/PDF/audio/video/web helper availability
uv run evolva benchmark health

# Check metadata, attachment resolution, preview coverage, and capability blockers
uv run evolva benchmark smoke \
  --metadata /path/to/benchmark/metadata.csv \
  --attachments /path/to/benchmark/attachments \
  --limit 10

# Generate task prompts without spending model calls
uv run evolva benchmark run \
  --metadata /path/to/benchmark/metadata.csv \
  --attachments /path/to/benchmark/attachments \
  --limit 3

# Run a tiny sample through the configured Evolva agent
uv run evolva benchmark run \
  --metadata /path/to/benchmark/metadata.csv \
  --attachments /path/to/benchmark/attachments \
  --limit 3 \
  --run-agent \
  --yes

# Preview one attachment and run optional deep extraction when supported
uv run evolva benchmark inspect-file /path/to/attachment.png --deep
```

Native benchmark helper tools are also available inside Evolva: `web_fetch`, `file_to_text`, `spreadsheet_describe`, `normalize_answer`, `benchmark_task_context`, `benchmark_smoke_check`, `benchmark_tool_health`, `ocr_image`, `audio_transcribe`, `video_probe`, `video_extract_frames`, `pdf_extract`, and `yt_dlp_info`. They use the Python standard library first and opportunistically use installed packages or binaries when present.

For web-heavy benchmark questions, Evolva now has two paths:

- Native online search tool: `web_search` / `web_search_pro` uses `TAVILY_API_KEY`, `BRAVE_API_KEY`, or `SERPAPI_API_KEY` when configured, with DuckDuckGo HTML fallback.
- MCP browser/search presets: persist local stdio MCP configs without installing or starting anything until you explicitly list/call MCP tools.

```bash
# See supported browser/search/fetch MCP presets
uv run evolva mcp presets

# Add a Playwright browser MCP server for JS-rendered pages and browser actions
uv run evolva mcp add-preset playwright

# Add a Brave Search MCP server; the key is stored in the local .evolva MCP config
uv run evolva mcp add-preset brave-search --env BRAVE_API_KEY=...

# Or add any custom stdio MCP server with environment variables
uv run evolva mcp add search npx --env BRAVE_API_KEY=... -y @modelcontextprotocol/server-brave-search

# Check schemas/health after the first network-enabled install/run
uv run evolva mcp health --refresh
uv run evolva mcp tools playwright
```

First `npx`/`uvx` runs may download MCP packages and browser assets, so they require network access. `benchmark health` reports configured browser/search MCP servers, local browser runtimes (`node`/`npx`/Playwright), and search API key presence.

For higher benchmark coverage, install optional local tools and then re-run `uv run evolva benchmark health`:

```bash
brew install tesseract ffmpeg yt-dlp poppler
uv pip install pypdf openpyxl pandas pyarrow pillow pytesseract openai-whisper
```

These dependencies are intentionally optional: Evolva reports missing capabilities clearly instead of making benchmark inspection fail at import time. `tesseract`/`pytesseract` improves image OCR, `ffmpeg`/`ffprobe` enables video frame and media metadata extraction, `openai-whisper` enables local audio transcription, `yt-dlp` helps with YouTube/media metadata, `poppler` adds `pdftotext`, and the Python packages improve PDF/table/image extraction.

Current scope: Evolva can load benchmark metadata, resolve local attachments, preview text/CSV/DOCX/PPTX/XLSX/PDF best-effort/ZIP/table files, classify likely tool requirements, and prepare prompts. Full benchmark accuracy still depends on a configured LLM plus external tools for dynamic browsing/search, robust PDF/OCR, image reasoning, audio transcription, and video/YouTube extraction. Good MCP additions for those gaps include Playwright/browser, fetch/search, Docling or MarkItDown, OCR/vision, Whisper, ffmpeg/yt-dlp, and table engines such as DuckDB/pandas.
