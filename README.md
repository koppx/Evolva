# Evolva

一个仿照 DeerFlow 思路实现的轻量级本地 Agent Harness：面向 CLI 对话，内置规划、工具调用、记忆、技能、工作区执行、反思与自我进化能力。

> 设计参考 DeerFlow 2.0 的核心思想：super-agent harness、sandbox/workspace、memory、tools、skills、sub-agent/task decomposition 与长任务执行。这里实现为一个可本地运行、依赖极少的 Python CLI。

## 能力

- **CLI 多轮对话**：`python3 -m evolva.cli chat`
- **TUI 终端界面**：`python3 -m evolva.cli tui`，提供聊天区、工具日志侧栏、状态栏、输入历史、滚动和命令补全
- **OpenAI-compatible LLM**：支持 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`
- **工具调用**：文件读写/列表、shell、Python 代码执行、Web 搜索、记忆检索、技能管理
- **可观测性 Trace**：每轮记录 prompt、LLM 响应、policy decision、tool call、latency、失败工具和最终回答，支持 list/show/replay
- **Eval Harness**：支持 JSONL 任务集、产物/文本/工具错误 scorer、结果报告，适合演示 Agent 质量闭环
- **Guardrails / Policy Engine**：工具执行前做风险分级、危险 shell denylist、路径逃逸检查、secret pattern 检测、网络开关
- **Workflow DAG**：用 JSON workflow 串联 agent 节点、role-agent 节点和 tool 节点，支持长任务编排原型
- **上下文管理**：`evolva/context/context.json` 持久化消息、笔记、产物、决策和摘要，可搜索/压缩
- **沙箱执行**：统一 sandbox root/workspace 策略，文件、shell、Python 执行都受路径和危险命令保护
- **多 Agent 协作**：内置 planner/researcher/coder/reviewer 角色，可委派或串联协作
- **TodoList**：`evolva/todo/todos.json` 持久化任务状态，支持 pending/in_progress/blocked/done/cancelled
- **规划-执行-反思循环**：Agent 每轮可给出计划并调用工具完成任务
- **长期记忆**：`evolva/memory/memory.jsonl` 持久化 facts/preferences/lessons
- **技能系统**：`evolva/skills/*.md` 存放可演化技能
- **自我进化**：从反馈、失败、成功经验中沉淀 lesson/skill；支持显式 `/evolve` 和自动反思
- **安全边界**：默认仅在工作区内读写；shell 有危险命令拦截，可用 `--yes` 跳过交互确认

## 快速开始

```bash
# 可选：配置 OpenAI-compatible LLM
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"
# export OPENAI_BASE_URL="https://api.openai.com/v1"

python3 -m evolva.cli chat

# 或启动 TUI
python3 -m evolva.cli tui

# 安装后也可以使用
evolva chat
evolva tui
```

如果没有配置 LLM，CLI/TUI 仍可运行：支持 `/help`、`/tools`、`/memory`、`/skills`、`/evolve` 等命令，并用规则模式处理简单任务。

## CLI / TUI 命令

```text
/help                查看帮助
/tools              列出工具
/skills             列出技能
/memory [query]      查看或搜索长期记忆
/context [query]     查看或搜索持久上下文
/todo                查看 TodoList
/todo add <title>    添加 todo
/todo done <id>      标记 todo 完成
/agents              列出多 agent 角色
/trace list          查看最近执行 trace
/trace show <run>    查看单次执行详情
/policy              查看 guardrail 策略
/evolve [feedback]   基于反馈/最近对话自我进化
/workflow <json>     运行 workflow spec
/run <tool> <json>   直接调用工具，例如 /run list_files {"path":"."}
/exit               退出
```

## 高级能力：Trace / Eval / Policy / Workflow

这些能力是面向高级 Agent 岗位面试重点补齐的工程闭环：不仅会“调工具”，还可以观测、评测、防护和编排。

```bash
# Trace：查看与回放历史执行
python3 -m evolva.cli trace list
python3 -m evolva.cli trace show <run_id>
python3 -m evolva.cli trace replay <run_id>

# Eval：运行 jsonl 任务集并生成 evolva/eval_results/*.json
python3 -m evolva.cli eval evals/tasks/smoke.jsonl --yes

# Workflow：运行 JSON 工作流
python3 -m evolva.cli workflow path/to/workflow.json --yes
```

Eval 任务示例：

```json
{"id":"tool_write_read_001","input":"创建 hello.py 并运行","expected_artifacts":["evolva/workspace/hello.py"],"expected_contains":["hello"],"scorers":["no_tool_error"]}
```

Workflow 示例：

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

## TUI 使用

```bash
python3 -m evolva.cli tui
python3 -m evolva.cli tui --yes        # 工具执行不再逐次确认
python3 -m evolva.cli tui --no-tools   # 启动时隐藏工具日志侧栏
```

快捷键：

```text
Enter          发送消息或命令
Tab            补全 /help /tools /skills /memory /evolve /run /exit
Ctrl+T         显示/隐藏工具日志侧栏
Ctrl+L         清空当前屏幕消息
PgUp/PgDn      滚动聊天区
Up/Down        切换历史输入
Esc            清空当前输入
```

## 示例

```text
你: 帮我创建一个 hello.py 并运行它
Agent: ... 调用 write_file 和 shell ...

你: /evolve 以后写 Python 文件后自动运行语法检查
Agent: 已记录 lesson，并生成/更新技能。
```

## 项目结构

```text
evolva/
  cli.py             CLI/TUI 入口
  tui.py             curses TUI 终端界面
  agent/core.py      规划-执行-反思循环
  agent/context.py   持久上下文管理
  agent/sandbox.py   沙箱策略与执行
  agent/policy.py    Guardrails / policy engine
  agent/tracing.py   执行 trace 与 replay
  agent/multi_agent.py 多 agent 协作编排
  agent/todo.py      TodoList 管理
  agent/llm.py       OpenAI-compatible 客户端和 fallback
  agent/memory.py    长期记忆
  agent/skills.py    技能加载/保存
  agent/evolution.py 自我进化策略
  tools/builtin.py   常见工具
  eval/harness.py    Eval Harness
  workflow/engine.py Workflow DAG 执行器
  workspace/         Agent 默认工作区
  traces/            执行轨迹
  eval_results/      Eval 结果
  workflows/         Workflow spec
  context/           持久上下文
  todo/              持久 TodoList
  skills/            可演化技能
  memory/            长期记忆文件
```

## 安全说明

这是本地 Agent，具备文件与 shell 能力。默认：

- 文件工具限制在项目根目录内，并通过 sandbox 统一解析路径。
- shell 阻止 `rm -rf /`、`git reset --hard` 等危险片段。
- 非 `--yes` 模式会对 shell 执行进行确认。
