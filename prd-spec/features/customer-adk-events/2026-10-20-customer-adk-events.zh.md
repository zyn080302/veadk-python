# customer 通道转 ADK 事件流

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-adk-events/2026-10-20-customer-adk-events.md)

Change ID：`customer-adk-events`；创建/修订：2026-10-20；状态：implemented。
组件：[runtime-customer-adk-events](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-adk-events/README.zh.md)。
前序：`customer-tool-dispatch`。

## 证据、目标和范围

保留的 customer Host 调用 `run_studio_agent(..., yield_user_message=True)`，转发原生 ADK `Event.model_dump(mode="json", by_alias=True, exclude_none=True)`。本地 ADK Runner 已保存输入，并在输出非 partial 事件前保存事件。直接转发远端 Event 会重复输入、接受远端状态修改、身份和工作流控制。ADK `is_final_response()` 可能在 Shared 成功终态及本地工具 ACK 完成之前为真。

在既有调度器上新增可独立使用的公开 `CustomerAdkEventStream`，把普通单 Agent 文本/工具运行转为安全的展示 Event，并拥有调度器上下文。这是已授权集成蓝图的一个阶段，不是完整 customer Runtime。Agent runtime/配置分发、持久会话映射/租约、ADK 工具回调、可信业务身份、共享额度、附件、交互鉴权/确认及多 Agent 工作流仍须后续完成。不复制模型循环、工具执行器或持久化实现。

## 需求与场景

| ID | 可观察需求 |
| --- | --- |
| FR-1 | 显式传入本地 author/invocation/branch 和新增文本用户消息快照；不获取环境凭证、不信任远端身份。仅去掉开头完全匹配的用户回显；额外、不同或迟到的用户事件均失败。 |
| FR-2 | 只重建文本/thought、完整工具调用/响应和有界数字用量。忽略远端 actions、state、metadata、ID、时间戳和路由。不支持的内容明确拒绝，不静默丢失。 |
| FR-3 | 远端工具展示只按完全一致的 function ID 和名称配对，替换为新本地 ID。不猜测它与通道 request_id 的关系，不执行展示事件。重复调用/响应、孤立响应、partial 工具片段和成功时未闭合调用均拒绝。 |
| FR-4 | partial 文本及时转发。只保留一个完整最终答案，等待调度器成功终态和清理成功后才输出。错误、取消、EOF、ACK 失败或清理失败都不能输出最终答案。缺少或多个最终答案明确失败。 |
| FR-5 | 一个实例拥有一轮和一个消费者。调用方必须使用异步上下文管理，包括消费/保存失败时；在同一任务中先关闭事件流，再关闭调度器。不重放、不自动重试；下轮新建适配器和调度器。 |
| FR-6 | 单条原始事件上限 1 MiB、事件数 4096、展示调用数 1024、待响应调用数 64；只使用固定诊断。非 partial 事件数字用量只复制一次，partial 用量不复制。 |

## 设计与任务

沿用已选用的 python-design-patterns 技能，通过组合实现。公开流负责生命周期和终态顺序，私有同步转换器负责字段选择与单轮展示关联。不增加后台任务或队列，调度器仍是唯一事件读取者。内容/用量在本地校验，不暴露 Pydantic 输入。未来 Runtime 必须独立处理本地可信回调 actions；远端状态属于 Host。

| 任务 | 文件 / 需求 | 验收 |
| --- | --- | --- |
| T-1 | 先新增 `tests/runtime/customer/test_events.py`；FR-1–FR-6 | AC-1 公开入口缺失先失败，随后转换/信任边界/上限通过 |
| T-2 | 新增 `veadk/runtime/customer/events.py` 和公开导出；FR-1–FR-6 | AC-2 真实调度器往返，只有 ACK 与清理后才输出一个最终答案 |
| T-3 | 本地测试 Agent 使用实际 ADK Runner/SessionService；FR-1、FR-4、FR-5 | AC-3 只有一个用户事件、本地状态隔离、工具展示正确；保存失败关闭且不重复执行 |
| T-4 | 原 hooks、SDK 回归、双语/链接检查、业务导航/证据 | AC-4 验证后推送独立分支，不宣称部署 |

定向命令：`python3 .codex/run_offline_tests.py tests/runtime/customer`；完整 SDK：`python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`。本地包装器隔离 HOME/dotenv/遥测/外网；CI 既有 Harness 门禁运行 `python -m pytest -q tests/runtime/customer`。保留原 pre-commit 必需门禁。不改依赖、既有 runtime 选择、前端、默认业务入口或 wheel。

## 审查、授权、风险与验证

生产/测试修改前已直接完成设计审查；review-spec 不可用。已核对协议/ADK 可行性、身份/状态归属、重复及终态、有界资源、取消、错误脱敏和双语一致性。用户原有“按蓝图实施、阶段验证后立即推送”已授权本阶段，不额外推导审批或部署权限。后续主要风险为 Host 事件形态变化、持久化恢复和回调语义。不支持的能力明确失败，不声称已迁移。

2026-10-20，基于 89748f19 加本次修改：AC-1–AC-3 通过。公开入口缺失在实现前先失败。审查追加三条先失败回归：role 为 list/dict 时出现 TypeError，空 user 内容被错误接受为答案；严格 role 校验后，三种情况均以固定代码拒绝。最终 customer 定向检查 166 项通过（6.28 s）；事件模块语句与分支综合覆盖率 97%，全部 customer 为 91%。本机真实 HTTP 和实际 ADK Runner/SessionService 的保存及失败清理通过。原 pre-commit 五项、暂存凭证扫描、Python 3.10 语法与双语标识/8 条绝对链接均通过。这些门禁后源码未变。最终完整 SDK 回归：7699 项通过 / 50 项跳过 / 4 项预期失败 / 6 个子用例通过（423.75 s，2 workers）。AC-4 代码/文档门禁通过；独立分支推送及远端哈希核验作为最后交付动作，记录在消费方业务仓库证据中。

实际 Runner 集成使用拥有新事件流的测试 BaseAgent，不证明正式 Agent 委托或 HarnessApp 路径已接通；后者仍属下一 Runtime 阶段。真实 customer Runtime、模型/MCP、20 题评测与远端 CI：`not_run`；本阶段仅离线样例及本机回环验证。总体 P0–P4 继续 active。
