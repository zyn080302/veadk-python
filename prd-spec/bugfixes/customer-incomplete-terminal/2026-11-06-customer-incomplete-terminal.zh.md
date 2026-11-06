# 客户未完成终态展示

[English](2026-11-06-customer-incomplete-terminal.md)
Change ID: customer-incomplete-terminal；日期：2026-11-06；状态：implemented。

## 背景、目标与边界
实际Host恢复回调序列化skyeyes_result，status为incomplete并含两个固定reason之一；events.py丢掉标识，业务前端将普通终态文本视为成功。HTTP200、EOF及turn_complete只证明传输结束，不证明业务成功。原事故root_cause_event仍null；确认的投影机制不冒称原案因果。
用户通过任务书明确授权隔离F04 SDK/SSE/历史/blocks修复；主负责固定制品、合入和PDSA，BugFix2拥有准入/恢复。不改共享SDK，不部署/push/付费模型MCP/远程shell，不改预算/来源校验。

## 场景、设计与契约
FR-1：只保留新建skyeyes_result对象，严格两个键status: incomplete及reason: model_tool_protocol_error或host_turn_budget_exhausted。非法保留字段报固定invalid_result_status；不复制任意reason、身份/state/auth或私有字段。元数据双别名歧义继续拒绝；无关元数据继续排除。
FR-2：标识只允许非partial、显式turnComplete=true的model事件，内容为非thought纯文字、空model parts或无content。工具、用户echo、thought、draft和非终态标识均失败。无正文标识作为真实暂存final，仍在dispatcher成功/ACK/cleanup之后释放；拒绝额外final或晚到标识。
FR-3：传输终态/journal完成与业务失败分别判断。标识落入持久化、业务SSE/历史/前端投影；保持正文/usage/工具与用途标识增量前缀。已收尾的incomplete不改成永久blocked；正常完成和新invocation保持独立。
顶层error会把有效Host停止答复变成SDK通道失败，丢公开提示并影响恢复；复制全部metadata违反隔离，因此选择受限展示标识。API、配置、依赖和数值限额不变；spec CON-2/CON-5/CON-8拥有新契约。

## 任务、验收与审查
T-1/AC-1（FR-1）：通过真实dispatcher/序列化加同份SDK红测，覆盖别名、严格校验、本地身份/复制隔离。
T-2/AC-2（FR-2）：覆盖无正文/空终态、提前增量、终态屏障、取消及不兼容/晚到标识，再最小修改events.py。
T-3/AC-3（FR-3）：真实安装SDK的业务HTTP/Runner/journal/历史与前端SSE/回放/浏览器回归，正常下一轮对照。业务测试登记标准/B14精确入口及catalog；SDK已有Harness tests/runtime/customer必跑，前端进入npm test/check。
T-4：执行受影响customer/Runtime门禁、pre-commit、业务入口、前端检查；交完整内部包及精确delta/source绑定红绿。主组合完整门禁与线上PDSA由主/Testor负责，不算本worker已验。
review-spec不可用，直接审查已核双语等价、有限白名单、终态顺序、取消、本地身份、兼容及可测性，无阻塞。用户2026-11-06任务授权覆盖该范围；明确固定cd3becf5/4eb18769基线优先于远端同步。SDK Studio/生成器无变更；前端消费者属于独立SkyEyes仓库。
风险：旧安装SDK仍丢标识，交付前由主集成不可变制品；未来未知reason须适配契约，不能复制原值。原事故根因与原题真实验收按范围not_run。实际执行证据见下文。

设计审查补充：实际Runtime回归证明，合法无正文终态投影仍被session_store.complete_turn的正文要求拒绝。仅用同一严格标识校验扩展正文条件；保持owner/error/interrupted/turn_complete/final/工具检查。直接journal回归拒绝缺失/非法标识、thought/工具/非终态，核展示确认与下一轮。更新session-store CON-6。此必要F04持久化增量属于已授权SDK/历史范围，不改业务准入实现；实现前已审查，无阻塞。

验证2026-11-06：同份最终SDK测试SHA，20失败/6通过→26通过；完整受影响customer+Runtime关闭479通过/22.246秒。实际安装业务3项及真实标准/B14入口：修前5外层测试含7子失败/1错误→5通过/23.202秒，零错误/跳过。相邻诊断/模型失败/F07业务回归19通过/12.824秒，零错误/跳过。前端98单测及9本地Chromium浏览器检查通过；独立HTTP200标识浏览器同份2红→2绿。build/typecheck、quick859及SDK五hook pre-commit通过。初次浏览器夹具要求刷新后仍有未持久化partial前缀，仅修正新增模式预期，核 live前缀、持久化未完成提示和下一次发送，原模式保持。完整组合/线上按分工仍not_run，归主/Testor。[绑定源码摘要](summary.json)。
