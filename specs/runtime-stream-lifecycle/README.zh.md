# Agent Runtime 事件流生命周期

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-stream-lifecycle/README.md)

组件：`runtime-stream-lifecycle`。修订：2026-10-20。状态：active（已实现并经本地验证）。
归属：`/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/agent.py`，对外部 `BaseRuntime.run_async` 的调用边界。
设计与验证：[runtime-stream-cleanup](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/runtime-stream-cleanup/2026-10-20-runtime-stream-cleanup.zh.md)。

- CON-1：Agent 在 `_run_async_impl` 生命周期内管理下层异步生成器。正常耗尽、显式关闭和异常展开均在同一任务关闭它；该边界不依赖脱离原任务的终结器。
- CON-2：按顺序输出原生事件，保留已有输出状态处理。保存/消费失败不重放运行或工具。传播错误及取消；清理失败仍然可见。
- CON-3：调用方必须耗尽或显式关闭迭代器，裸 `break` 不等于关闭。Runtime 负责取消、期限、协议终态及子任务清理。该边界不实现强制工具终止、保存恢复或请求去重。

不增加状态存储、身份字段、配置、权限或依赖。资源归属以每次调用为单位，包括 Harness 克隆；缓存的 Runtime 对象仍可复用。公开 API 和 ADK 行为不变。测试覆盖直接 Agent 委托、正式 Runner 保存失败和本地 Harness HTTP。本地 customer 测试通过测试 Runtime 驱动现有调度器，不代表已注册公开 customer Runtime 或已连通生产环境。

验证：`/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/test_runtime_stream_cleanup.py`、customer 测试及 Harness sidecar 发布门禁。CON-1–CON-3 对应设计的 AC-1–AC-4。回归不需要远端凭证或服务。

CON-1、CON-2 也适用于 SDK 自有 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runner.py` 中 `intercept_new_message` 和 `run()` 的转发。处理器自有包装层必须关闭自身下层。测试覆盖 VeADK Runner 公开方法与标准 Harness HTTP。成功后的处理语义不变。
