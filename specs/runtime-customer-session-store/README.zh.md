# customer 会话存储

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-session-store/README.md)

组件：runtime-customer-session-store。修订：2026-10-20。状态：active。
所有者：/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/session_store.py。测试：/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer/test_session_store.py。

- CON-1：`CustomerSessionStore(engine)` 复用调用者的 AsyncEngine，关闭 echo 并设置 hide_parameters=True。`initialize()` 显式创建独立会话/轮次/事件表。SQLAlchemy 异常统一为 `store_unavailable`；取消继续传播。不隐式访问网络或初始化表。
- CON-2：`claim(local_identity, engine_id, remote_app, lease_seconds=180)` 接收可信 app/user/session 三元组，存储其摘要，不负责调用者鉴权。engine_id 是服务端配置版本；remote_app 接受 managed_* 或 studio_debug。远端 user/session 首次随机生成，拒绝后续改绑。未过期占用是 `session_busy`，过期未释放是 `session_recovery_required`，不自动接管。
- CON-3：状态为 idle → running → completed → idle。每次修改原子检查 owner、revision、期限。`close()` 幂等；running 释放变 blocked，过期释放不能恢复执行。completed 可释放、重新占用以恢复展示。不提供强制解锁、自动续租或重试。
- CON-4：`begin_turn(invocation_id, input_digest)` 在远端提交前预留 ID，返回稳定 run/channel/scope。重复调用是 `duplicate_turn`，输入不同是 `invocation_conflict`。调用 ID 保留到业务明确清理历史。
- CON-5：`append_event(event)` 在外层展示/保存前记录可信投影后的本地完整 Event，拒绝 partial。默认每事件 1 MiB、每轮 4096 事件/16 MiB，可配置为有限正数。相同 ID/内容幂等，内容不同是 `event_conflict`。调用者不得导入远端 actions/state。
- CON-6：`complete_turn()` 须在确认远端成功、工具 ACK 和清理后调用，要求最后一个 Event 为 turn_complete=True、无工具的最终文本。`read_completed(invocation_id)` 只返回展示 Event，不执行工具。`acknowledge_display()` 在核验 ADK 保存后调用，允许下一轮并保留去重记录。
- CON-7：`set_affinity(SecretStr | None)` 保存私有路由状态；lease、binding、turn 的 repr 不显示内容。亲和值不进入普通 state、Event 或日志。不是正文密钥过滤器。调用者负责鉴权、加密、安全日志、保留策略和引擎关闭。
- CON-8：租约期限覆盖执行、清理和保存。不确定或过期轮次需要业务核验并使用新会话或专门恢复流程，不可猜测重跑。跨进程互斥不保证外部副作用 exactly-once。

SQLite 重启/竞争测试验证本地持久行为。PostgreSQL 集成与正式 Runtime/业务装配尚未验证。不修改前端/CLI/部署。设计和实际验证见[变更记录](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer-session-store/2026-10-20-customer-session-store.zh.md)。

租约提供 `pending_invocation_id`，重启后可定位待恢复轮次。每个事件独立成行，追加不重写已有事件。操作期限包含等待本地写锁；序列化前拒绝非 JSON state 和交互鉴权/确认事件，每次数据库操作都会拒绝可能打印行内容的 DEBUG 日志配置。

以下示例在重启后定位已完成展示，不会启动 customer Runtime。代码在 async 函数内运行。

```python
from sqlalchemy.ext.asyncio import create_async_engine
from veadk.runtime.customer import CustomerSessionStore

engine = create_async_engine(
    "sqlite+aiosqlite:////tmp/customer-session-example.sqlite",
    hide_parameters=True,
)
store = CustomerSessionStore(engine)
await store.initialize()
async with await store.claim(
    ("example_app", "user_a", "session_a"),
    engine_id="customer-v1",
    remote_app="managed_example",
) as lease:
    if lease.pending_invocation_id is not None:
        events = await lease.read_completed(lease.pending_invocation_id)
        # Persist/deduplicate events in the local Session before acknowledging.
        # Incomplete turns raise instead of permitting remote replay.
    # Only after verified display persistence: await lease.acknowledge_display()
await engine.dispose()
```
