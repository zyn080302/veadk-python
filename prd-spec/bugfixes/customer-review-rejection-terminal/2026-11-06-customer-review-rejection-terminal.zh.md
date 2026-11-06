# 客户审核拒绝终态兼容

[English](2026-11-06-customer-review-rejection-terminal.md)
Change ID：customer-review-rejection-terminal；日期：2026-11-06；状态：已批准隔离实现。

## 背景与证据
真实 SkyEyes scoped 审核回调输出 `ResearchDeliveryReviewRejected`，元数据严格为 `skyeyes_result: {status: "incomplete", reason: "research_delivery_review_rejected"}`。固定 SDK 以 `invalid_result_status` 拒绝这一合法原因；真实 SDK/SSE/SQL/history 集成测试在展示公开未完成提示之前失败。这是已确认的 SDK 消费兼容机制，不是原客户事故的归因。新业务分类为 `research_delivery_review_incomplete`，独立于模型/工具协议错误。

## 目标、边界与场景
让合法审核拒绝以业务 incomplete 经过序列化、展示投影、传输收尾、持久历史和展示确认。不得变成业务成功，也不授予重试、state、身份或权限。用户授权高优修复与合入，主代理明确委派这一隔离的单 reason 兼容修复。主代理负责 wheel 装配/固定、合入、PDSA 发布和原线上 badcase 验收。本 worker 不修改共享 SDK 安装、依赖/版本、冻结工作树，不调用模型/外网、不发布、不执行远程 shell。
公开模型停止提示及空正文/无正文标记终态，只能在调度器完成且清理成功后收尾。未知原因、非法状态、伪造字段、草稿、工具/thought/user 事件及元数据歧义继续拒绝。普通完成以及新会话/调用保持独立。

## 要求与设计
FR-1：仅向 `_display_metadata` 既有严格 reason 集合加入 `research_delivery_review_rejected`。保留恰好两键、status、双别名歧义、新副本与本地身份映射检查；旧协议/预算原因继续有效。
FR-2：持久化完成使用同一校验器，不改变暂存 final、ACK、清理、取消、journal 所有权或恢复准入。传输完成与业务未完成独立。
FR-3：同份红绿回归经过真实 ADK 序列化、CustomerAdkEventStream/dispatcher、SQLite 存储/重连/历史/展示确认，覆盖跨身份隔离及下一轮独立成功。保留严格 marker/content 失败和原协议测试。既有强制 Harness `tests/runtime/customer` 目录自然包含新增测试，无需绕过门禁。
双语 runtime-customer-adk-events 组件规范 CON-8 是 reason 白名单正本，仅扩展该集合。不改公开 API、存储表结构、配置或无关组件。

## 任务、验收与审查
T-1/AC-1：把隔离的 3710 文件源码绑定到固定制品准确源清单，保留原源/测试和共享环境。
T-2/AC-2：先新增回归，在生产代码未改时证明合法新 reason 失败，再以同份测试验证窄候选零失败/跳过。
T-3/AC-3：执行强制 customer 目录、相邻 Runtime cleanup、改动文件 Ruff、双语/差异检查。通过隔离源码导入，由 contextual worker 执行业务实际 SDK/SSE/SQL/history 与 native outer，不修改共享 SDK。
T-4：交独立可审 delta、准确源/测试摘要与真实计数、完整内部源码候选包及确定性构建辅助。实际 wheel 装配/固定和线上验收属于主代理，离线测试不代表可发布。
review-spec 不可用，已等价直接审查：双语等价，原因集合严格有界，终态/身份/所有权检查不变，无新增依赖，外部服务仅本地样例，回归覆盖实际失效层；无设计阻塞。既有用户任务与主窄修授权批准方案，优先于仓库再次确认或同步远程源码要求。准确固定源不能经 pull/rebase 漂移。审查在生产及测试修改前完成。

## 风险与验证
旧制品继续拒绝新原因。主代理必须构建并固定新的不可变制品，不能盲刷新旧摘要。未来未知原因仍报错并需要独立合同审查。全仓/pre-commit/真实 Runtime 尚未执行，测试后补充实际结果。内部包包含模版 SDK 源码，不是客户交付物。

2026-11-06验证：固定源与安装events字节一致，3710文件源清单零失配。新增/相邻targeted49：未改生产源39绿/10红，候选49绿/0skip，外网0。强制customer+Runtime cleanup529绿/0skip，41loopback/0外网。改动文件Ruff check绿；之后仅新增测试完成格式化，最终同份未改父行为仍10红。真实安装制品验证待主新授权dev21构建，源导入通过不能证明Host子进程使用候选。全仓/pre-commit/线上验收not_run。
