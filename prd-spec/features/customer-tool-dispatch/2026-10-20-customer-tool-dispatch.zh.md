# Customer 反向工具调度

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-tool-dispatch/2026-10-20-customer-tool-dispatch.md)

变更 ID：`customer-tool-dispatch`；创建/修订：2026-10-20；状态：implemented。
组件：[runtime-customer-tool-dispatch](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-tool-dispatch/README.zh.md)。
前序：[customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.zh.md)。

## 依据与范围

公开 Shared 客户端校验工具请求，但不执行工具。如果在 SSE 读取循环中直接等待工具，就无法在执行期间接收 `tool.cancel`；如果无限创建任务，又会把客户压力转移到业务进程。Pi 的 ADK 工具桥已经提供 `(arguments, call_id)` 异步执行器，后续可复用，无需把模型循环移回业务 Agent。

本阶段在客户端之上提供可独立使用的完整调度器，不代表已经实现 `Agent(runtime="customer")`、ADK 事件转换、持久会话归属、可信业务身份、共享配额或业务部署。这些仍是已授权集成蓝图的必需阶段。离线验证无需访问模型、凭证、实际配置或 Runtime。

## 需求与场景

| 需求 | 可观察行为 |
| --- | --- |
| FR-1 | 给定显式不可变请求及完全匹配的异步执行器，进入调度器上下文并消费合法 Shared 事件；缺失、多余或同步执行器在 HTTP 前拒绝。 |
| FR-2 | 并发工具默认最多执行 8 个（可配置 1–64）；保留客户端 64 个在途、单轮 1024 个请求的限制。排队时间计入工具期限。 |
| FR-3 | 工具执行期间持续读取 SSE；收到 tool.cancel 或退出上下文时，先使其结果失效再取消任务。吞掉取消异常的工具也不能回传迟到结果。 |
| FR-4 | 工具异常返回固定错误，不包含异常文本。工具到期终止整轮，不在到期后提交，不重试工具、结果或整轮。执行器意外取消也终止整轮。 |
| FR-5 | 事件缓冲有界，默认 16，可配置 1–256；消费者跟不上时以 `event_backpressure` 失败，取消整轮并回收配合取消的任务。转发事件只用于观察。 |
| FR-6 | 所有仍需回传的工具结果确认成功后才发布成功终态；显式 tool.cancel 的调用不要求回传；即便 Host 提前成功，失败或结果未知的回传确认也必须覆盖该成功，不得误报。 |
| FR-7 | 一个上下文持有一个读取任务、有界工具任务及一轮客户端运行。退出只取消一次，默认最多等待 10 秒完成所有清理。`quiescent` 表示任务是否已全部停止。不配合取消的执行器触发 `cleanup_timeout`；调用方必须隔离该调度器/客户端，直到 quiescent 才能复用执行上下文。Python 无法强制停止这类代码。 |

## 设计与文件

新增 `veadk/runtime/customer/dispatch.py`，公开导出 `CustomerToolDispatcher`，新增 `tests/runtime/customer/test_dispatch.py`。现有 Harness 发布门禁已经运行该测试目录。无需修改依赖、Studio 或已有 Runtime 分发。

上下文持有后台调度任务，调用方只消费一次 `events()`。读取及工具任务在创建时继承调用方上下文，但这不构成身份协议；后续业务适配器必须绑定可撤销的可信执行上下文和会话租约。信号量限制执行并发，有界队列承载观察事件。诊断仅返回固定错误码。调度器不选择地址、请求头、身份、工具目录或 Skill。

调度任务优先处理任务失败，成功终态等待工具回传结束。清理时先撤销回传资格再取消任务，包括清理超时后才结束的任务，其异常也必须被取走。执行器需配合异步取消；同步或阻塞工具需要后续业务阶段显式接入有界工作池。

## 任务与验收

| 需求 | 任务 | 验收 | 验证 | 状态 |
| --- | --- | --- | --- | --- |
| FR-1–FR-2 | T-1 接口与调度 | AC-1 前置校验及并发上限 | 定向调度测试 | pass |
| FR-3–FR-4 | T-2 取消与失败 | AC-2 无迟到/重复 HTTP 回传，错误固定 | 取消、排队到期、异常测试 | pass |
| FR-5–FR-7 | T-3 生命周期与背压 | AC-3 缓冲和清理有界，终态真实，可再次调用 | 慢消费者、确认竞争、清理与复用测试 | pass |
| FR-1–FR-7 | T-4 同步与交付 | AC-4 原客户端、真实本机反向 HTTP、全仓回归与原 hooks | 以下命令 | pass |

命令：`python3 .codex/run_offline_tests.py tests/runtime/customer`；全仓：`python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`；隔离 HOME/cache 下执行原 pre-commit hooks。`.codex` 包装器是本地证据设施；CI 通过原 Harness 门禁运行 `python -m pytest -q tests/runtime/customer`。

## 审查、授权与风险

生产代码/测试前已直接审查（review-spec 技能不可用）：协议仍归 customer-channel；不新增模型循环、环境鉴权、持久化写入或重试；信号量和队列有硬限制；取消先失效再回收；远端成功等待本地回传确认。双语 ID、限制和验收一致。用户已有按蓝图实施及阶段验证后推送的指令覆盖本阶段，不新增部署或合并授权。

尚未验证：真实 Host 时序、工具是否配合取消、适合实际负载的并发及队列大小、持久租约恢复和实际业务身份。默认值是保护边界，不是客户容量结论。整体集成和客户原 20 题验收仍未完成，不能据本阶段宣称蓝图完成。

交付前审查修正：失败回归测得配置清理预算 0.2 秒，实际等待 0.3047 秒，原因是内部失败与上下文退出分别重新计时。现统一使用一个单调时钟清理截止时间，重复 close 也不重新计时；强化 FR-7，范围不变。

## 最终验证记录

2026-10-20，基于 SDK b4d91382 加本变更。初始公开入口缺失测试失败；额外清理叠加回归先失败再修复。最终 customer 定向 92 项通过（3.60 秒）；dispatch 语句与分支综合覆盖率 94%，整个 customer 目录 89%。真实本机 HTTP 同时覆盖客户端直连与调度器工具回传。

最终源码全仓回归 7625 passed / 50 skipped / 4 xfailed / 6 subtests passed（388.29 秒，2 workers）。原 pre-commit 五项通过；Python 3.10 语法、双语 ID/链接与 diff 检查通过。早期运行在清理修正后已中止，不计作最终证据。未执行实际 Runtime、模型/MCP、客户原 20 题、远端 CI 或新业务镜像；本阶段不包含部署。
