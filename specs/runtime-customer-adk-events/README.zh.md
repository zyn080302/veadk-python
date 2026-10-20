# customer ADK 展示事件流

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-adk-events/README.md)

Component ID：`runtime-customer-adk-events`；修订：2026-10-20；状态：active。
代码/测试：`veadk/runtime/customer/events.py`、`tests/runtime/customer/test_events.py`。
设计/证据：[customer-adk-events](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-adk-events/2026-10-20-customer-adk-events.zh.md)。

## 职责与公开入口

`from veadk.runtime.customer import CustomerAdkEventStream`。拥有一个 `CustomerToolDispatcher` 上下文，将它观察到的 `run.event` 转为 ADK 展示 Event。调度器负责执行/ACK/取消；Runner 负责本地持久化；Host 负责推理历史。本组件不提供 Agent runtime 注册、业务身份、模型循环、工具回调/状态桥、重放、会话迁移、媒体输出、交互工具授权或多 Agent 支持。

```python
async with CustomerAdkEventStream(
    dispatcher, author="assistant", invocation_id="local-invocation",
    new_message={"role": "user", "parts": [{"text": "Hello"}]},
    branch=None,
) as stream:
    async for event in stream.events():
        await persist_or_send(event)  # 调用方错误会退出并取消整轮。
```

## 合同

| ID | 合同 |
| --- | --- |
| CON-1 | 构造时快照非空的纯文本用户 Content，校验本地 author/invocation/可选 branch。上下文和 `events()` 均只能使用一次；必须先进入，再在同一 asyncio 任务中消费/退出。异常传播；远端输入相关诊断仅含固定代码。 |
| CON-2 | 只丢弃开头一次完全匹配的用户回显；不同/重复/迟到用户事件失败。输出使用本地 author/invocation/branch 及新 Event ID/时间。不复制远端 actions/state/metadata/路由/鉴权/签名。这不是业务正文或工具值脱敏器：执行器/Host 必须提前过滤密钥。 |
| CON-3 | 仅转换 text 及可选 thought、完整 functionCall/functionResponse、五项非负整数用量（promptTokenCount、candidatesTokenCount、totalTokenCount、cachedContentTokenCount、thoughtsTokenCount，每项最多 2^53-1）。也接受 snake case，歧义别名拒绝。partial 快照不复制用量。不认识的内容类型或错误结构失败。纯 thought/用量事件仅作 partial 展示，不是最终答案。 |
| CON-4 | 完整 function ID 必须非空且最多 128 字符，名称最多 64 字符并与响应一致。映射新本地 ID，最多 64 个待响应/1024 个总调用。展示不执行工具、不关联通道 request_id，也不能再生成另一套本地工具展示流。重复/孤立响应、重复调用 ID、partial 工具片段、长任务/鉴权/确认事件及成功时未闭合调用明确失败。远端回调状态不应用于本地。 |
| CON-5 | 暂存完整普通答案，不从 partial 拼造最终答案。要求恰好一个最终答案，其后不能有内容（可有纯用量事件）。仅在调度器成功且上下文清理成功后输出。错误/中断/取消/EOF/ACK/清理失败都丢弃暂存答案。空内容仅在明确 turnComplete=true 时算最终答案。最终输出 turn_complete=true，此前输出均不为真。 |
| CON-6 | 最多 4096 条原始 run 事件，单条 JSON 最多 1 MiB；完整远端 Event ID 重复则失败。只保留有界 ID 集合/映射与一个最终 Event。没有持久化/重启保证，不重试或恢复迭代器。调用方保存失败须通过新调用/对账处理，不可重新消费同一流。 |

## 状态、隔离与失败

状态：constructed → entered → consuming → closed。只有调度器关闭后才输出最终答案；外层流上下文仍会关闭生成器。消费者异常时，在同一任务中先关闭生成器，再关闭调度器。保留调度器 `cleanup_timeout` 与 `quiescent` 义务：不配合取消的上下文停止前必须隔离。进入后未消费便关闭也会取消调度器。拒绝重入/并发迭代。

错误代码包括 `invalid_adk_event`、`unsupported_adk_content`、`unexpected_user_event`、`remote_event_error`、`remote_event_interrupted`、`invalid_display_tool_call`、`invalid_display_tool_response`、`unsupported_partial_tool_event`、`unsupported_interactive_event`、`too_many_adk_events`、`adk_event_too_large`、`duplicate_adk_event`、`missing_final_response`、`multiple_final_responses`、`event_after_final`、`unresolved_display_tools` 及生命周期错误。错误不含输入值。HTTP/调度错误保留固定代码。不增加日志或指标。

## 兼容与验证

新增可选 API，不改变既有 runtime 和通道行为。仅支持普通单 Agent Shared ADK JSON；不支持的 Host 版本/能力须显式适配，不能强制转换。本地测试使用实际 ADK 序列化、Runner 持久化及调度器样例。合同映射：CON-1/CON-6 生命周期/上限；CON-2 信任/回显；CON-3 内容/用量；CON-4 工具；CON-5 终态/ACK/清理。既有 Harness 发布门禁包含 `tests/runtime/customer`。验证状态在关联设计中维护；样例通过不等于真实 Runtime 验收。

原生 Runtime 集成：私有 Python 本地事件批次共用调度器有界队列，绝不从远端 JSON 解析。原生结果提交等待 Runtime journal/yield 确认；取消、队列溢出或日志失败时停止提交。原生模式校验本地已注册工具名的远端展示，实际输出本地完成的 call/response 对；Host 自有工具展示保留。本地状态遵循 [runtime-customer CON-7](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)。既有显式 executor 的展示行为不变。


## 原生协议扩展（2026-10-20）

已实现，专项与全仓本机回归通过。[设计与证据](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.zh.md) 定义显式 protocol="native"、/apps + /run_sse、精确结果回显 ACK、跨 HTTP 期限和绑定隔离。Shared 默认行为不变。通道在既有展示投影前校验并规范化延迟工具和已验证回包回显。执行名额在等待 ACK 前释放，避免批次死锁；期限和 ACK 后 final 要求保持。store 表结构和未完成轮次隔离不变。不声称完整 Skill/附件、崩溃恢复或生产验收。


## 原生附件扩展（2026-10-20）

SDK 实现、全仓回归及固定 Host 源码联调已验证；业务固定制品验收待完成：[customer-native-attachments](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-attachments/2026-10-20-customer-native-attachments.zh.md)。原生输入增加有界原始媒体与不解释的元数据；Shared 仍只接受文本。Runtime 使用独立 8 MiB 原生首包预算；client max_initial_request_bytes=None 继承 max_request_bytes。工具批次默认仍为 2 MiB、输出事件 1 MiB。原输入保留在 ADK/Host 历史；journal/恢复表结构与输出内容不变。精确限制与验收以链接设计为准。
