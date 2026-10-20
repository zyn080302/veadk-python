# customer 原生通道

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.md)

变更 ID：customer-native-channel。创建/修订：2026-10-20。状态：implemented；本机验证通过，已推送用户独立分支。

## 背景与范围

现有 CustomerRuntime 仅支持 managed Shared HTTP。固定 customer 候选 588179428751d6f311ec9cad2b623f2fd257d1d7 与 Host 4d7c505940fe183576f36340cf063c06566ab843 提供 /run_sse+harness_config 及 /apps Session API。Host 返回延迟 functionCall 后结束当前 HTTP，下一次请求回显 functionResponse 输入。ADK 把延迟调用视为单步 final，但这不等于业务整轮完成。Host 不承诺 affinity、执行器版本检查或客户端工具期限。此前固定 Host/MCP 验证使用测试驱动，不是 CustomerRuntime。

目标：通过现有公开 customer Runtime 和标准 Harness 接入此协议，保留本地异步工具/回调、持久整轮互斥、展示日志和取消。此阶段不代表整体适配目标完成：二进制 Skill/附件、账号共享配额/冷却、异常执行恢复、生产数据库/身份和客户原题 A/B 仍是必须继续的工作。本阶段不切换默认入口，不合并或部署。

## 要求与场景

- FR-1：CustomerRuntimeConfig 和 CustomerChannelClient 新增仅关键字 protocol="shared"|"native"，默认 shared。Shared 报文和绑定摘要保持不变；配置相同时 native 绑定仍不同。native agent_config 是包含非空 JSON AgentConfig 对象的 SecretStr；environment 必须为空。HTTP 前拒绝无效协议/配置，不记录配置或校验输入。
- FR-2：native 使用精确 /apps Session GET/create 和 /run_sse。不调用 Shared 能力/取消路由，不伪造 affinity；可持久化实际返回的可选 affinity。工具序列化去掉 Shared 专用 source；skills/thinking 放在 harness_config.run_config。仅发送本轮输入或对应工具回包，不发送下载的历史。
- FR-3：在暴露可执行工具调用前校验所有事件。延迟 ID 必须恰好对应本事件中本地声明的工具调用；验证名称、参数及本地声明版本/期限。Host 内部工具只展示。重复 ID、部分工具片段、畸形事件、未请求的用户回显和 final 后内容均失败。沿用有界事件/调用限制。延迟工具优先于任何 final 判定。
- FR-4：每个延迟调用只收一个回包，序列化后只消费一次。当前 HTTP EOF 且全部结果齐备才发送下一请求。submit_result 必须等到后续流回显完全一致的有序输入（ID、名称、JSON 结果）并通过事件校验后才成功。缺失/变化/重复回显或消费不明均失败且不重试；本地暂存不是 ACK。JSON 字典原样保留，其他 JSON 结果使用 result 包装；失败发送固定错误对象。不把凭证或回包缓冲持久化到轮次之外。
- FR-5：一个整轮期限覆盖所有 HTTP、执行队列、结果等待和流消费。单次操作限制约束响应头等待，沿用流空闲超时。取消撤销全部回包权限，并用既有有界、可抵抗重复取消的清理关闭实际流/连接池；原生没有取消 API。不承诺远端回滚或崩溃后 exactly-once。EOF 没有最终回答或仍有未完成 Host 工具均失败；校验 EOF、结果 ACK 和本地清理之前不发布 final。
- FR-6：max_concurrency 限制执行器执行，不包括之后等待 ACK。当延迟工具多于执行名额时，全部工具在限制内执行并提交一个有序批次；超时/背压触发取消而非死锁。最多 64 个待回包、1024 个总调用；单个回包及合并请求大小均受限。
- FR-7：标准 Harness /run 与 /run_sse 使用实际 Runtime、原生异步工具桥和持久会话映射。首轮 GET/create，续问不下载历史。未完成执行继续被 store 阻止，已完成展示恢复保持既有行为。既有 Session 切换协议在 Host I/O 前失败。

## 设计与职责

私有原生通道组合现有 CustomerChannelClient HTTP 池和 dispatcher，不继承 Shared 报文状态机，不复制模型循环。原生序列化器仅转换服务端配置。原生通道驱动多个 HTTP 步骤，转换为已有内部 run.event/tool.call/run.completed 信封；在调度前使用现有严格事件 projector 校验，正常输出再以调用方本地身份投影。这一有界额外校验同时保护独立通道调用方和 Runtime。

只有精确核对本地工具后才规范化 longRunningToolIds。已校验的工具结果用户回显改为私有助手 author 以供展示投影；保留事件 ID/内容，继续忽略不可信远端状态。初始一致文本回显仍可选，不改写未经验证的用户内容。所有待确认结果只有在回显验证后才获得真实 ACK。本地工具日志仍是回调状态的唯一来源。Shared 公开报文和投影规则不变。

复用 store 表结构与副作用前登记，只在 native 配置绑定中加入协议。无需扩展公开 Session 名称（原生 Host 接受 managed_*）。dispatcher 在等待 ACK 前释放执行名额，保持期限、错误优先和所属任务清理。无新依赖或前端代码。

受影响源码：veadk/runtime/customer/config.py、client.py、native_channel.py（新增）、runtime.py、dispatch.py。测试：tests/runtime/customer/test_native_channel.py（新增）、既有 customer/Runtime/Harness 测试，以及已授权业务工作区中的固定 Host 集成。组件合同：runtime-customer CON-1/3/4、runtime-customer-channel CON-1/3/4/5/6、runtime-customer-tool-dispatch CON-1/4、runtime-customer-adk-events CON-2/4/5。store 表结构不变，调用方绑定和不确定执行约束继续适用。

## 任务与验收

| 要求 | 任务 | 验收 | 证据 |
| --- | --- | --- | --- |
| FR-1/2 | T-1：序列化/配置/路由 | AC-1：原生路径/配置、无效输入、Shared 默认/绑定不变 | pass：33 项专项与固定 Host HTTP 联调 |
| FR-3/4 | T-2：有校验的跨 HTTP 状态机 | AC-2：多轮工具、Host 内部工具、精确 ACK、畸形/重复/迟到/消费不明失败 | pass：33 项专项与固定 Host HTTP 联调 |
| FR-5/6 | T-3：期限和有界调度 | AC-3：工具多于名额、延迟回显、超时/取消/清理/背压不重放且不误报成功 | pass：33 项专项与固定 Host HTTP 联调 |
| FR-7 | T-4：Runtime/Harness 集成 | AC-4：本地持久化、同 Session 续问、协议隔离、原生回调；实际固定 Host 本机 HTTP | pass：33 项专项与固定 Host HTTP 联调 |
| 全部 | T-5：核对与交付 | AC-5：双语审查、专项/全仓回归、原 pre-commit、独立分支推送 | pass：全仓回归、原 hooks 与独立分支推送核验 |

通过隔离本机包装器执行：python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer。最终共享合同回归使用该包装器加 -p xdist.plugin -n 2 -m "not codex_smoke and not piagent_smoke"。原 pre-commit：python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_native_precommit.py。包装器隔离 HOME 和替身；测试不得使用实际凭证或非本机服务。固定 Host 使用独立锁定环境和业务门禁，不能静默互换 SDK/Host 依赖。执行后记录实际源码版本和命令。替身通过不代表部署可用。

## 审查、授权与风险

review-spec 不可用，已直接审查接口职责、别名歧义、真实 ACK、工具参数校验、有界内存、跨步期限、取消和双语等价性。发现：持有执行名额等待 ACK 会导致批次死锁，以 FR-6 解决；ADK 的长时 final 不是业务终态，以 FR-3/5 解决；缺失回显不能当成提交成功，以 FR-4 解决。无阻塞设计问题；实际 Host 集成仍须验证事件格式。

用户授权：已有按蓝图完成适配/性能优化及验证阶段提交/推送的要求覆盖本实现，不新增审批、合并或部署权限。SDK 仅推用户 fork skyeyes-user/feat/skyeyes-harness-20261020。新协议显式启用。关闭原生 Host 连接不证明回滚，不确定轮次继续阻止执行，后续恢复仍需完成。此变更不声称完整 Skill/附件或真实云/客户验收。本机门禁与独立分支推送已核验；不声称生产交付完成。

## 验证检查点

父提交 5a01c438 加本次改动：最初 21 项用例在实现前全部失败（13.99 秒）。JSON 标量类型和多事件工具批次回归另复现两项失败。POST 前取消/过期复现两项失败（3.51 秒），已在发送前检查修复。最新专项 33 项通过（4.47 秒）。最后的发送前检查修正之前，customer/清理/Harness 回归 349 项通过（32.28 秒）。固定真实 Host 与实际 SDK Runtime 分别使用独立依赖环境，三项测试通过，覆盖标准 /run 和 /run_sse、原业务 MCP、回调状态、同 Session 续问、真实 SSE 断线后阻止不确定会话且不重放工具。模型/MCP 是本机确定性替身，不声称云端/客户验收。最终全仓门禁通过：7864 passed、50 skipped、4 xfailed、6 subtests passed（404.24 秒，2 workers），覆盖最后发送前检查修正；跳过/预期失败不作为对应能力已通过的证据。

最终原 pre-commit 五项通过；38 条绝对文档链接、双语 FR/T/AC/CON 编号、diff whitespace 通过。已再次 fetch 官方 main（402a3da9）和用户独立分支（5a01c438），均为 HEAD 祖先，已同步基线未变化。运行时代码未在最终全仓回归后修改。

实现提交 `bcadbbb3965270485dfdba4b5e0ae1a80a8100f3` 已推送到用户 fork 的 `feat/skyeyes-harness-20261020`，`ls-remote` 与本地完全一致。本次文档收尾不修改已验证源码；新业务固定 wheel、完整业务装配与真实客户验收继续推进，未合并或部署。
