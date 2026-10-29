# 客户会话当轮的确认取消

[English](2026-10-29-customer-confirmed-cancellation.md)

变更 ID：customer-confirmed-cancellation。日期：2026-10-29。状态：approved。
组件：[customer Runtime](../../../specs/runtime-customer/README.zh.md)、[会话存储](../../../specs/runtime-customer-session-store/README.zh.md)、[Dispatcher](../../../specs/runtime-customer-tool-dispatch/README.zh.md)。不改前端、依赖、发布凭证或模型配置。

## 证据与目标

当前业务入口与 CustomerSessionLease.close 都在运行中 SSE 取消后将会话隔离。即使过期，相同业务身份也无法继续。已有七项业务复现确认的是缺陷，不是修复。仅关闭本地 HTTP 响应不能证明 Host 停止；外部工具已经产生的副作用无法回滚。

目标是在确认用户断连后，使用原鉴权应用、用户、会话与远端映射继续追问。进程崩溃恢复、超时接管、任意强制解锁与自动工具重放不在范围内。未显式接入的 SDK 默认仍保持保守行为。

## 需求与场景

- FR-1：服务端观察真实 ASGI disconnect。客户端 Header、任务取消、期限与传输错误本身不能授权恢复。执行前取消保持原有安全释放。
- FR-2：Runtime 撤销提交并等待 Dispatcher、工具任务及 HTTP 清理完成后，才调用可选的服务端异步取消确认器。Dispatcher 未静止、清理失败或重复取消耗尽清理预算均保持 blocked。
- FR-3：确认器接收不可变且 repr 不泄露内容的上下文，包含本地应用/用户/会话、invocation、远端映射与已保留 run。仅在远端执行已禁止继续、已停止且历史已收尾后返回严格 True。SDK 不臆造远端停止证据；SkyEyes 提供接入，请求不能配置。
- FR-4：保留完整 journal 事件与原用户历史；不把流式片段提升为成功答案。只恢复已验证的持久化前缀，以明确取消/副作用未知的回执闭合未配对工具调用，并追加中断终态事件。回读核对完整终态 journal 后才允许新一轮。冲突、后续轮次或历史缺失均阻止释放。
- FR-5：只有存活的原 owner 能收尾原 invocation/run。保留取消轮次 ID 防重复，保留远端映射。取消终态但尚待持久化的 journal 可以重新取得展示恢复权，不得重放执行。
- FR-6：普通并发仍 session_busy。业务只可在同 owner 已记录的取消清理阶段短暂等待，不靠过期抢占。重启缺停止证据仍 blocked。
- FR-7：正常成功轮次不增加模型、外部请求或逐事件历史查询。取消路径有界。设计或上下文 repr 不记录凭据、路由能力、原始生产日志或载荷。

## 设计与契约变化

增加可选 CustomerRuntimeConfig.confirm_cancellation 和冻结的 CustomerCancellationContext。在原 lease 中包裹 projection：projection 与 client 清理结束后，未完成退出可在有界、屏蔽取消的清理中调用确认器。业务接入检查真实断连标记；异常或非严格 True 不恢复执行。在历史收尾前撤销 bridge。

增加 owner 校验的 CustomerSessionLease 终态取消方法，包含读取运行中 journal、记录取消终态及读取成功或取消的展示。原 complete_turn 成功校验不变。取消路径核对已保存 journal 前缀，追加缺失完整事件、未配对工具取消回执及中断事件，回读验证，确认持久化后才清 pending。复用数据库列，状态契约增加 cancelled。中断明确不是业务成功。既有恢复接口保持只恢复展示、不访问 Host。

SkyEyes 使用内部 loopback 取消接口，以现有服务端生成的 turn 能力及精确远端身份鉴权。先禁止该 ticket 发起新 step，仅取消并等待其已登记 Host 请求，核实任务清理，再收尾该 Host invocation 的未配对调用与中断历史。跨进程共享状态确认禁止继续的终态 step。缺任务或状态不明确不能作为证据。这是业务契约，不是 SDK 网络协议，也不增加客户 BFF 取消接口。外层业务保护只在同 owner 与业务身份的 SDK 收尾已确认后释放。没有客户原 Runtime 修改授权。

已排除删除锁、所有取消均 healthy、TTL 接管、替换会话与把不完整内容标成功的方案：它们允许执行重叠、丢上下文或隐藏不确定副作用。不承诺分布式 exactly-once。

## 任务

- T-1（FR-1–7）：双语设计/组件更新与审查，在修改生产代码或测试前取得具体 SDK 变更的明确批准。
- T-2（FR-2–5）：存储与真实 Runtime 红测，然后实现配置、上下文、清理与取消终态 journal 收尾。
- T-3（FR-1、3、6）：业务断连标记、精确 ticket 的 Host 停止/历史收尾与业务释放；真实 ASGI/HTTP 回归接入强制门禁。
- T-4（FR-2–7）：固定 wheel/receipt、安装版消费回归、SDK 必需门禁及业务 API/native/PostgreSQL 门禁。
- T-5：全部门禁绿色后仅发布授权 PDSA，完成真实取消/追问/历史/APMPlus 验证。客户原 Runtime 零写入。

## 验收与验证

AC-1：同份修复前后测试覆盖响应头前、增量后、工具中取消；两层 owner 收尾后同会话追问才成功。断言任务退出、旧轮无新模型/工具调用、journal 配对、身份保持与普通并发拒绝。
AC-2：确认器缺失/False/非布尔/异常、伪造断连、超时、不合作工具、Host 不明确、身份/run/owner 错误、owner 过期、历史前缀冲突、迟到写入与清理中断均拒绝。保留默认隔离回归。
AC-3：重启后待确认的取消终态 journal 只恢复展示，无 Host/工具请求；运行中崩溃 owner 不能抢占。已完成但展示未确认沿用原恢复语义。
AC-4：专项与 SDK 默认 Python 回归、pre-commit、受影响 lint/type；安装版 wheel 与源码摘要绑定。业务 API/native/PostgreSQL 强制门禁真实执行新增测试。本地替身不证明部署。
AC-5：授权 PDSA 正式 API 中断运行中 SSE，立即以相同身份追问、读历史、核对两条真实 Trace 的执行重叠与取消记录。业务质量与采集验收分别判定。

命令：uv run --extra dev pytest tests/runtime/customer；uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"；uv run --extra dev pre-commit run --all-files。真实 Codex smoke 仅环境准备后单独运行（CODEX_RUN_SMOKE=1、-p no:xdist）。

## 审查、风险与交付状态

review-spec 不可用，已直接审查 owner/期限防护、任务退出顺序、历史前缀、重复取消、服务端配置、兼容与双语一致性。设计已解决一个阻塞项：仅确认器布尔值不足，必须具备 SkyEyes 精确 ticket 的 Host 停止契约和 SDK 独立验证的 Dispatcher/历史条件。用户于 2026-10-29 授权继续按此前具体 SDK 扩展方案实施，批准已在生产代码和测试修改前记录。实现与定点离线验证已完成；默认并行 SDK 回归仍运行。尚无新 wheel 或 PDSA 发布。两进程 Host 任务终止与 ADK 持久化的完整安装消费者及真实端到端验收仍待完成；无法证明时必须拒绝恢复。

接入细化：Host 在 Runner 执行前分配 invocation ID，正常路径不新增历史查询。`CustomerSessionStore.cancellation_settled` 为仍持有业务 Session 的外层保护提供只读的精确 run/身份/engine 确认依据；要求取消终态、会话 idle、无展示待确认及 SDK owner 已释放。该方法不修改占用也不执行请求。


取消时序补充：覆盖完整工具回执正在写入日志时取消，分别在事务提交前、提交中、提交后但尚未对外发布时取消。收尾必须等待原数据库操作停止，保留已提交事件，对回滚后未配对调用明确补写取消回执，不重放工具。存储失败或事务清理未确认时仍不得释放占用。Runtime 将每个已接收的完整事件写入作为独立叶任务持有，防止调用方取消打断它；取消时在清理预算内等待该任务。只有写入成功结束才允许确认；超时、被取消或失败的写入阻止收尾。正常路径保留原数据库调用与有限操作预算；partial Token 事件不创建写入任务。

清理失败补充：租约释放失败不能把正在传播的 `CancelledError` 或 `GeneratorExit` 替换为新异常。ADK 可能向已断开的消费者发布该异常，并永久等待确认。保留取消，只记录固定诊断码；无法确认释放时保持持久化 owner/状态不变。非取消场景的释放失败仍传播。相同真实 Runner 的故障注入回归必须在修改前失败、修改后通过，并证明没有授权后续执行。

## 验证检查点（2026-10-29）

- 取消确认定点：pass，8项（`.codex/cancellation-targeted-v3.txt`）；customer Runtime全部测试：pass，386项（`.codex/cancellation-customer-v3.txt`）。同份修复前失败保留在`.codex/cancellation-red.txt`。
- 受影响Ruff和Pyright：pass，类型错误为零。pre-commit：pass，五项hook；新增未跟踪文件仍须在提交前显式扫描。
- 默认SDK回归：running，`.codex/cancellation-full-v2.txt`；不能记为pass。前次fixture失败和既有非取消retry失败继续保留，retry定点重跑通过。
- 业务跨进程HTTP模型/工具取消：pass，两项定点测试。断言原执行已停止、相同身份/完整历史保留、工具不重放、普通并发仍拒绝。fast诊断结果不能代替完整安装包、API/native/PostgreSQL门禁。
- Host同一服务器ticket的内部延迟工具请求沿用首个invocation ID。收尾前核对原输入和工具输入，已有执行后不伪造缺失输入。外层重复取消保留取消异常，同时只在所有自有任务done后登记停止确认。
- 新wheel、安装消费者、完整业务发布门禁、PDSA真实取消/追问/历史/APMPlus：not_run。客户原Runtime冻结。

## 最新检查点：PDSA 更新暂停

用户已暂停 PDSA Runtime 更新，替代此前发布授权：T-5 和 AC-5 等待后续授权。不进行云构建、Runtime 配置修改、重启或发布。继续本地 SDK 开发、制品核验与隔离的离线消费者门禁。客户原 Runtime 继续冻结。

- 前次 SDK 默认回归（`.codex/cancellation-full-v2.txt`）终态为 7946 通过、1 失败、50 跳过、4 xfailed。保留失败及诊断中断证据，不能算绿色门禁。
- 完整事件写入时取消、清理异常覆盖取消，两项回归分别在对应修改前复现失败。两处修改后，取消确认专项 15 项全部通过（`.codex/cancellation-accepted-journal-green-v2.txt`）。
- 完整 SDK v3 终态为 7888 通过、66 失败：包装器错误设置 `OTEL_SDK_DISABLED=true`，禁用了这些测试所需的内存采集。移除此包装器配置后，同份 66 项失败测试与 15 项取消回归一起通过（81 项）。完整 v4（`.codex/cancellation-full-v4.txt`）现正执行，绑定 1052 个 Python 文件摘要。保留 v3 失败证据，未弱化生产采集逻辑或测试断言。
- 测试关键字参数类型问题已修正。受影响 Ruff、格式与 Pyright 全部通过，类型错误为零；最终 pre-commit 五项 hook 全部通过。此前类型检查失败证据保留。
- 尚未取得新的已提交 SDK wheel、安装消费者结果、完整业务 API/native/PostgreSQL 门禁或线上取消验收，不宣称这些已完成。
