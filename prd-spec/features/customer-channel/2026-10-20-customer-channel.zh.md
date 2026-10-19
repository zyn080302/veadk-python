# Customer Shared HTTP 通道客户端

[English](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.md)

变更 ID：`customer-channel`；修订：2026-10-20；状态：implemented。
组件：[runtime-customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.zh.md)。

已批准的 Harness 集成蓝图要求公开 customer Runtime 适配。当前 SDK 分发支持 `adk`、`codex`、`piagent`、`dsh`，均未实现 managed customer Shared 通道。普通 Studio 工具清单的默认超时不同，也不保留 `source`；复用会改变目录摘要并违反 customer Host 策略。

本阶段先实现可独立使用的 HTTP 客户端。Runtime 分发、ADK 事件转换、持久化会话映射、业务集成和真实验收仍属于原目标，本阶段不代表这些工作完成。不复制服务端 core，不把远程 Agent 变为工具，不部署或切换现有入口。

## 要求与场景

| 要求 | 场景与预期结果 |
| --- | --- |
| FR-1 | 调用者提交完整配置和只读 Skill 快照：Shared 字段、默认值和摘要准确传到 HTTP，普通 Studio 行为不变。 |
| FR-2 | 能力查询、显式创建会话、运行、回传、取消使用一个已配置入口和会话专属客户端；响应的新亲和值替换旧值，不作为业务会话标识。 |
| FR-3 | HTTP 200、ready 或 EOF 没有成功的 `run.completed` 时，返回固定协议错误；跨轮、格式错误、超大事件拒绝处理。 |
| FR-4 | 工具调用校验 run/scope/catalog/name/executor 和参数 schema，只消费一次；重复、迟到、已取消调用不能再次回传，包括 HTTP 结果不确定的情况。 |
| FR-5 | 单次操作、整轮和清理都有期限；取消或提前退出关闭 HTTP，最多发送一次有期限的 `run.cancel`，之后可再次运行；不自动重放运行、回传或会话创建。 |
| FR-6 | 凭证仅保留在明确的本地配置和请求头/正文；异常、日志、repr 不包含响应正文、URL、配置或亲和值；禁止重定向和环境代理凭证；期限拒绝非有限值。 |

## 设计与任务

复用 `httpx`、Pydantic、AnyIO。`veadk/runtime/customer/` 负责协议值及每会话最多一轮的客户端。HTTP、有限 SSE 帧解析、工具关联分别承担独立职责。客户端提供已校验事件和显式回传，不执行工具代码；后续 runtime 层负责执行任务和可信业务授权。注入 transport 用于隔离测试，生产 transport 不重试。接口、状态和默认值以组件合同为正本。

- T-1 → FR-1/FR-6：协议模型与脱敏错误；运行入口深拷贝快照，防止外部修改。
- T-2 → FR-2/FR-3/FR-5：HTTP 客户端、有限 SSE 帧、成功/EOF/错误语义、上下文取消和资源清理。
- T-3 → FR-4：调用与回传关联、schema/期限/重复校验，不重放副作用。
- T-4 → FR-1–FR-6：先写失败合同测试，纳入已有 Harness 发布工作流及其回归；阶段提交前更新双语文档和源码绑定证据。

影响：`veadk/runtime/customer/`、`tests/runtime/customer/`、`.github/workflows/harness-sidecar-release-gate.yaml`、`tests/test_harness_sidecar_release_gate.py`。不修改 Agent、Studio UI、既有 runtime、依赖或默认配置。

## 验收与验证

AC-1/FR-1：精确 wire fixture、摘要、默认值、非法目录、完整只读 Skill。AC-2/FR-2：能力查询、显式 `sessionId`、亲和更新及会话隔离。AC-3/FR-3：UTF-8/SSE 分片、非法/超大/未知/跨轮事件、error/cancelled/EOF。AC-4/FR-4：调用和回传关联、重复迟到、结果不确定、在途调用有界。AC-5/FR-5/FR-6：单次/整轮超时、调用者取消、提前退出、再次运行、不重定向/重试、错误脱敏。

定向命令：`python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer tests/test_harness_sidecar_release_gate.py`。本地包装器隔离 HOME、dotenv、遥测和外网，CI 使用等价替身配置。最终检查包括相关 Harness App、双 worker 全仓 Python 回归、原 pre-commit、双语/链接/diff。真实 customer E2E 在分发和业务集成完成前仍为 `not_run`；工作流配置不等于远端 CI 已执行。

## 审查与交付记录

2026-10-20 直接设计审查（`review-spec` 不可用）：核对保留 managed Host 的类型和 transport，检查工具 source/只读策略、终态/取消、Python 3.10 兼容、错误、资源归属、双语一致和可测试性，无阻塞设计项。授权来自用户此前按蓝图实施、继续优化和阶段推送要求；本阶段在已批准范围内，不增加部署权限。

风险：模型出口重试/配额不由本客户端控制；断网可能导致取消未送达，因此同时关闭流，不伪造取消确认；本地关联不是分布式租约；会话持久化、跨进程恢复留在后续 runtime/业务阶段。入口、配置和请求头由服务端持有，不能由浏览器选择。实际 Host 版本兼容性仍未实测。

2026-10-20 验证完成（`f7cc528e` 加本变更）：旧 SDK 先出现入口缺失；审查新增两项失败回归后修正。定向 62 项通过（3.31 秒，customer 模块分支覆盖 87%），包含真实本机 HTTP 反向工具往返。保留 Host 的 SharedChannelRun 直接校验生成请求另 1 项通过（2.43 秒），仅为离线协议兼容。双 worker 全仓 **7594 passed / 50 skipped / 4 xfailed，另 6 subtests passed，430.70 秒**；原 pre-commit 五项通过。Python 3.10 语法、双语合同 ID、绝对路径链接和 diff 检查通过。

AC-1–AC-5、T-1–T-4 在本客户端阶段完成。真实 customer E2E、模型/MCP、客户原 20 题、Linux 新制品和远端 CI 为 `not_run`：Runtime/业务桥尚未接通，不能把本阶段结果用作其验收。前端与 Codex/Pi 烟测为 `not_applicable`：未改变这些实现；现有 Sidecar 覆盖率约束未修改。SDK 全仓检查不等于所有 50 个跳过场景得到验证。

审查补充：控制面请求互斥，错误事件之后或存在待回传工具时拒绝成功终态。这些落实 FR-2/FR-3，不扩大范围；补充失败测试后再调整实现。

源码绑定（本阶段被测文件）：

| Path | SHA-256 |
| --- | --- |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.github/workflows/harness-sidecar-release-gate.yaml | e68432b4c3f78d76e0bc6cea7b10bcb5d7c97dcc3638d12617122215ceaee645 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer/test_channel.py | ad1ef25893754688bf64dcb3953af112e6e3bb1880a9082474f4e355244e06d2 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/test_harness_sidecar_release_gate.py | f9847f48bf94895db551c76b4c3a4d7a89109434d201f7fbcf124b8c7c71d1d1 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/__init__.py | 589bd25a1a6cf94f7eb6dd4781946a1e2b6ff5a303f391a35473a2643813b299 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/client.py | 05aa0a4211b172b83f3c1cedfcc148e33f578bcc4f0cdaa8b7d69fa2dc219b63 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/protocol.py | c0ddee4e633234d0ae6708cc48378fde5ffc3a757f94f7f07090fe0ac192f1a0 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/sse.py | 8d85d7f44df50358afd663c62b9bbdaafacc229776bd68b83994eb8ce68f8bc4 |
