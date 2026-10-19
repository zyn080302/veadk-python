# runtime-customer-tool-dispatch

[Counterpart](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-tool-dispatch/README.md)

ID: `runtime-customer-tool-dispatch`; revision: 2026-10-20; status: active.

负责合法 Shared 工具请求的执行调度，消费 [customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.zh.md)。不负责地址/鉴权/会话选择、模型执行、ADK 事件转换或持久化。

`CustomerToolDispatcher(client, request, executors, *, max_concurrency=8, event_queue_size=16, cleanup_timeout=10)` 是异步上下文管理器。executors 由服务端提供，是请求工具名称到异步 `(arguments, request_id)` 函数的完全匹配映射。使用 `async with ... as dispatch` 后只消费一次 `dispatch.events()`。调用方持有并关闭客户端，必须先关闭调度器。不能复用同一个调度器重新开始运行。

| ID | 合同 |
| --- | --- |
| CON-1 | 快照化请求/执行器，HTTP 前校验；仅接受完全匹配名称的异步执行器。并发最多 max_concurrency（1–64），排队消耗工具期限。 |
| CON-2 | 独立读取及执行；先使已取消调用失效，再取消任务。不回传迟到/已取消结果，不自动重试。工具异常只暴露 `tool_execution_failed`，到期终止整轮。 |
| CON-3 | 有界队列承载合法 Shared 信封（1–256，默认 16）；溢出以 `event_backpressure` 失败。观察事件不授权再次执行工具。 |
| CON-4 | 所有仍需回传的本地结果确认成功后才发布成功终态；模板显式 tool.cancel 的调用不再要求回传，迟到结果直接丢弃；错误优先于缓冲事件。确认未知、超时、取消或 EOF 均不能成功。 |
| CON-5 | 退出上下文先撤销所有回传资格，再请求一次取消。清理等待正数且有限，默认 10 秒，覆盖调度和子任务；内部失败、上下文退出和重复关闭共用首次清理启动时的一个截止时间。仅全部停止后 quiescent 才为真；cleanup_timeout 后必须隔离调度器、客户端和执行上下文，直至 quiescent。工具需配合取消，不宣称强制停止 Python 代码。 |
| CON-6 | 诊断不包含原始异常、凭证、事件或工具结果。任务继承当前调用上下文，但调用方仍须提供可信且可撤销的身份及持久会话互斥，本接口不建立这些保证。 |

验证：现有 Harness 发布门禁中的 `tests/runtime/customer/test_dispatch.py`。[设计/证据](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-tool-dispatch/2026-10-20-customer-tool-dispatch.zh.md)。Agent 分发已通过 CustomerRuntime 接通；业务装配仍单独推进。原生集成遵循下文 runtime-customer CON-7。

## 使用方式

以下 client、request 和 executors 均由可信调用方提供；不会创建本地模型。

```python
from veadk.runtime.customer import CustomerToolDispatcher

async def observe_run(client, request, executors):
    async with CustomerToolDispatcher(client, request, executors) as dispatch:
        async for event in dispatch.events():
            yield event
```

消费 observe_run 时应使用 contextlib.aclosing，确保提前退出也关闭调度器。收到 cleanup_timeout 后依据 quiescent 隔离尚未停止的执行上下文；不要把回传事件或任务输入写入诊断日志。

原生 Runtime 集成：私有 Python 本地事件批次共用调度器有界队列，绝不从远端 JSON 解析。原生结果提交等待 Runtime journal/yield 确认；取消、队列溢出或日志失败时停止提交。原生模式校验本地已注册工具名的远端展示，实际输出本地完成的 call/response 对；Host 自有工具展示保留。本地状态遵循 [runtime-customer CON-7](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)。既有显式 executor 的展示行为不变。


## 重复取消清理 (2026-10-20)

CON-5: 调用方重复取消不能跳过关闭 client 前的有界等待。等待既有截止时间或任务完成后再传播取消，不延长预算。

[设计](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.zh.md)
