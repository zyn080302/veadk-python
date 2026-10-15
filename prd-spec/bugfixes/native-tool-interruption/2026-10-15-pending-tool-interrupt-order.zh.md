# 待处理工具的中断顺序

[English](2026-10-15-pending-tool-interrupt-order.md)

变更ID：native-tool-interruption；日期：2026-10-15；状态：approved。
合同：[native-tool-interruption](../../../specs/native-tool-interruption/README.zh.md)。

## 证据与范围
Harness原生Responses客户端工具回归发现，调用方提交工具结果之前出现两次上游请求。McpBridge登记pending后立即返回占位文本，runtime.py到下一个事件才中断，和原生下一次请求存在竞态。

## 需求与设计
FR-1：pending/authentication_required/confirmation_required/transferred在返回MCP占位文本前等待本轮中断回调。FR-2：保留原始ADK调用事件和调用方负责的结果，不伪造完成。FR-3：普通完成工具、工具准入、预算与其他轮次保持原行为。不新增循环、配置、重试或提供商分支。
内部McpBridge.register_turn可选on_interrupt回调调用既有turn.interrupt接口。先登记中断状态再等待。运行时让桥接和既有事件消费检查复用幂等回调。取消继续传播，不分离后台任务。

## 任务与验收
T-1/AC-1：桥接HTTP覆盖所有中断状态的顺序及正常工具不受影响。T-2/AC-2：运行时接线并真实原生验证Harness Responses/Messages/Chat调用结果续接，每轮仅一个上游请求。T-3/AC-3：桥接/运行时定向测试、强制Python回归、原生smoke和pre-commit。T-4：同步双语文档。

## 风险、评审与授权
中断可能取消正在执行的工具handler；保留已发ADK事件并测试回收。回调错误不能变为成功结果。仅内部兼容扩展，不改前端或依赖。已直接完成设计评审，无未决设计阻塞。用户在当前会话授权补齐Harness兼容能力和修复，无需重复设计确认。云验证只允许现有5663目标，凭证留在本地。

## 验证记录
2026-10-15：原生客户端工具红测稳定复现额外上游请求。修复后桥接测试 33 passed、1 skipped，覆盖四类等待状态、并发确认、回调失败和取消。下游 Harness 原生测试 15 项通过，包含三协议调用/回执往返且每轮仅一次模型请求、Workflow 恢复与双向 A2A。

`python -m pytest tests -q`：7136 passed、50 skipped、4 xfailed，6 个子测试通过。使用隔离环境并开启遥测，使 tracing/metrics 测试实际初始化；初轮 OTEL_SDK_DISABLED=true 导致 65 项遥测测试失败，纠正环境后 65 项复查和完整重跑均通过。`python -m pytest tests/runtime/codex/test_codex_native_smoke.py -q` 与选定持久化 smoke：12 passed、2 skipped（缺外部数据库配置），已实际启动原生进程。`pre-commit run --all-files` 全部通过，包含依赖策略和密钥检查。

2026-10-15 已复核本次 execution_control、mcp_bridge、runtime 及回归文件的取消、共享确认、错误脱敏、普通工具兼容和轮次隔离，没有未解决的本地阻塞。云验收与新版公共镜像仍待完成，须单独记录；本地夹具结果不代表云验收。
