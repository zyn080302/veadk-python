# Customer 展示事件发布顺序

[English](2026-10-21-customer-display-order.md)

变更 ID：customer-display-order。创建/修订：2026-10-21。状态：approved。

## 证据与范围

SkyEyes Devbox 对照 `2346323d4bf670f7`、SDK `0bf87db3` 在基线第二轮返回 `display_conflict`。已完成日志和 ADK 展示各有七条事件，无重复 ID，按 ID 核对内容一致，但顺序不同。这证明顺序冲突，尚未证明产生机制。完整基线/Jev 对比和回答质量仍未完成。

`CustomerRuntime._saved_prefix` 正确要求内容完整、顺序一致。`DatabaseSessionService` 按 timestamp 再按 ID 回读。本地工具调用事件在执行前创建，执行后才随回包一起发布；等待期间可能发布 Host 展示事件；最终答复也先创建、后发布。因此创建时间不一定代表发布顺序。实现前必须用真实 SQLite/ADK 回归证明该机制；没有证据不能将实测失败归因于时间精度。

目标：新发布的 customer 事件经数据库回读后保持日志顺序，已完成轮次可以继续或恢复，且不重复执行工具。不包含：修改 ADK 存储结构、弱化内容/前缀校验、修复已有冲突历史、重放工具、修改 MCP schema、生产发布，或宣称性能/质量已经通过。

## 需求与设计

- FR-1：Host 展示与待完成本地工具交错时，通过真实 `DatabaseSessionService` 保存并回读后，持久事件顺序与发布/日志一致；第二轮正常执行。
- FR-2：在持久日志追加和 yield 之前，只赋值一次本地展示时间。使用当前本地时间，并按 ADK 数据库微秒精度严格晚于此前持久事件，覆盖时钟不变和回退。此字段表示本地发布时间，不表示工具执行耗时。partial 事件保持临时展示。不改变 ID、内容、动作、用量或已记入日志的事件。
- FR-3：完整有序内容核验、重复/内容变化/缺口拒绝、租约、终态/ACK/清理及取消行为不变。恢复只追加真实缺失后缀，使用日志中已有时间，不访问 Host 或工具。已有乱序历史仍报冲突。
- FR-4：验证服务重启、缺失后缀恢复，以及固定新 wheel 下原 Devbox 五轮两组对照。完整回答质量和净性能收益独立评判，不以此正确性修复替代。

合同归属：[runtime-customer](../../../specs/runtime-customer/README.zh.md) CON-4/CON-5。投影和本地工具生产者接口不变；Runtime 是同时负责日志和输出事件的统一位置。不在各生产者各自计时、不在保存后排序历史、不将无序集合当作完整前缀。不改变依赖、配置、鉴权、权限、公开签名或数据结构。存储需保留微秒顺序；其他时间分辨率须另行验证。时钟修正只在本地进行，使用常量空间，不等待或调用网络。

## 任务与验收

| 需求 | 任务 | 验收 | 验证 |
|---|---|---|---|
| FR-1 | T-1：改生产代码前新增真实数据库交错回归 | AC-1：旧代码因同内容乱序而失败；修正后正常续轮 | `uv run --extra dev pytest tests/runtime/customer/test_display_order.py` |
| FR-2/FR-3 | T-2：在 `runtime.py` 赋发布时间 | AC-2：相同/回退时钟与重启通过；保留完整内容和负向检查 | 同一定向测试，加 `tests/runtime/customer/test_runtime.py` |
| FR-3/FR-4 | T-3：消费者门禁、审阅与双语同步 | AC-3：customer/Harness 门禁、全仓 SDK 回归、pre-commit 通过 | `uv run --extra dev pytest tests/runtime/customer tests/test_harness_sidecar_release_gate.py`; `uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"`; `uv run --extra dev pre-commit run --all-files` |
| FR-4 | T-4：固定 wheel 与业务验收 | AC-4：安装 Runtime 门禁及 Devbox 五轮对照重跑，保留原失败 | SkyEyes `scripts/check.py --scope native-runtime --sdk-installed`，使用已有固定源码路径；`scripts/devbox_customer_live_pair.py --dependency-base <verified-sdk> --case ambiguous --confirm-followup --followup-neighbors` |

现有强制 Harness 发布工作流执行整个 `tests/runtime/customer`，新增回归自动纳入。离线测试使用合成数据、真实本地数据库与 Host 替身，不访问外部模型或凭证。Devbox 验证沿用已授权的隔离包装器，与离线证据分开记录。

## 审阅与交付

直接设计审阅（没有 `review-spec`）：范围与归属清楚、不绕过内容检查或自动重放、公开接口不变、真实存储覆盖原来遗漏的层级。双语需求和标识共同核对。用户持续目标已授权 SDK/Runtime 修正与 Devbox 迭代；属于范围内常规实施，不另称用户单独审批本设计或批准发布。T-1 先证明顺序机制；证据矛盾时先修订设计，再做 T-2。

customer/发布合同定向回归：`pass`（357项，30.04秒；整体31.603秒），含8项新回归。5项pre-commit与双语标识/引用检查：`pass`。全仓回归：`pass`（7917 passed、50 skipped、4 xfailed、6 subtests passed；424.04秒，整体425.315秒；2 workers）。跳过项不证明对应能力。第一次命令显式加载未安装的外置subtests插件，在收集测试前失败；pytest 9 已内置该能力，修正命令取消此外置插件。保留失败启动记录，不计为产品回归失败。未宣称正确性、制品、部署恢复或性能成功。剩余风险：已有冲突会话仍需专门核对恢复；测试 ADK/SQLite 之外的粗粒度时间存储未验证；跨轮系统时钟跳变也可能影响 ADK 自己的用户/工作流事件，这些事件不归本 Runtime 管理。

T-1 证据：旧 SDK 回归失败（1 failed，15.58 秒），真实数据库重开后按 ID 完整内容一致、有序 ID 不一致。创建/发布交错已证明可造成此类故障；未重建旧实测的具体调度。继续 T-2，原完整内容核验不变。

业务源码模式集成：`pass`，11项及真实进程重启、身份/历史保留和不重复付费查询通过。使用本次源码改动，不代表新wheel安装或真实供应商验收。T-1/T-2/T-3、AC-1/AC-2/AC-3完成；固定wheel和Devbox的T-4/AC-4待完成。验证绑定 `0bf87db3` 加本次改动：{"veadk/runtime/customer/runtime.py": "8b257bf0e3e8867dcfa858b3436195804586b2ed937653587938f6cf313a9ec1", "tests/runtime/customer/test_display_order.py": "cdfa614cdc65bc85b7caac27d7c375e28ef3e233e2f251c2fefce1e2bab0c4d1"}。
