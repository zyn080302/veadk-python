# 原生 SSE 正文超时修复

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-native-stream-timeout/2026-10-21-customer-native-stream-timeout.md)

变更 ID：`customer-native-stream-timeout`；创建/修订：2026-10-21；状态：approved（实现与验收待完成）。

## 证据与范围

`CustomerChannelClient` 用 `operation_timeout` 配置 HTTPX，原生 `_step` 继承该设置并用于正文读取。真实本机 HTTP 复现中，正文延迟 0.35 秒、整轮 2 秒、单次操作 0.1 秒时约 0.178 秒失败；仅将单次操作调到 1 秒则成功。MockTransport 不执行 socket 读取超时。此缺陷已证实；是否解释下游真实模型失败，须待新安装制品复测。

目标：允许原生模型流在整轮期限内等待。非目标：模型重试、自动重放、新增环境变量、修改 Shared 协议、部署或宣称性能提升。公开签名与默认值、身份、工具、ACK 校验及持久化保持不变。

## 需求与设计

- FR-1：响应头及时到达时，原生首段正文或分片间隔超过 `operation_timeout`，但在 `turn_timeout` 内，应正常完成。
- FR-2：连接、写入、连接池和响应头获取保留短操作期限。精确会话 JSON 控制操作仍整次受短期限约束。
- FR-3：既有整轮期限统一覆盖全部原生 HTTP 步骤、本地工具等待及下游消费。超时和调用者取消关闭流、结束调度任务，不重放运行或结果。
- FR-4：延迟工具结果回显仍须精确匹配后才 ACK；验证最终输出前不成功。错误与超时不得伪造成功或用量。

仅在原生 `/run_sse` 的 `build_request` 传入 `httpx.Timeout(operation_timeout, read=None)`。既有包围 `send(stream=True)` 的 `fail_after(operation_timeout)` 限制响应头获取，包括部分响应头。正文读取受既有外层整轮期限约束。没有外层期限时 `read=None` 不安全，因此改动仅限由 `_native_run` 管理的 `_NativeChannel._step`。连接/写入/连接池保持有限期限。不自动重试，不新增任务、状态或存储。短 JSON 与 Shared 请求不变。将所有单次期限加大的方案会削弱控制操作保护，且仍保留隐式流期限，因此不采用。

合同正本：[runtime-customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.zh.md)，CON-4/CON-6。消费方：[runtime-customer](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)，CON-4，引用正本的原生流期限语义。不修改前端、云资源、表结构、权限或依赖。测试仅合成本机 HTTP，无凭证、外部调用或用户状态。

## 任务与验收

| 需求 | 任务 | 验收 | 验证 |
| --- | --- | --- | --- |
| FR-1/FR-4 | T-1：修改代码前增加真实 HTTP 回归 | AC-1：首段正文、分片间隔、多步骤 ACK 在修复前失败、修复后通过 | `uv run --extra dev pytest tests/runtime/customer/test_native_stream_timeout.py` |
| FR-2/FR-3 | T-2：限定各超时范围 | AC-2：慢响应头/控制操作仍失败；整轮期限/取消关闭且不重放 | 同一回归文件与原 customer 测试 |
| FR-1–FR-4 | T-3：实现请求超时覆盖 | AC-3：customer/消费方合同及发布检查通过 | `uv run --extra dev pytest tests/runtime/customer tests/test_harness_sidecar_release_gate.py` |
| FR-1–FR-4 | T-4：同步与验证 | AC-4：分别记录全仓回归、pre-commit 与制品消费方验证 | `uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"`; `uv run --extra dev pre-commit run --all-files` |

既有强制 `.github/workflows/harness-sidecar-release-gate.yaml` 已触发并执行完整 `tests/runtime/customer`；新回归自动进入门禁，无需重复工作流。包装器使用既有仓库环境、隔离 HOME、只允许本机回环网络，与仓库 pytest 入口等价并显式加载插件。

## 评审、授权与交付

直接评审（review-spec skill 不可用）：需求与双语合同一致；请求路径改动最小；安全与身份不变；整轮期限/取消/ACK/无重放约束保留；真实 socket 测试覆盖缺失机制。无设计阻塞。用户当前完整目标授权继续修复 SDK/Runtime 并在 Devbox 迭代；这是范围内的常规实现，不冒称另行获得设计审批或发布审批。

2026-10-21 验证：旧代码新增回归 4 failed / 3 passed（18.17 秒）；修复后首版 7 passed（11.32 秒）；完整 customer 与发布门禁合同 349 passed（28.10 秒），其中新真实 HTTP 文件 10 项。全仓使用 2 worker：7909 passed、50 skipped、4 xfailed、6 subtests passed（444.21 秒）；跳过项不作为已验证能力。pre-commit 五项 pass；双语标识、链接和 whitespace pass。执行基线 df31f1ce，加本设计对应 diff；实现摘要 fde11b8a480995aa6bae5b740d35b246d168320db21e6045684b4f946c2e9d99，回归摘要 4ddd1537bfd5ae8adc72b58bd9d9c45b52d1da49a6750e83ee411ff75e926645；全仓执行期间源码未变。T-1/T-2/T-3 与 AC-1/AC-2/AC-3 完成。T-4/AC-4 的安装制品与 Devbox 业务复测仍 not_run；整体交付未完成。制品/Devbox 验证单列；未完成前不得宣称业务失败已修复。风险：空闲正文连接可持有至既有整轮期限，仍有明确上限；Host 行为变更及完整业务质量不属于本 SDK 修复，继续保留在整体优化目标中。
