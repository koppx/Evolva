# 生产工业化技术方案

## 环节 1：能力模型与策略控制

### 功能
- 目标：把工具执行从“按工具名粗粒度放行”升级为“按能力、风险、环境 profile 决策”。
- 输入：工具名、工具参数、工具声明的 capabilities、当前 `EVOLVA_PROFILE`。
- 输出：`PolicyDecision`，包含 `allowed`、`risk`、`requires_confirmation`、`reason`、`capabilities`、`redactions`、`audit_tags`。
- 依赖：`evolva/agent/capabilities.py`、`evolva/agent/policy.py`、`evolva/tools/base.py`、内置工具注册。
- 核心逻辑：工具注册时声明能力；策略层基于能力、路径、危险命令、网络和 MCP 调用要求给出可审计决策；`safe/prod` profile 对高风险能力更严格。
- 数据流：`EvolvaAgent._call_tool()` 读取工具能力 -> `Policy.check_tool()` 生成决策 -> trace/metrics 记录 -> 允许时执行工具。

### 验证
- 验证点：危险命令、路径逃逸、未知工具、profile 限制、工具能力字段。
- 预期结果：危险或逃逸请求返回 `Policy denied`；允许请求带完整能力和审计标签进入 trace。
- 判定标准：任一高风险请求被放行、或决策缺少能力/原因/风险字段，判定失败。

### 测试
- 单元测试：能力归一化、默认能力映射、危险命令识别、路径逃逸识别。
- 集成测试：通过 `EvolvaAgent._call_tool()` 调 shell/read_file，验证 policy、trace、metric 串联。
- 异常与回滚测试：未知工具返回 `Tool error` 而不崩溃；被拒绝工具不产生副作用。

### 可观测性
- 日志/trace：`policy_decision` 事件记录工具、参数、能力、风险、审计标签。
- 指标：`policy.decision`、`policy.denied`。
- 告警：默认 `policy-denied-any` 规则在拒绝发生时产生 alert。

## 环节 2：结构化命令沙箱

### 功能
- 目标：避免 shell 注入和不可控命令执行，提供可验证的本地执行边界。
- 输入：命令字符串、cwd、timeout、输出大小限制。
- 输出：`SandboxResult`，包含 `ok`、`stdout`、`stderr`、`returncode`、`timed_out`、`truncated`、`metadata`。
- 依赖：`evolva/agent/sandbox.py`、策略层、shell 工具。
- 核心逻辑：解析为 `CommandSpec`；拒绝 `&&`、`|`、重定向等控制符；校验 cwd 在 workspace 内；使用 `subprocess.run(..., shell=False)`；截断输出并记录元数据。
- 数据流：shell 工具 -> policy -> sandbox parser -> backend run -> trace/metrics。

### 验证
- 验证点：控制符拒绝、允许命令正常执行、超时、cwd 逃逸、输出截断。
- 预期结果：`echo safe && echo unsafe` 被拒绝且不输出 unsafe；合法命令返回 stdout。
- 判定标准：出现 `shell=True` 风险、控制符被执行、cwd 可逃逸、超时不返回，判定失败。

### 测试
- 单元测试：命令解析、控制符检测、cwd 安全检查。
- 集成测试：通过 shell 工具执行合法命令和非法命令。
- 异常与回滚测试：超时命令被终止并返回结构化失败；解析失败不执行任何进程。

### 可观测性
- 日志/trace：`tool_call` 输出包含沙箱拒绝原因或执行结果摘要。
- 指标：`tool.call`、`tool.latency_ms`、`tool.failure`。
- 告警：工具失败触发 `tool-failure-any`。

## 环节 3：可选容器沙箱后端

### 功能
- 目标：在生产/预生产提供比本地进程更强的隔离能力，同时保持开发默认可运行。
- 输入：`EVOLVA_SANDBOX_BACKEND`、镜像、网络开关、只读 root、内存/CPU/pids/user 限制、命令规格。
- 输出：容器化执行结果或明确的后端不可用错误。
- 依赖：结构化 sandbox、`AgentConfig`。
- 核心逻辑：选择 `local` 或 `docker/container` backend；生成无 shell 的 `docker run` argv；默认禁用网络、只读 root、tmpfs `/tmp`、资源限制和用户映射。
- 数据流：sandbox backend selector -> Docker argv builder -> subprocess 执行 -> 统一 `SandboxResult`。

### 验证
- 验证点：backend 选择、Docker argv、网络默认关闭、资源限制、Docker 缺失处理、固定 smoke check。
- 预期结果：Docker 命令参数符合隔离要求；无 Docker 时返回清晰失败；`evolva sandbox smoke` 可验证当前后端。
- 判定标准：容器默认联网、root 可写、资源无限制、Docker 缺失导致崩溃，判定失败。

### 测试
- 单元测试：生成的 Docker argv 包含 `--network none`、`--read-only`、`--tmpfs`、`--memory`、`--cpus`、`--pids-limit`。
- 集成测试：CLI `/sandbox`、`/sandbox smoke`、`evolva sandbox smoke`。
- 异常与回滚测试：缺少 Docker daemon/binary 时返回失败，不影响 local backend。

### 可观测性
- 日志/trace：`sandbox_info` 和 smoke 输出记录后端、root、配置。
- 指标：通过工具调用链记录 `tool.call`、`tool.failure`、`tool.latency_ms`。
- 告警：smoke 失败在部署门禁中应作为阻断信号；本地 alert 由工具失败规则捕获。

## 环节 4：Trace 脱敏与审计

### 功能
- 目标：让运行证据可审计，同时避免把 API key、token、password、private key 等敏感内容落盘。
- 输入：trace event data、final answer。
- 输出：脱敏后的 trace JSON。
- 依赖：`evolva/agent/redaction.py`、`TraceRecorder`、存储层。
- 核心逻辑：在 `TraceRecorder.event()` 和 `TraceRecorder.end()` 持久化前统一调用 redactor；保留命中类型用于审计。
- 数据流：agent/tool event -> redaction -> atomic trace write -> eval scorer 检查。

### 验证
- 验证点：已知 secret pattern 不出现在 trace 文件；脱敏标记出现。
- 预期结果：原始 secret 被替换为 `[REDACTED:*]`。
- 判定标准：trace 任意位置保留原始 secret，判定失败。

### 测试
- 单元测试：redactor 覆盖 api_key、bearer token、password、private key 等模式。
- 集成测试：写文件工具携带 secret 后，trace scorer 验证原文不存在。
- 异常与回滚测试：redactor 失败时不应阻塞工具执行；保守输出应避免扩散敏感原文。

### 可观测性
- 日志/trace：policy/tool trace 中只出现脱敏内容。
- 指标：`redaction.hit` 记录命中次数、工具来源和 redaction 类型。
- 告警：当前不默认为每次脱敏告警，避免噪声；可按部署策略加高频异常规则。

## 环节 5：原子状态存储与损坏恢复

### 功能
- 目标：提升 memory/context/todo/artifact/trace 等本地状态在并发和异常退出下的可靠性。
- 输入：JSON/JSONL 状态读写请求。
- 输出：原子写入后的状态文件、fsync-backed JSONL、损坏文件隔离副本。
- 依赖：`evolva/storage.py`、各状态 store。
- 核心逻辑：临时文件写入后 `os.replace()`；文件锁保护读改写；JSONL append 后 fsync；损坏 JSON 读失败时重命名为 `.corrupt.*` 并返回默认值。
- 数据流：store update -> file lock -> atomic write/read recovery -> caller。

### 验证
- 验证点：并发 todo 写入不丢数据；坏 JSON 可恢复；JSONL append 完整。
- 预期结果：坏文件被隔离，新状态使用默认值继续运行。
- 判定标准：损坏状态导致启动崩溃、并发写丢数据、恢复文件不存在，判定失败。

### 测试
- 单元测试：`read_json` 损坏恢复、`atomic_update_json`、`append_jsonl`。
- 集成测试：memory/context/todo/artifact/trace store 使用新 helper 后行为不变。
- 异常与回滚测试：写入中断不覆盖旧文件；损坏文件隔离后业务可降级运行。

### 可观测性
- 日志/trace：恢复行为通过 eval/命令检查验证；运行期保留 `.corrupt.*` 作为证据。
- 指标：当前以文件证据和 eval gate 覆盖；可后续增加 `state.recovered` 指标。
- 告警：生产部署可对 `.corrupt.*` 文件数量配置文件监控告警。

## 环节 6：MCP 监督与超时控制

### 功能
- 目标：避免 MCP stdio server 卡死、输出过大、配置损坏或错误进程拖垮 agent。
- 输入：MCP server 配置、请求 method、params、timeout、max message bytes。
- 输出：MCP 响应或结构化 `Tool error`。
- 依赖：`evolva/agent/mcp.py`、MCP tools、存储层、observability。
- 核心逻辑：请求超时后清理进程；读取前检查 message size；stderr tail 非阻塞；配置读写使用 atomic JSON；`mcp_add_server` 可持久化 `request_timeout` 和 `max_message_bytes`。
- 数据流：MCP tool -> manager config -> client request -> timeout/size guard -> trace/metric。

### 验证
- 验证点：超时、超大消息、配置持久化、重新加载配置。
- 预期结果：慢 server 在 1s 超时并返回 `Tool error`；指标出现 `mcp.timeout`；配置重载后 timeout 保持不变。
- 判定标准：MCP 请求无限等待、超大消息进入内存、配置丢失，判定失败。

### 测试
- 单元测试：fake process framing、超大 message 拒绝。
- 集成测试：慢 MCP server 触发 timeout；`mcp_add_server` 配置写入并 reload。
- 异常与回滚测试：timeout 后进程清理；坏配置读取走默认结构而不崩溃。

### 可观测性
- 日志/trace：`tool_error` 或失败 `tool_call` 包含 MCP timeout 片段。
- 指标：`mcp.timeout`、`tool.error`、`tool.failure`。
- 告警：默认 `mcp-timeout-any` 为 critical。

## 环节 7：产物生命周期控制

### 功能
- 目标：让工具生成的文件有 provenance、大小限制、摘要校验和可控 manifest 增长。
- 输入：工具结果中的 artifact 数据、文件路径、producer、event id。
- 输出：artifact manifest record，包含 path、sha256、size、producer、event id 等。
- 依赖：`evolva/agent/artifacts.py`、`EvolvaAgent._record_tool_artifacts()`、存储层。
- 核心逻辑：记录文件前校验路径和大小；计算 sha256；支持 verify；超过 record 上限时 prune。
- 数据流：tool result -> artifact recorder -> manifest atomic write -> eval scorer。

### 验证
- 验证点：超大文件拒绝、sha256 校验、manifest pruning、producer 记录。
- 预期结果：合法文件进入 manifest；篡改文件 verify 失败；manifest 数量可控。
- 判定标准：路径逃逸、超大文件入 manifest、digest 校验失效，判定失败。

### 测试
- 单元测试：record、verify、prune、oversize。
- 集成测试：write_file 工具产物进入 manifest，security eval 校验 producer。
- 异常与回滚测试：产物记录失败只记录 artifact_error，不回滚已成功工具输出。

### 可观测性
- 日志/trace：`artifact_recorded`、`artifact_error`。
- 指标：`artifact.error`。
- 告警：默认 `artifact-error-any` 捕获产物记录异常。

## 环节 8：观测指标、告警与查询出口

### 功能
- 目标：上线后能持续判断策略、工具、MCP、脱敏和 artifact 是否健康。
- 输入：trace events。
- 输出：JSONL metrics、JSONL alerts、human-readable report、Prometheus text。
- 依赖：`evolva/agent/observability.py`、`TraceRecorder`、CLI/TUI。
- 核心逻辑：trace 持久化时派生指标；alert rule 按窗口聚合并去重；CLI 和交互命令提供读取与 Prometheus export。
- 数据流：trace event -> observability.record -> metrics/alerts JSONL -> `/metrics` / `evolva metrics` / Prometheus text。

### 验证
- 验证点：policy denied、tool failure、tool error、mcp timeout、artifact error、Prometheus export。
- 预期结果：对应指标和 alert 可被读取；Prometheus 指标名符合 `evolva_*` 格式。
- 判定标准：关键失败没有指标、alert 重复刷屏、CLI 无法读取，判定失败。

### 测试
- 单元测试：metric record、alert rule、dedupe、Prometheus render。
- 集成测试：TraceRecorder 事件派生指标；CLI `/metrics`、`metrics list|alerts|prometheus`。
- 异常与回滚测试：observability disabled 时不写文件但返回 record；坏 JSONL 行被跳过。

### 可观测性
- 日志/trace：trace 是指标来源；指标和 alert 均为 JSONL，可回放。
- 指标：`policy.*`、`tool.*`、`mcp.timeout`、`redaction.hit`、`artifact.error`。
- 告警：默认规则覆盖 policy denial、tool failure/error、MCP timeout、artifact error。

## 环节 9：Eval 与 CI 回归门禁

### 功能
- 目标：把安全和可靠性要求固化为可重复运行的质量门。
- 输入：JSONL eval task、baseline、min score、no-regression 开关。
- 输出：eval report、gate pass/fail、CI 结果。
- 依赖：`evolva/eval/harness.py`、`evolva/eval/scorers.py`、`evals/tasks/*.jsonl`、GitHub Actions。
- 核心逻辑：每个 task 绑定自己的 trace run；scorer 支持文本、trace、artifact manifest、metric、safe glob、命令检查；CI 跑 lint、mypy、compile、coverage、build、eval。
- 数据流：eval task -> agent/tool execution -> scorer context -> report -> baseline gate。

### 验证
- 验证点：smoke、repo index、安全 eval；baseline 缺失/回退识别；metric/glob scorer。
- 预期结果：当前 security eval `7/7`，包含 MCP timeout 和 corrupt-state recovery。
- 判定标准：任务回退、分数低于 baseline、缺少安全任务，判定失败。

### 测试
- 单元测试：scorer registry、trace run binding、metric scorer、file glob scorer。
- 集成测试：`evolva.cli eval` 跑 smoke/repo/security baseline。
- 异常与回滚测试：未知 scorer 失败可解释；命令 scorer 拒绝不安全参数；baseline regression 阻断。

### 可观测性
- 日志/trace：每个 eval task 产生独立 trace run id。
- 指标：eval 可断言生产指标是否出现，例如 `mcp.timeout`。
- 告警：CI gate 失败即发布阻断；运行期告警由 observability sink 负责。

## 环节 10：CLI/TUI 与 fallback 路径一致性

### 功能
- 目标：保证无 LLM/fallback 模式下的 read/list/search 也走同一套 policy、trace、metrics，而不是绕过安全链路。
- 输入：用户命令、fallback 规则命中的文件/搜索请求。
- 输出：通过 `_call_tool()` 执行后的回答和工具日志。
- 依赖：`EvolvaAgent` fallback 逻辑、CLI/TUI 命令处理、工具注册。
- 核心逻辑：fallback 不直接读文件或搜 web，而是调用工具；路径逃逸仍被 policy 拦截；CLI/TUI 暴露 `/metrics`、`/sandbox` 等生产运维入口。
- 数据流：fallback parser -> `_call_tool()` -> policy/sandbox/trace/metrics -> response。

### 验证
- 验证点：fallback read_file 路径逃逸、metrics CLI、sandbox CLI、interactive commands。
- 预期结果：fallback 的逃逸读取会被拒绝并产生 policy denied 指标；CLI/TUI 命令输出可读。
- 判定标准：fallback 直接绕过 policy 或不产生日志/指标，判定失败。

### 测试
- 单元测试：命令 parser 覆盖 metrics/sandbox 子命令。
- 集成测试：`handle_command()` 覆盖 `/metrics`、`/sandbox smoke`、`/run` 等路径。
- 异常与回滚测试：未知命令输出 `Unknown command`；sandbox smoke 失败返回非成功信息而不崩溃。

### 可观测性
- 日志/trace：fallback tool call 与普通 tool call 使用同一 trace 事件。
- 指标：同普通工具链，覆盖 `policy.denied`、`tool.call`、`tool.failure`。
- 告警：路径逃逸和工具失败会进入默认 alert 规则。

## 当前验收边界

- 已通过：ruff、scoped mypy、compileall、coverage、build、smoke eval、repo eval、security eval。
- 当前安全 eval：`7/7`，覆盖危险命令、shell 控制符、路径逃逸、trace 脱敏、MCP timeout 指标、状态损坏恢复。
- 保留风险：默认 backend 仍为 local；Docker 实机隔离需在预生产运行 `EVOLVA_SANDBOX_BACKEND=docker evolva sandbox smoke`。
