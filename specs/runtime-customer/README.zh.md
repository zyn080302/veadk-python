# Customer Runtime

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.md)

组件：runtime-customer。修订：2026-10-20。状态：active。

负责公开 customer Agent 执行边界，组合已有通信、调度、事件投影与持久存储。

- CON-1：服务端构造 CustomerRuntimeConfig，含 endpoint、engine_id、remote_app、SecretStr agent_config、CustomerSessionStore、工具/Skill 声明及匹配异步执行器。它不是请求 schema，也不负责解析凭证；Agent 不序列化配置或 endpoint。
- CON-2：Agent(runtime="customer") 跳过本地模型初始化，仅接受本地 name/description/身份/memory/run processor 和 Runtime 配置。原生工具和工具回调需要 native_tools=True（CON-7）；模型/Agent 回调、Skill 和其他原生配置仍拒绝；运行时重新校验 clone/修改。
- CON-3：远端映射绑定本地 app/user/session 及 endpoint、配置、工具/Skill 修订摘要。私有亲和值恢复并持久更新后才允许后续 HTTP。定点查询 Session 不把历史读入模型；已有执行后远端 Session 丢失则阻止。
- CON-4：远端操作前预留，只发送新用户 Content（原生媒体见 CON-8）；准备/执行/清理都有边界，不重试整轮。完整本地 Event 先记日志再输出，最终成功需要终态、ACK 和清理。下一轮核验 ADK 实际保存日志内容后，才解除待展示状态。
- CON-5：recover_display(agent, session_service, local_identity) 获取同一租约，核验已保存前缀/内容、追加缺失展示并回读；不远端调用、不重放工具。结果不明、内容冲突/乱序及遗留占用需要其他恢复流程。
- CON-6：HarnessApp 接受预建 customer Agent；请求只能确认 runtime="customer"，不能切换 endpoint/配置/引擎/模型/工具。HarnessConfig/环境创建仍仅 adk/codex。显式 max_llm_calls、不支持的插件/特性拒绝；Host 循环/token 预算仍需另外实现。

身份须由上游鉴权。Header 来自服务端 callback，不能任意转发客户端 Header。数据库加密/访问/期限与可信工具结果处理归调用方；SQLite/离线 Host 测试不代表 PostgreSQL 或部署 Host 兼容。错误为固定码，取消传播。不自动接管租约、不保证分布式 exactly-once、不过滤正文凭证、不强停非合作工具。

设计/任务/验证以[变更记录](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer/2026-10-20-customer-runtime.zh.md)为正本。测试：tests/runtime/customer/test_runtime.py 和现有 customer/Harness 门禁。不新增依赖、前端、部署或 CLI 工厂。


## 服务端装配示例

在异步应用工厂中使用当前 SDK 分支。endpoint 和完整 Host 配置必须由可信本地配置代码提供，不能放进请求 JSON。下文 `host_configuration` 是 `SecretStr`，不是 YAML 文件名。

```python
from veadk import Agent
from veadk.cloud.harness_app.app import HarnessApp
from veadk.memory.short_term_memory import ShortTermMemory
from veadk.runtime.customer import CustomerRuntimeConfig, CustomerSessionStore

# db_engine: caller-owned AsyncEngine with hide_parameters=True and safe logs.
# adk_sessions: caller-owned ADK SessionService for display persistence.
store = CustomerSessionStore(db_engine)
await store.initialize()
config = CustomerRuntimeConfig(
    endpoint=customer_endpoint,
    engine_id="customer-v1",
    remote_app="managed_example",
    agent_config=host_configuration,
    store=store,
    headers=trusted_headers_provider,
    tools=tool_declarations,
    executors=async_executors,
)
agent = Agent(
    name="customer_agent",
    runtime="customer",
    customer_runtime_config=config,
)
app = HarnessApp(
    agent, ShortTermMemory(session_service=adk_sessions), "example_app"
).app
```


示例没有安装 `Agent.tools`/模型回调桥。显式提供匹配的异步执行器，调用方负责鉴权和结果过滤。不要配置本地 `max_llm_calls`、模型字段、插件或请求覆盖，本阶段不能在 Host 执行这些设置。标准 `/run`、`/run_sse` 支持文本输入；应用鉴权和部署不属于此示例。

默认 total_timeout=165 秒、operation_timeout=10 秒、cleanup_timeout=10 秒、max_concurrency=8、event_queue_size=16，租约还覆盖有界清理/数据库释放。Shared 首次会话准备后必须取得亲和值；native 不要求或伪造该值。首轮定点 GET/创建 Session；续问依赖已核对的 Host 合同在推理前拒绝不存在的 Session，避免下载完整历史。endpoint、Host 配置/环境、引擎版本、工具/Skill 声明变化需要新本地 Session；Header 轮换值不参与绑定，调用方须保持账号/租户归属不变。

展示保存失败时，在下一轮用户输入前仅通过可信服务端代码调用 `await get_runtime("customer").recover_display(agent, adk_sessions, ("example_app", user_id, session_id))`，返回追加事件数。已有事件必须是同一日志前缀；内容冲突或已有后续 invocation 则拒绝恢复。不会续跑未完成执行或释放进程崩溃遗留占用。恢复比较身份/内容/actions/usage，排除 ADK 自动生成的 node_info/output 记录。原生工具状态回调遵循 CON-7；插件仍不支持。

Runner 兼容边界：本阶段验证 Google ADK Runner 和标准 Harness HTTP 路由。VeADK Runner.run() 默认传入 max_llm_calls=100，customer 会拒绝该显式本地预算；Host 预算或调用方适配完成前，不能把便捷 Runner.run() 入口视为已接通。

## 原生工具集成

CON-7：native_tools=True 将已声明异步 Agent.tools 和原生工具回调接入隔离串行状态、受信本地事件批次及现有 journal/恢复路径。仅 JSON Session/temp: 状态；temp: 不持久化。其他 actions、Toolset、模型/Agent 回调仍拒绝。完整边界和验收：[原生工具设计](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-tools/2026-10-20-customer-native-tools.zh.md)。

原生工具用法：构建 native_tools=True、匹配 CustomerTool 声明、executors={} 的 CustomerRuntimeConfig；给 Agent 传入异步 Python 函数、异步 FunctionTool/BaseTool 实例和 before_tool_callback/after_tool_callback/on_tool_error_callback。声明比较忽略 schema title/description 注解，将对象缺省 additionalProperties 规范为 False。Toolset、同步函数在 Host I/O 前拒绝。Host 配置与工具元数据仍由服务端管理；工具实现或回调变化时，提升 engine_id/executor_revision。

原生调用在单轮内串行，不受 max_concurrency 并行数影响。每次使用隔离状态，通过 ToolContext.state 赋值/update 发布 JSON 增量；未生成 delta 的嵌套原地修改不提交。仅无前缀的 Session 键和 temp: 受支持，app:/user: 写入和其他非空 actions（含 skip_summarization）失败。temp: 仅本轮有效。结果返回 Host 前经过同一个有界队列及先 journal 后 yield 路径，这不代表 ADK 已持久保存。本地已注册工具名的 Host 展示仍校验，但不重复显示；Host 自有工具展示保留，不触发本地执行。复制状态和串行执行有成本，此桥不宣称性能提升。工具/服务/追踪是调用方管理的受信依赖，不是沙箱代码；工具不得把凭证放入结果、状态或遥测。既有共享/外部副作用无法撤回。


## 原生协议扩展（2026-10-20）

已实现，专项与全仓本机回归通过。[设计与证据](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.zh.md) 定义显式 protocol="native"、/apps + /run_sse、精确结果回显 ACK、跨 HTTP 期限和绑定隔离。Shared 默认行为不变。通道在既有展示投影前校验并规范化延迟工具和已验证回包回显。执行名额在等待 ACK 前释放，避免批次死锁；期限和 ACK 后 final 要求保持。store 表结构和未完成轮次隔离不变。不声称完整 Skill/附件、崩溃恢复或生产验收。

连接原生 Host 时，在 CustomerRuntimeConfig 设置 protocol="native"。agent_config 必须为 SecretStr(JSON AgentConfig)，environment 必须为空。AgentConfig 字段由 Host 校验。native_tools=True 独立启用两种协议下的本地 Agent.tools/回调。底层调用方等待 submit_result ACK 时须并发读取事件；CustomerToolDispatcher 已负责此行为。native 不要求或伪造 affinity；Shared 仍要求该值。


## 原生附件扩展（2026-10-20）

SDK 实现、全仓回归及固定 Host 源码联调已验证；业务固定制品验收待完成：[customer-native-attachments](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-attachments/2026-10-20-customer-native-attachments.zh.md)。原生输入增加有界原始媒体与不解释的元数据；Shared 仍只接受文本。Runtime 使用独立 8 MiB 原生首包预算；client max_initial_request_bytes=None 继承 max_request_bytes。工具批次默认仍为 2 MiB、输出事件 1 MiB。原输入保留在 ADK/Host 历史；journal/恢复表结构与输出内容不变。精确限制与验收以链接设计为准。

CON-8：原生仅接受 user Content，最多 8 parts/3 个内联 blob；类型 PNG/JPEG/WebP/PDF，单 blob 4 MiB、解码总量 5 MiB、文本总量 1 MiB、消息 JSON 7 MiB。接受规范标准/URL-safe Base64 并规范化为标准 Base64；校验文件头与可选 display_name（1–180 字符）。元数据是不解释的 JSON 对象（总量 16 KiB、深度 8、单消息 256 个值）。接受无冲突 snake/camel 别名。允许仅附件；URI/fileData、thought/工具字段、未知字段、非法/空负载在 Host I/O 前报 unsupported_user_message。Shared 仍只接受文本。不记录输入或将其带入错误。SDK 不渲染 PDF，业务 Host 负责转换模型请求副本。原 ADK 用户事件保留附件，恢复 journal 仍只存 assistant/tool 投影事件。测试：tests/runtime/customer/test_native_attachments.py。
