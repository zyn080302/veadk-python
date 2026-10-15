# 原生工具中断

[English](README.md)

组件：native-tool-interruption；日期：2026-10-15；状态：implemented（离线验证通过）。
所属代码：veadk/runtime/codex/mcp_bridge.py、runtime.py 与 execution_control.py。测试：tests/runtime/codex/test_codex_mcp_bridge.py及下游Harness原生协议测试。

CON-1：内部register_turn新增可选on_interrupt异步回调，不接收内容或凭证。既有INTERRUPT_STATUSES结果先登记状态，再等待回调，最后返回占位文本。普通结果不调用。未传回调保持桥接原行为。
CON-2：运行时回调每轮只通过原生turn接口请求一次中断。调用事件、续接结果和会话由ADK管理，不增加历史库或循环。并发轮次不共享回调状态。
CON-3：TurnInterrupt 通过 asyncio.Lock 使同轮并发调用共享一次确认；成功后才设置 done。异常或取消被保留，后续调用重新抛出，不会误报成功；不创建后台任务。取消传播。回调失败写入 turn state 并通知 on_error，MCP 仅返回通用错误，不输出异常原文或成功占位。工具准入、token、预算和超时归属保持。原事件消费中断复用同一回调作为兜底。

验证：真实loopback MCP顺序断言、正常与独立轮次对照，下游真实原生客户端工具协议往返。完整门禁及云验证记在[PRD](../../prd-spec/bugfixes/native-tool-interruption/2026-10-15-pending-tool-interrupt-order.zh.md)。不新增公共配置、环境变量、遥测或依赖。
