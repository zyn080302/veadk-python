# 客户业务交付状态投影

[English](2026-11-06-customer-business-partial-status.md)
Change ID: customer-business-partial-status；date: 2026-11-06；status: 已实现及本地验证；制品/线上待验。

## 验证检查点
最终同份SDK27项：d140455b修前26失败/1通过，修后27通过；受影响customer目录478通过，五项pre-commit hooks通过。独立业务同份5方法修前5条AssertionError记录/0errors/skips→5通过；standard/B14实际入口2通过，内部精确5。生产分页historyAPI原来只保留purpose，独立严格白名单现保留两份业务状态合同。相对92bcd常规外层67→68/135→136，主集成按新增ID累加。独立前端7402968有HTTP6/browser2红绿、npm132/强制8/type/build/quick通过；908087c仅登记文档。精确源码/安装SDK摘要及回执见[evidence/test-summary.json](evidence/test-summary.json)。这是离线合成机制，原root_cause_event=null；主负责固定制品/tasks终审/冻结完整组合/PDSA，本轮均待验。

## 证据、目标与范围
前序d140455b已保留skyeyes_result的两个固定incomplete原因，但丢弃skyeyes_research_delivery；实际业务after_model回调生成五字段合同。SDK传输完成不表示研究必要项全部完成。原事故root_cause_event=null，不声称原请求因果。用户明确授权隔离白名单修复与实际入口回归；主负责预算、制品、tasks、全门禁和PDSA。不改共享SDK/主/guard，不云模型/MCP/业务重放/push/部署或提高deadline。

## 要求与设计
FR-1：_display_metadata仅接受新副本skyeyes_research_delivery对象，键恰为version、model_reported、outcome、requirements、unknown。version为整数1（非bool），model_reported为literal True；outcome为answer/partial/clarification；requirements为整数1..128，unknown为整数0..requirements。answer要求unknown0，partial/clarification要求unknown>0。保留字段非法则固定invalid_research_delivery拒绝且不回显。其他远端metadata/state/auth/事实不导入，事件身份保持本地新绑定。
FR-2：交付状态仅附于非partial的model公开纯文本待释放最终事件；用户、思维、工具、草稿、无正文及显式非终态标识拒绝。普通ADK最终正文缺remote turnComplete继续兼容；仅真实run.completed、结果ACK及dispatcher成功清理后释放本地turnComplete终态。标识不补造final，不改执行状态/usage/正文。
FR-3：journal/SSE/ADK历史保留五字段原值；既有两键/两reason的严格incomplete合同保留。transport completed仅传输收尾。Runtime/session_store接口和恢复状态机不变：仍需完整journal/历史回读、展示ACK/idle及独立owner/returned/proof/CAS。settled partial可以进入独立授权下一轮；unknown或清理失败不能。
FR-4：前端实时/历史仅将合法partial业务outcome标incomplete，保留原公开正文与流式前缀，隔离身份/调用，不自动重试或授恢复权。裸诊断、非法EOF脱敏和完整JSON EOF兼容保留前序字节。answer/clarification与partial分别处理，均不认证授权或事实。

## 任务、验证与验收
T-1/AC-1：tests/runtime/customer/test_business_delivery_status.py通过实际ADK序列化/CustomerAdkEventStream/dispatcher及注册Runtime/Runner/session journal，覆盖别名、非法输入、身份/state排除、增量、失败清理和展示ACK/下一轮。同份测试在d140455b失败、events.py修复后通过。既有Harness workflow执行整个customer目录。
T-2/AC-2：新增业务实际HTTP测试用真正ResearchCompletion.after_model生成metadata，贯穿本地Host HTTP→Runtime→SQL journal→SSE→history，核incomplete诊断及下一轮/零MCP，登记backend自动发现、catalog和standard/B14精确计数入口。loopback+独立复制固定已安装SDK，不构建wheel/云调用。
T-3/AC-3：实际runSSE→projector和源码Vite浏览器核partial原正文、实时/历史incomplete、增量时序、下一次手动发送和不自动重试，纳强制npm；保留client/sse字节和全部旧回归。
T-4/AC-4：更新runtime-customer-adk-events双语合同；运行受影响customer、格式/凭证hooks，绑定源码/测试摘要，交独立commit/patch及完整内部包。主/Testor最终组合与线上保持not_run。

## 审查、风险与授权
review-spec技能不可用，直接审查别名歧义、字段边界/类型、恶意metadata、非partial终态形状、本地身份、传输/ACK/清理顺序、unknown拒绝、不改预算/guard及双语一致性。用户当前明确独立白名单指令已授权，不重复询问。精确基线d140455b/92bcd6b/9fca508；远端rebase会混入无关增量，不属于隔离交付。本次无SDK公开签名/store/schema/调度改变，仅维护显示合同。执行前所有检查not_run；机制测试不归因原事故。
