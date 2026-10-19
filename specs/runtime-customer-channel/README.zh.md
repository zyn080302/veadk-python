# runtime-customer-channel

[Counterpart](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.md)

ID: `runtime-customer-channel`; revision: 2026-10-20; status: active.

本组件负责 managed customer Shared HTTP 公开客户端，不执行工具、不创建第二个模型循环、不选择业务身份。调用者以异步上下文使用 `CustomerChannelClient`，通过 `capabilities()` 查询能力、`create_session(app_name, user_id, session_id)` 显式建会话，再进入 `run(CustomerRunRequest)` 消费 `events()`、调用 `submit_result()`。一个可信业务会话使用一个客户端，续轮复用 HTTP 池和亲和信息。本阶段尚未实现 `Agent(runtime="customer")`。

| ID | 范围 | 合同 |
| --- | --- | --- |
| CON-1 | 协议 | `studio-tool-channel/1`；`/managed/harness/studio-channel/v1/{capabilities,http-runs}`；`/managed/harness/studio-channel/v1/http-channels/{channel_id}/messages`；`/managed/apps/{app}/users/{user}/sessions`。建会话使用 `sessionId`，运行使用 `session_id`。 |
| CON-2 | 快照 | `CustomerTool` 明确 source 为 `mcp/studio/knowledgebase`；默认 600000 ms，最大 1800000 ms；摘要对完整清单排序并排除 null。最多 64 工具、16 Skill。`CustomerSkill` 包含 instructions/references/assets，scripts 必须为空。`CustomerRunRequest` 增加完整 secret `agent_config` 与 `environment`、每轮新的 run/channel/scope 和一条新增用户消息；不重放历史、不传 environment context。 |
| CON-3 | 生命周期 | 一个客户端绑定一个 (app,user,session)，最多一轮运行，控制面请求不能与运行或其他控制面请求竞争。调用者负责持久化和关闭客户端。只有成功 `run.completed` 且此前无错误事件、无待回传工具才表示成功；error/cancelled/EOF/非法事件抛带固定 code 的 `CustomerChannelError`。本地映射及 HTTP 状态不表示远端已持久化。 |
| CON-4 | HTTP | 可信 HTTP(S) 入口，不含 userinfo/query/fragment；明文 HTTP 仅允许本机回环测试。明确请求头 provider，不使用环境代理、不重定向。`X-Session-Id` 为私有不透明亲和值，由合法响应更新，不进入事件或 state。单次 30 s、整轮 165 s、清理 5 s，可配置正有限期限。默认响应/事件上限 1 MiB、运行正文上限 2 MiB。不重试，包括结果不确定的工具回传。 |
| CON-5 | 工具 | 暴露 `tool.call` 前核对 run/scope/catalog/name/executor/schema/deadline；最多 64 在途、每轮最多 1024 个不同调用。重复 ID 失败；tool.cancel 使待回传失效。HTTP 前消费结果，取消或传输失败不能重放。执行取消由后续适配器负责，transport 暴露 tool.cancel。 |
| CON-6 | 清理 | 终态前退出上下文，清理期限内最多尝试一次 run.cancel，再关闭响应，即使取消未送达。清理底层任务有时间上限，不创建无限队列。正常完成不取消。整轮期限包含下游消费时间，取消异常保持取消语义。 |
| CON-7 | 兼容 | 独立于普通 Studio 清单；现有分发、App、默认值、callback 和依赖不变。公开客户端配置不得从不可信请求头填充。凭证和远端正文不进入诊断异常。测试使用替身配置和 HTTP，真实入口验收单列。 |

验证：`tests/runtime/customer/` → CON-1–CON-7; `.github/workflows/harness-sidecar-release-gate.yaml` 执行相同合同测试。

设计与证据：[customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.zh.md).

```python
from pydantic import SecretStr
from veadk.runtime.customer import CustomerChannelClient, CustomerRunRequest

async def invoke(endpoint, header_provider, full_config: SecretStr, user_id, session_id):
    async with CustomerChannelClient(endpoint, headers=header_provider) as client:
        await client.capabilities()
        await client.create_session("managed_example", user_id, session_id)
        request = CustomerRunRequest(
            app_name="managed_example", user_id=user_id, session_id=session_id,
            agent_config=full_config,
            new_message={"role": "user", "parts": [{"text": "Hello"}]},
        )
        async with client.run(request) as channel:
            async for event in channel.events():
                # Forward validated events to the owning adapter, without logging payloads.
                yield event
```

调用者提供 Host 支持的完整配置和已授权入口；该片段本身不配置或调用模型。仅新会话调用创建接口；续轮复用客户端和会话，重新创建 CustomerRunRequest。工具和 Skill 须显式提供，并发工具执行和取消由适配器负责，不能记录请求/事件正文。复现本地离线证据使用所链接 PRD 的命令；CI 在隔离替身环境运行 `python -m pytest -q tests/runtime/customer`。


## 持久 Runtime 集成新增接口（2026-10-20）

`restore_session(app_name, user_id, session_id, affinity=SecretStr(...))` 在任何 HTTP 前一次性绑定新客户端。`session_exists(...)` 只检查该远端会话并返回布尔值，仅 HTTP 404 代表缺失，不枚举 Session 或返回历史。构造参数 `on_affinity` 为可选异步 callback：新私有亲和值保存后才替换当前值、允许后续请求构造 Header。callback 失败后客户端固定报 `affinity_persistence_failed`，取消仍传播。`aclose()` 清除 callback 和私有数据。这些接口为增量扩展，已有客户端不强制使用持久存储。


## 重复取消清理 (2026-10-20)

CON-6: run 取消、响应关闭与连接池关闭使用有界且明确拥有的底层任务，防御重复直接取消。无无界队列；原生成器与 AnyIO scope 保持原任务。清理后仍传播调用方取消。

[设计](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.zh.md)
