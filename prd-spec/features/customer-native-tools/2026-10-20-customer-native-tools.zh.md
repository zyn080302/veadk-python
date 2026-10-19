# Customer 原生工具桥

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-tools/2026-10-20-customer-native-tools.md)

变更 ID：customer-native-tools。创建/修订：2026-10-20。状态：implemented。
组件：[runtime-customer](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)。

## 背景与范围

Customer Runtime 目前仅接收显式异步 executor，拒绝 Agent.tools 和工具回调。SkyEyes 需要保留现有 Python MCP 函数及 ToolContext 身份。ADK 2.7.1 的 functions.handle_function_calls_async 会执行原生 before/after/on_error 回调；State.__setitem__ 还会在 SessionService 保存前修改底层字典。迟到任务共享原始调用状态存在风险。

本阶段把异步 FunctionTool/BaseTool、Python 异步函数和原生工具回调接入实际 customer Runtime。模型/Agent 回调、SkillToolset 解析、产物、交互鉴权/确认、插件、多 Agent 和生产部署继续属于后续蓝图工作，仍明确拒绝。这是既有蓝图授权内的阶段进展，不是迁移完成。

## 需求与场景

- FR-1：服务端设置 native_tools=True 时，Agent.tools 的名称/schema 必须匹配配置声明，不得同时配置显式 executors。名称重复、声明不一致、同步函数、延迟/长运行工具、Toolset 在 Host I/O 前拒绝。既有显式 executor 模式保持兼容。
- FR-2：有效反向 tool.call 使用当前本地 ToolContext 身份和继承的 ContextVar；原生 ADK before/after/on_error 回调仅执行一次。结构化结果保真传递，不转换成字符串。展示事件不触发执行。
- FR-3：同一调用内的原生工具串行执行，每个工具使用隔离的 Session 状态副本。仅成功且受支持的状态增量在写入本地日志后供下一工具读取。已完成调用生成本地 call/response Event，经过 Runtime 既有先 journal 后 yield 路径。原生模式只过滤本地已注册工具名的远端展示（仍先校验），保留 Host 自有工具及其他模型文本/usage。
- FR-4：仅支持 JSON Session 状态和 temp: 状态。temp: 仅本轮有效，不进入持久 actions；app:/user: 写入、非 JSON 状态和其他非空 actions 明确失败。不支持的本地 actions 不得成为成功 Host 结果或本地最终答案。不承诺跨 Session 状态事务。
- FR-5：取消、期限到达、背压、日志失败、清理失败时撤销本地结果提交。迟到工具修改不得影响原 Session 或后续工具。未处理异常返回固定 tool_execution_failed；被原生错误回调恢复的异常采用回调结果。不记录异常正文。无法撤回不配合取消工具的外部副作用。
- FR-6：完整原生工具事件沿用已完成轮次的展示恢复，不发 HTTP、不重放工具。保留下一轮读回核对，因为生成器恢复不代表 ADK 已保存。

## 设计与取舍

CustomerRuntimeConfig 增加仅关键字参数 native_tools=False，模式进入 Session 绑定；仅此模式允许 tools/before_tool_callback/after_tool_callback/on_tool_error_callback。CustomerTool 的 revision、timeout、risk 元数据仍由服务端显式提供。通过 ADK 既有 schema 转换比较声明，忽略 schema title/description 注解，把对象未声明的 additionalProperties 规范为 False。工具实现或回调变化时，装配方必须提升 engine/executor revision，不能可靠地自动散列代码实现。

本轮工具桥持有串行锁和状态副本。每个调用克隆 invocation/session 数据，执行 ADK functions，在序列化前验证原始 JSON 状态和受支持 actions，再将私有 Python 事件批次送入调度器。远端 envelope 与本地批次共用同一个有界队列。投影将本地 Event 交给 Runtime；批次确认只代表已通过 journal/yield 路径，不代表 ADK 已持久保存。工具桥随后更新自己的隔离状态并返回 Host 结果，结果状态与 JSON 内容分开保存。入队前与批次确认后检查取消 request ID 和 Runtime 关闭。最终答案仍等待工具结果 ACK 与清理完成。

全部拒绝回调会丢失业务功能；从 executor 子任务直接写 journal 会破坏顺序。共用队列保持单一消费方。每轮工具串行以牺牲工具并行度换取确定的状态读改写；显式异步 executor 模式保留现有并发。服务对象与任意受信工具代码仍由调用方负责，此桥不是 Python 沙箱。

## 任务与验收

| 需求 | 任务 | 验收 | 验证 |
| --- | --- | --- | --- |
| FR-1/2 | T-1 config 和 native_tools.py | AC-1 实际 Agent/Runner 执行原生回调，错误目录在 HTTP 前拒绝 | customer 原生集成测试 |
| FR-3/4 | T-2 dispatch/events/runtime 接通 | AC-2 并发到达时状态串行可见，无重复展示/远端 actions；不支持动作失败 | 原生集成及现有投影/调度测试 |
| FR-5 | T-3 生命周期回归 | AC-3 取消、迟到修改、有界队列、日志失败不得发布成功 | 原生/调度/Runtime 测试 |
| FR-6 | T-4 持久化与 Harness 验证 | AC-4 实际 /run、/run_sse、续问和恢复保留本地 actions、不重放 | 本机 HTTP 与 Runner 集成 |
| 全部 | T-5 文档、审查与交付 | AC-5 双语合同、完整 Python 回归、pre-commit；提交推送已授权独立分支 | 仓库门禁 |

影响：veadk/runtime/customer/{config,dispatch,events,runtime,native_tools}.py、tests/runtime/customer/、本 PRD 与组件规范。现有 Harness 发布门禁已发现全部 customer 测试。不改依赖、前端、数据库 schema 或 wire protocol。

## 审查与授权

2026-10-20 直接审查（review-spec 不可用）：检查合同、错误、信任边界、有界生命周期、兼容性和双语等价。用隔离副本解决底层状态被提前修改的风险；只保留本地工具展示，解决远端/本地 function ID 无法关联问题；journal 排除 temp: 以符合 ADK 持久化行为。无未解决设计阻塞。用户既有执行蓝图授权及最新阶段 commit/push 指令覆盖本阶段；不从仓库文件推导额外权限。

## 验证与交付

2026-10-20 基于父提交 896802b44747d759b3ea8dbe8f50890fa5cc041c 加本次五个 customer 实现文件及原生测试验证。执行命令：python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer；随后同一包装器 -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'；远端同步后在隔离环境执行 pre-commit run --all-files。此阶段只用合成本机 HTTP 替身。真实 Host/模型/MCP、客户原 20 题、PostgreSQL 和部署均 not_run，不能据此声明线上兼容或性能收益。

最终审查补充：ADK 会在 JSON 规范化前把图片/媒体工具结果提取为 FunctionResponse.parts。新增回归复现了图片被静默丢弃（DID NOT RAISE）；工具桥现于本地事件和 Host 结果输出前拒绝媒体/其他 response 字段，落实既有不支持附件的边界。未知反向工具名仍由通道拒绝；on_tool_error 处理已注册工具执行失败，不代表接入了 Host 未知工具恢复。保持 CustomerRuntimeConfig 原有位置参数兼容。

实现前审查修正：新失败回归证明，全量隐藏远端工具展示会误删 Host 自有 read_skill 活动。现明确仅过滤本地已注册的工具名；Host 自有工具展示保留既有投影校验，不触发本地执行。这是保留已有远端 Skill 快照行为，不是新增本地 SkillToolset 支持。第二次在途广泛回归已失去最终版本代表性并停止；下列最终门禁覆盖修正后的实现。


最终验证（2026-10-20）：

- **pass**：隔离包装器运行最终全仓 Python 回归，2 workers：7,824 passed、50 skipped、4 xfailed、6 subtests passed，379.03 秒。按规定排除 smoke markers；跳过和预期失败不代表对应路径验收通过。
- **pass**：最终原生工具/事件 94 项，9.70 秒，包含实际本机 `/run`、`/run_sse`、Session 读回和第二轮；Host 与工具均为合成替身。较早的相关回归 310 项通过，发生在最终媒体/展示修正前。
- **fail before / pass after**：最初 10 条新测试在父版因不支持 native_tools 失败；媒体丢失和 Host 自有工具展示回归另行在修正前复现失败。最终新增 21 个测试用例。
- **pass**：24 条绝对文档链接、双语需求/任务/验收标识、全部六个修改 Python 文件的 Python 3.10 语法。既有 Harness 门禁发现新增测试文件。
- **pass**：远端同步和最终文档同步后的原五项 pre-commit 门禁（Ruff 检查/格式、硬编码密钥扫描、依赖策略、YAML 密钥扫描）。
- **not_run**：真实 Host/模型/MCP、客户原 20 题、PostgreSQL、wheel/镜像、远端 CI 与部署。本阶段仅证明本机 SDK 集成，不声明性能提升或业务迁移完成。

T-1–T-4 和 AC-1–AC-4 已在本阶段范围内实现并验证。T-5/AC-5 交付使用已授权用户 fork 分支；推送核验随生成的 SDK 提交号记录在业务证据中。
