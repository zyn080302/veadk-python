# 在所属任务内关闭委托 Runtime 事件流

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/runtime-stream-cleanup/2026-10-20-runtime-stream-cleanup.md)

变更 ID：`runtime-stream-cleanup`。创建/修订：2026-10-20。状态：implemented。
合同：[runtime-stream-lifecycle](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-stream-lifecycle/README.zh.md)。

## 证据、范围与场景

`Agent._run_async_impl` 显式关闭 ADK 生成器，但用裸 `async for` 转发外部 Runtime 事件。包装层停在 `yield` 时关闭它，不会同步关闭下层生成器。这是通用的资源归属缺陷：Runner 保存失败、消费者提前退出或处理事件期间取消，可能把 Runtime 清理留给其他任务中的异步终结。customer 事件流要求退出与进入发生在同一任务。

本阶段在注册 customer Runtime 前修复 Agent 公共边界。不注册 customer，不添加会话映射，不修改模型重试策略，也不代表部署后的全链路迁移完成。这些仍属于已授权集成蓝图。

委托 Runtime 已输出事件时，消费者关闭迭代器，应在进入时的任务中完成 Runtime 清理后再返回。Runner 在工具结果之后保存失败时，应传播原有错误、关闭下层事件流，且不重放工具。取消和正常完成保持原有含义。

## 要求与实施

| 要求 | 任务 | 验收 |
| --- | --- | --- |
| FR-1：用 `aclosing` 管理下层生成器 | T-1：先写失败回归，再最小修改 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/agent.py` | AC-1：显式关闭、消费者异常及取消均在原任务中清理一次 |
| FR-2：保留原生事件顺序、输出状态和错误 | T-2：正式 Agent/Runner 测试与 Harness HTTP 回归 | AC-2：正常及失败路径保留结果、状态与错误语义 |
| FR-3：经该边界释放实际 customer 调度器资源 | T-3：用测试 Runtime 组合现有 client/dispatcher/events，承载者使用生产 Agent | AC-3：保存失败关闭 HTTP、取消运行、停止所属工具且不重放 |
| FR-4：强制门禁保留回归 | T-4：扩展 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.github/workflows/harness-sidecar-release-gate.yaml` 及其合同测试 | AC-4：源码/测试变动触发门禁并执行回归 |

复用已有 `contextlib.aclosing`，不增加依赖或包装抽象。不吞掉清理错误，不将取消转换为最终成功输出。Runtime 仍负责自己的有界清理；Agent 不强制终止不合作的 Python 工具。测试使用合成配置、隔离 HOME 和本地传输，不需要凭证或真实服务调用。

受影响消费者是所有经 Agent 执行的非 ADK Runtime，包括 Harness 克隆的 Agent。公开签名、Runtime 选择、模型配置和线上协议不变。新增专项生命周期合同管理资源释放语义，引用已有 customer 协议合同而不复制。Studio 前端和依赖不受影响。

## 审查与授权

在生产/测试修改前直接审查设计（无可用 `review-spec`）：已检查资源归属、异常传播、同任务清理、兼容性及双语一致性，无设计阻塞。授权来自用户既有“按蓝图完成适配、继续优化”的要求，以及阶段验证后向独立分支提交、推送的明确要求。本阶段是范围内的前置修复；不授权合并或部署。

## 验证记录

2026-10-20，基于 `37902a4b24eba648d9a160b3dcdb61c84c396ac5` 的差异：

- `pass`：初始 Agent 回归复现 11 条失败、4 条通过；修正 ADK 子任务归属断言后恢复原 Runner，五条 Runner 回归全部失败。修复后生命周期检查 28 项通过，耗时 5.77 秒，包含真实本机 HTTP 断开和再次发送；较早的受影响检查 213 项通过，耗时 20.56 秒。
- `pass`：`python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`：7727 项通过、50 项跳过、4 项预期失败、6 个子用例通过，耗时 390.11 秒，2 workers；排除了显式 Codex/Pi smoke。原 pre-commit 五项通过；Python 3.10 语法、双语合同标识、8 条绝对链接及 diff 空白检查通过。
- `not_run`：远端 customer、模型/MCP、客户原 20 题；本变更未提供其所需集成环境。
- `not_applicable`：新依赖解析、前端构建或架构图变更。

隔离测试包装器属于本地开发设施；CI 用仓库依赖执行同一批已提交测试。测试入口为 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/test_runtime_stream_cleanup.py`；范围内 AC-1–AC-4 均已本地验证。远端 CI、部署、customer 注册及业务 wheel 替换仍未验证或未实现，不能从上述结果推断。

## 已审查的范围细化：Runner 转发

标准 Harness 使用 `veadk.runner.Runner`；其 `intercept_new_message` 和 `run()` 的转发生成器也使用裸 `async for`。因此 AC-1、AC-2 必须包含这些 SDK 自有包装层，不只包含 Agent。T-1 扩展到 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runner.py`，每个所属边界使用 `aclosing`；测试公开 `run_async`、`run` 中处理器提前退出/异常，以及 Harness HTTP 保存失败。第三方处理器仍负责自身内部生成器。这是所需链路上的同一清理机制，不改日志或成功后的处理语义。已在扩展测试/实现前直接审查，不增加权限或部署范围。
