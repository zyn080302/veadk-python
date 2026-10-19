# 重复取消时的 customer 清理

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.md)

ID：customer-repeated-cancellation。创建/修订：2026-10-20。状态：implemented。

## 证据与范围

SDK 父版本 `9e14fe4b` 下，业务本机 HTTP 测试在 MCP 初始化等待时取消 `/run_sse`。调度器等待、HTTP 连接池关闭和租约释放先后收到取消；随后 owner 向已经关闭的 client 发送 `run.cancel`。AnyIO 的 shield 不能单独防御直接重复的 `asyncio.Task.cancel()`。生成器的任务归属已正确，继续保持原任务。

本次修复属于已授权的 customer Runtime 适配，覆盖调度器等待、通道取消/响应关闭、HTTP 连接池关闭及租约释放。不新增重试、不改工具结果、不恢复执行状态不确定的会话、不部署，也不声称完成真实客户验收。

## 要求与场景

- FR-1：调用方取消后立即撤销工具结果提交；后续取消不能跳过有时间上限的 owner/子任务等待，从而提前关闭 client。未完成且已提交的 run 最多发送一次 `run.cancel`。
- FR-2：在取消 HTTP、响应/连接池关闭或租约释放期间重复取消，不能中断正常配合的清理。保留有限预算；重复等待不能重置截止时间。清理完成或预算到期后继续向调用方传播取消。
- FR-3：正常完成、清理错误/超时及不配合取消的工具仍有明确行为。取消后无成功事件、重放、隐式解锁或迟到结果。running 租约进入 blocked，idle 租约释放后可重新取得。
- FR-4：公开签名、默认值、身份边界和依赖不变。不把运行中的异步生成器或已打开的 AnyIO scope 移到另一任务。不输出数据载荷或凭证诊断。

工具执行期间取消 consumer，如果在工具正常清理时再次取消，则调度器等待工具退出、Host 收到一次取消，随后外层才能关闭 client。租约释放期间取消，则清理完成后先释放持久化所有权，再向调用方抛出取消。清理预算耗尽时有界退出，不接收迟到结果。

## 设计与合同影响

在 `veadk/runtime/customer/cleanup.py` 增加私有清理辅助函数：以绝对截止时间、AnyIO shield 和延后传播直接取消的方式等待所拥有的任务；把独立的底层清理操作放到所拥有的单独任务，防止调用方取消破坏其 await 链。只在等待清理期间捕获取消，不调用 `uncancel()`，不把取消转为成功。收取消除子任务异常；超时只请求取消一次，不无限等待忽略取消的代码。

调度器只等待既有 owner/子任务，不迁移其工作。通道关闭和租约关闭在首次 await 前创建有时间上限的底层清理任务。通道取消与响应关闭继续共享一个预算（80% 留给取消，剩余时间用于响应关闭）。连接池关闭保留单独配置的预算。租约释放使用现有 store 操作预算，包含锁等待。已有生成器/scope 留在原任务。

更新 runtime-customer-tool-dispatch CON-5、runtime-customer-channel CON-6、runtime-customer-session-store CON-3。不改变协议/表结构、前端、CLI 或依赖。缓慢或不配合取消的 transport/数据库仍可能清理失败；不能强制停止任意 Python 代码，也不能证明远端回滚。调用方继续遵守既有隔离和恢复策略。

未采用：仅增加 AnyIO shield（直接取消已复现失败）；无限等待（资源保留无上限）；迁移整个 Runtime 生成器（违反任务归属）。

## 任务与验收

- T-1 / AC-1（FR-1–3）：在 `tests/runtime/customer/` 新增稳定失败回归，覆盖重复取消 consumer、取消/响应/连接池清理顺序、租约释放、超时/迟到结果。仅使用合成配置、本机 SQLite/HTTP。
- T-2 / AC-2（FR-1–4）：实现私有辅助函数，接入调度器、client 和租约。重跑受影响测试及使用 SDK 源码的业务真实本机 HTTP 取消测试。
- T-3 / AC-3：运行 customer/stream/Harness 发布门禁回归、仓库单元测试和原 pre-commit hooks。既有门禁发现 `tests/runtime/customer/`，不另设可选门禁。检查双语、绝对链接与空白。
- T-4 / AC-4：记录绑定父版本/差异的实际结果，提交推送 SDK 用户独立分支；业务 wheel 重建与接入验证作为下一业务阶段。

验证使用 `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py` 和 `.codex/run_native_precommit.py`，隔离配置仅用合成数据。业务集成使用 `/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/.codex/run_harness_backend_tests.py test_customer_mcp`。

## 审查与交付

直接设计审查（无可用 review-spec 技能）：已检查要求、所有权、取消/错误处理、兼容、安全、有界等待、测试及双语等价。已解决阻断：单独 shield 不足；生成器保持原任务，仅保护底层清理操作/等待。用户既有“按蓝图完成适配”授权覆盖本次修复；用户明确要求阶段提交推送独立分支，不合并、不部署。

实现/本地验证：pass。真实 Host/MCP/模型、客户原 20 题、PostgreSQL 与远端 CI：not_run；本地回归不证明这些链路。

阶段证据：修复前 6 failed / 1 passed，5.13 秒；client/dispatcher/store 相关回归 137 passed，3.72 秒；customer/stream/Harness 门禁回归 319 passed，44.93 秒。业务原 MCP 本机 HTTP 套件 7 passed，5.689 秒。直接追踪确认 Host 取消先于 client 关闭，生成器任务归属不变。格式修正并把租约测试移到其 fixture 所在文件后，原 pre-commit 五项通过；24 条绝对文档链接有效。全仓回归：7,831 passed、50 skipped、4 xfailed、6 subtests passed，418.18 秒，2 workers；测试版本为父版 9e14fe4b 加本次差异。
