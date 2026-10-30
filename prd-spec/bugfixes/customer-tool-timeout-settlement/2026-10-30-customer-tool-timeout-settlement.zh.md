# Customer工具超时结算

[English](2026-10-30-customer-tool-timeout-settlement.md)

变更ID：customer-tool-timeout-settlement。日期：2026-10-30。状态：范围已授权，验证待执行。

## 背景与授权

调用方反馈工具超时没有本轮回复，后续同会话被恢复保护拒绝。Dispatcher清理可证明本地静止，但Runtime的可选确认路径排除了tool_timeout；调用方只确认断连，无法结算工具期限。用户已明确授权修复这些失败并发布对应业务Runtime；本变更执行已有授权范围，不新增外部资源权限。

## 要求与设计

R1：仅精确、受控的tool_timeout，在dispatcher、HTTP和待提交journal清理后可请求可选服务端确认。其他通道失败保持。无回调或返回值非字面True仍隔离。
R2：CustomerCancellationContext增加reason，默认customer_turn_cancelled。唯一新增原因tool_timeout；不能由错误推断远端停止。可信调用方确认精确owner/step/identity并保留原输入与事件。
R3：确认超时后，将未配对调用以tool_timeout、side_effects unknown结算；向持久化journal追加interrupted、turn_complete超时提示。存储保留cancelled表示执行已停止，事件记录实际原因。不迁移表，不重试工具。
R4：与断连取消不同，超时终态通过Runner发布一次。yield前持久化缺失journal前缀及配对回执；Runner保存唯一终态后核验并确认显示，再释放所有权。发布失败或取消继续保持恢复要求。未确认超时保留原异常。
R5：用户取消、transport断连确认、正常完成、身份隔离及历史变化拒绝保持现有行为。

## 任务、文件与验收

T1：增加真实executor期限的shared/native Runner红测试，验证清理证明、原历史、精确终态与同会话追问；覆盖拒绝/抛错确认及无回调。
T2：更新cancellation.py、runtime.py及runtime-customer、runtime-customer-session-store双语契约；不放宽Dispatcher或channel期限。
T3：执行SDK专项、完整必需门禁及已安装调用方双进程/持久化HTTP回归，发布前必须通过。在本文件记录实际结果，离线通过不证明线上行为。
A1：不重放executor、不强行解锁；本轮持久化超时终态恰好一次，原输入及历史保留，追问使用同一binding。
A2：停止不明确或存储冲突仍隔离；全部既有取消测试通过。

## 审查、兼容性与风险

review-spec技能不可用，已直接审查：可选确认保持默认与权威停止证明。新context字段有默认值兼容旧调用。事件不包含凭证、路由或供应商错误。yield/存储顺序是主要风险，须通过真实Runner和持久化调用方回归。范围授权来自用户既有明确修复发布指令，此范围无需重新请求。总期限/Runtime期限结算不在本变更范围。

## 验证

已按R1–R5实现。同份真实期限回归修复前8失败/2通过、修复后通过；customer专项417通过。两worker SDK默认回归7,979通过、50跳过、4 xfailed、6 subtests通过，受测Python源码摘要保持不变。隔离wheel只用于调用方消费验证。standard/B14安装版持久HTTP验收每配置4项通过、零跳过，隔离wheel import与Python源码校验通过，进程均已停止。Host测试替身override已纠正转发可选reason关键字；权威停止证明及全部历史/续问/不重放断言仍强制检查。仓库hook、正式源码绑定制品、部署后验收与发布仍待完成，不宣称线上已修复。
