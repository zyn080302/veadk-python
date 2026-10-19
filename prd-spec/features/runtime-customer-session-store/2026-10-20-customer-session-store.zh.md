# customer 持久会话占用

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer-session-store/2026-10-20-customer-session-store.md)

变更 ID：runtime-customer-session-store。创建/修订：2026-10-20。状态：implemented。

## 证据与范围

现有 customer 客户端、调度器和事件投影器要求调用者提供持久互斥。进程内锁在重启后消失，可能导致已执行过工具的轮次再次提交。本阶段使用已有 SQLAlchemy AsyncEngine 依赖，实现正式 Runtime 所需的持久层。Runtime 注册、HTTP 客户端亲和恢复、callback 桥和业务装配仍属于后续蓝图任务；不宣称本阶段完成迁移。

## 需求与设计

| 需求 | 任务 | 验收 |
|---|---|---|
| FR-1：固定身份和引擎绑定 | T-1：存储与公开导出 | AC-1：独立连接竞争仅一个持有者；用户/引擎隔离 |
| FR-2：远端提交前预留调用 | T-2：claim/begin/release | AC-2：重复 ID、过期持有者和不确定轮次不可重跑 |
| FR-3：持久且有界的本地展示记录 | T-3：append/complete/read/ack | AC-3：重开数据库可恢复展示，不执行工具 |
| FR-4：固定错误与私有亲和值 | T-4：合同、回归和门禁 | AC-4：诊断不包含身份、SQL 参数或亲和值 |

使用三张私有表，与 ADK Session.state 分开。短事务通过版本条件更新互斥，不长期占用事务。显式初始化表。调用者提供 AsyncEngine，关闭 SQL 回显并隐藏参数；负责数据库期限、连接池、加密与关闭。不新增依赖、网络调用、凭证加载或遥测。

状态为 idle → running → completed → idle。claim 有明确期限，不自动接管过期占用；running、blocked 或过期未释放状态需要恢复。running 时释放会阻止后续执行。completed 在释放/重启后仍可恢复展示，调用者核验 ADK 保存后明确确认，才能开始下一轮。远端提交前调用 begin_turn，重复调用不重新提交。只记录可信投影后的完整 Event，限制数量和字节；完成要求明确最终文本 Event，并由调用者确认远端成功、工具 ACK 和清理结束。

维护合同见 [runtime-customer-session-store](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-session-store/README.zh.md)。影响文件：/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/session_store.py、/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/__init__.py、customer 测试和 Harness 发布门禁。不改变前端、依赖、CLI 或部署。

## 测试、风险与审查

先写失败测试。临时 SQLite 文件和独立 AsyncEngine 覆盖竞争、重启、取消、过期、重复调用、限制与脱敏错误。执行 `python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer`、SDK 扩展回归和既有 pre-commit。生产 PostgreSQL、公开 Runtime HTTP 与客户原 20 题仍为 not_run；方言编译不等于真实验收。

本层不鉴权传入身份，不过滤正文密钥，不强停非合作工具，不承诺分布式 exactly-once。不确定副作用保持阻塞。不提供强制解锁、后台续租或自动删除历史；保留策略与专门恢复流程由业务负责。

review-spec 不可用，直接审查接口、状态、并发、取消、错误边界、安全与双语一致性。已否决自动过期接管及未确认展示保存就恢复执行。依据用户既有蓝图实施和阶段 commit/push 授权推进，不包含合并/部署。设计在代码/测试前审查通过。验证结果如下。

实现前补充审查：事件独立成行，并维护每轮计数；避免每次追加都重写整轮记录。

## 验证记录（2026-10-20）

基于 SDK `5c95434465f8acb2373b46fbefbecc7196124f0f`；本持久层阶段 T-1–T-4、AC-1–AC-4 已完成。失败基线为 CustomerSessionStore 未导出导致的一次收集错误。最终新增 37 条测试。customer/生命周期/门禁套件 232 项通过，23.37 秒；SDK 全仓 7764 项通过、50 项跳过、4 项预期失败，另 6 个子用例通过，399.99 秒、两个 worker，排除显式 Codex/Pi smoke。原 pre-commit 五项、暂存凭证扫描、Python 3.10 语法、双语标识与八条绝对链接通过。此前一次覆盖率运行停滞后已停止，不宣称取得覆盖率结果。

全仓命令：`python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`。测试使用临时 HOME/SQLite 并禁止外网。工具往返组合实际客户端/调度器/投影器，使用 MockTransport；通过不确认展示保存模拟保存失败，不是公开 Runtime、实际 ADK 保存异常、生产 PostgreSQL 或真实客户验收。源码摘要及最终提交绑定见[证据](/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/docs/project/evidence/customer-session-store-verification.json)。没有部署或合并 main/master。
