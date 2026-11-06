# 客户事件队列生产消费协调

对应英文：[English](2026-11-06-customer-event-backpressure.md)。
日期2026-11-06；状态：已实现并完成离线验证，固定制品集成待主会话。

## 证据、目标与边界

固定安装SDK与指定基线源码一致：`_emit`/`_emit_local`均使用`put_nowait`，短暂慢消费在已有请求/工具截止前触发`event_backpressure`。客户原案没有绑定队列时序，`root_cause_event=null`、归因abstain；机制复现不是原案因果。

用户明确授权隔离SDK队列修复，以及慢消费、突发批、原生accepted、取消、截止、退出回归和强制门禁。主会话负责固定SDK制品集成及PDSA；BugFix2负责Runtime业务终态/原会话恢复。人物门禁/V8独立先发布。不部署、push、真实模型/MCP重放、远程shell、资源枚举或修改共享SDK。

## 需求与设计

- REQ-1：保持有界FIFO、默认16/上限256、内容/顺序/usage和本地调用响应配对。采用可中断`await queue.put`替代容量即失败；不合并、丢弃或增加无界缓冲，由当前reader向传输施加消费背压。本地待入队生产者已受64-job上限约束。
- REQ-2：入队和原生`accepted`等待继续受已有owner请求截止和executor工具截止约束，不扩预算。保持执行permit在远端ACK前释放，消费者停止不能导致无限生产等待。
- REQ-3：成功仍在必要结果ACK和合法Host终态之后；异常走owner/failure状态、不依赖数据队列容量，优先于缓冲事件。无伪造成功或公开事件字段变化。
- REQ-4：关闭/取消事件迭代器后撤销提交、取消owner，在已有共同cleanup截止内回收children；晚到生产者不能恢复关闭的消费者。协作任务应收尾；不协作任务保持cleanup_timeout/隔离，不假报quiescent。
- REQ-5：实际dispatcher、原生ADK投影/Runtime/Runner及业务慢持久化消费路径回归。首个SSE partial必须在Host终态之前到达。取消和截止以明确barrier保持满队列；原生发布完成accepted/journal过程，不能重复执行。

影响`veadk/runtime/customer/dispatch.py`、新增`tests/runtime/customer/test_event_backpressure.py`以及`test_dispatch.py`既有停顿负向回归。不修改runtime.py归属。组件CON-3由立即容量失败改为可取消且受截止约束的协调；CON-4/5保持。业务门禁和制品审查另备增量由主集成。

## 任务、验证与验收

1. 保留固定SDK/制品基线，隔离包副本和业务工作树。
2. 代码/测试编辑前完成双语设计/契约审查；新增确定性实际路径回归并保留同份红测。
3. 仅实现队列协调/迭代器退出，验证同份绿、完整customer Runtime测试及受影响发布检查。
4. 复查双语一致、调度竞态、ACK、有界性、失败和收尾；按实际工具执行pre-commit，保留blocked/not_run。
5. 业务/SDK回归登记既有强制发布层，交付精确commit/patch、源码摘要和完整内部包。

验收需事件全量按序、queue高水位不超配置容量、partial先于终态、工具与结果ACK仅一次、满队列仍可观察原脱敏错误、截止/关闭/取消有界收尾且无晚到提交。测试仅合成数据和mock/本地HTTP。本任务不执行原badcase/PDSA/客户部署真实验收。

## 审查、授权、兼容与风险

review-spec不可用，直接审查双语/契约一致性、同owner取消scope、原生accepted循环、有界生产者、传输背压和错误优先。设计检查暂无阻塞，发现API/范围变化须重新审查。用户2026-11-06明确追加指示已提供需求/设计授权，不推导额外确认门禁。

远端取消若排在被背压阻塞的数据之后，须待传输继续消费才能读到；已读tool.cancel、外部任务取消和截止保持可中断。任意跳读未来控制事件需要额外无界缓冲，本实现不承诺。慢消费仍可能触及既有真实截止，应失败而非成功。消费者仍可识别旧`event_backpressure`错误码，但短暂容量不足不再自行失败。

2026-11-06验证：同份SHA fed82d45，基线6失败/1通过（5.418s）→候选7通过（3.635s）；完整customer+Runtime关闭453通过（22.018s），受影响完整Harness检查579通过（36.774s）。全文件pre-commit五个hook全绿（59.037s）。业务真实Runtime/Runner/JoinedStreamingResponse三项及标准/B14实际入口另在业务候选绑定证据。合成业务fixture采用5秒请求/工具时限容纳冷启动/观测开销；生产165秒与150/240门禁预算不变。同步目标为用户固定ae982106制品来源，不改基线到无关远端head。无关全仓unit suites为not_run：当前只准备并验证受影响Harness门禁。真实验收因用户范围not_run；原事故abstain。

绑定实际执行源码的回执：[summary.json](summary.json)。
