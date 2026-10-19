# 让委托 HTTP 执行遵守 Harness 模型调用次数上限

[English](2026-10-20-delegated-run-limit.md)

变更 ID：harness-http-call-limit。创建/修订：2026-10-20。状态：implemented。
组件：[harness-service CON-4](../../../specs/harness-service/README.zh.md)。
前序：[服务嵌入](../../features/harness-service-integration/2026-10-20-public-app-and-session.zh.md)。

## 背景、目标与范围

HarnessApp 保存 `max_llm_calls`，默认工厂读取 `MAX_LLM_CALLS`（默认 10）。委托的 ADK `/run_sse` 创建 RunConfig 时没有传入该值，`/run` 同样遗漏，因此多步骤查询可能超出配置的单轮次数上限。源码依据：`HarnessApp._mount_run_sse_override`、ADK `ApiServer.get_fast_api_app`、`InvocationContext.increment_llm_call_count`。实施前仍须通过 HTTP 复现。

在委托的 `/run`、`/run_sse` 恢复既有配置。这是单轮模型调用次数边界，不是 TPM/RPM 准入、传输重试计数、租户安全边界或性能收益测量。A2A、实时音频、真实模型接入和业务默认入口切换不在本次修复内；全链路防护仍需后续完成。既有显式 Harness 覆盖的优先级保持不变。

## 需求与场景

- FR-1：App 上限为 1，查询需要“模型/工具/模型”时，两条委托路由都只调用一次模型，保留已完成工具事件，在第二次模型调用前报告原执行错误。
- FR-2：上限为 2 时，同一流程完成。`None` 保留 ADK 默认；非正数保留 RunConfig 既有的无限制语义。每轮计数独立，包括并发会话与后续轮次。
- FR-3：会话不存在时仍在调用模型前返回 HTTP 404。metadata、state delta、invocation ID、附件事件拆分和断连取消继续由 ADK 负责。显式 `/run_sse` Harness 覆盖仍在原路由按原优先级生效。
- FR-4：客户端断连取消执行中的模型生成器并释放资源，随后请求仍能成功。修复不增加模型服务、凭证、文件系统或后台任务。

## 设计与合同影响

新增私有、无计数状态的 BasePlugin，在 `before_run_callback` 中复制本轮 RunConfig，仅修改 `max_llm_calls`，计数和执行限制仍由 ADK 负责。通过公开 `AdkWebServer.get_runner_async` 覆盖方法及 `PluginManager.get_plugin/register_plugin` API，为每个 ADK 管理的 Runner 注册一次。Server 持有所属 HarnessApp 的引用，插件读取同一配置的当前值；`None` 时不修改本轮。不得修改请求对象、共享 RunConfig、Runner.run_async 或全局 ADK 类。等待 Runner 获取结束后，检查与注册之间没有挂起点，并发获取不会在同一 Runner 重复注册。

保留捕获的 ADK handler 及其会话校验、事件序列化、取消责任。不把所有设置上限的请求改送 `_run_sse_events`，因为后者自动创建会话，会改变 404 合同。不复制上游路由实现，不全局 monkeypatch RunConfig。该插件独立于可选的 Harness 增强插件，不触发覆盖路由；不挂到单次覆盖 Runner 或 A2A Runner。

同步两种语言的 CON-4。无需新增公开参数、请求字段、存储格式或依赖。不增加 user ID 鉴权，不授权客户端修改上限。错误保持原路由行为：SSE 错误事件，`/run` 服务端错误。该配置是 App 默认值，不是新增的租户硬上限。

## 任务、验证与验收

| 需求 | 任务 | 验收 | 验证 | 结果 |
| --- | --- | --- | --- | --- |
| FR-1/2 | T-1：先写 HTTP 回归；T-2：在 `veadk/cloud/harness_app/app.py` 接入插件与 Server | AC-1：两条路由的实际模型替身/工具次数及终态符合上限 | `tests/cloud/test_harness_app_call_limit.py` | pass |
| FR-3 | T-3：兼容与并发轮次用例 | AC-2：404、metadata/state、显式覆盖及独立计数正确 | 新增及原 Harness HTTP/合同测试 | pass |
| FR-4 | T-4：真实 loopback HTTP 断连用例 | AC-3：模型清理且随后请求成功 | 新测试文件，有限时本地 uvicorn 服务 | pass |
| 全部 | T-5：回归加入强制 Harness 发布门禁；检查双语文档并推送已验证分支 | AC-4：定向及全仓回归、pre-commit、差异与密钥扫描通过 | 下列命令 | pass |

使用仓库 Python 环境、合成配置、临时 HOME，禁用 dotenv/遥测并禁止外网。定向：`python3 .codex/run_offline_tests.py tests/cloud/test_harness_app_call_limit.py tests/cloud/test_harness_app_http.py tests/cloud/test_harness_app_contract.py tests/cloud/test_harness_app_embedding.py tests/test_harness_sidecar_release_gate.py`。全仓：同一包装器加 `-p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`。包装器是本地隔离工具；CI 使用合成配置执行 `python -m pytest`。提交前同步目标基线，在隔离环境及既有本地缓存中执行 `pre-commit run --all-files`。这些测试不能证明远端 CI 或真实模型端到端通过。

## 风险、审查与交付

通过 HTTP 实际执行覆盖上游 Plugin/Runner 行为，不只断言 mock。保留原错误表达，不伪装为成功答案。达到上限可能留下已完成工具步骤、尚未生成模型总结；已完成事件仍可读取，新一轮获得独立预算。本次修复不限制总时长或跨副本配额。

2026-10-20 设计审查：已直接检查需求、公开扩展点、并发、取消、安全、路由兼容与双语一致性；`review-spec` 不可用。无未解决设计阻塞。授权来自用户已有的按蓝图完成适配/性能优化、将验证通过的阶段成果推送独立分支的要求；不推导新的合并/部署权限。在该设计检查点，实现和全部检查尚待执行。范围改变须先更新本双语设计再改代码。

验证检查点（2026-10-20）：修改生产代码前，新增 HTTP 文件在 `d20cc73d935ba93800c74734e9c7bffe8aeaf8b5` 上实际得到 **3 failed / 17 passed，38.04 秒**。两条委托路由在上限 1 时实际调用合成模型两次；显式覆盖后的默认轮同样超限。修复后，上述定向命令得到 **113 passed，32.83 秒**，含输出前/后真实 loopback HTTP 断连清理及随后成功发送。这是合成集成证据，不是模型服务或客户验收。已 fetch/rebase 的 `origin/main` 仍为 `402a3da9cc1a9b4201411d660b51dd6bf023f06a`；原 pre-commit 全部钩子通过。全仓双 worker 回归通过：**7533 passed / 50 skipped / 4 xfailed**，另有 6 个子用例通过，耗时 **413.47 秒**；跳过及预期失败不计为通过。此 SDK 修复的 AC-1 至 AC-4 已满足，客户集成整体计划仍未完成。生产源码 SHA-256：`veadk/cloud/harness_app/app.py` = `9bc5087225ebfc85b11f07c319d601d85b1bc947069f8b32a83d9c9fc26e6b65`；新增测试 SHA-256 = `f9ff9f4e0c7fae1dc49c26bb4ea67b39410fa53899c5b197c5da0504f770c209`。远端 CI、业务制品更新及发布尚未执行。
