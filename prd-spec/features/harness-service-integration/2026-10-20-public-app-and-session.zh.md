# 标准 Harness App 与公开会话注入

[English](2026-10-20-public-app-and-session.md)

变更 ID：harness-service-integration。创建/修订：2026-10-20。状态：阶段实现；定向验证与 pre-commit 通过，全仓回归尚未全绿。
组件：[harness-service](../../../specs/harness-service/README.zh.md)。

## 背景与目标

用户已批准的 SkyEyes 蓝图要求标准 HarnessApp 承载现有 Agent 和带计时的 DatabaseSessionService。官方基线 402a3da 中导入该类就创建环境 Agent/App，ShortTermMemory 也不能接收已有服务；create_session 在定点读取前列出用户全部会话，并记录连接 URL。这些行为增加启动/请求成本并可能暴露凭证。

本次先实现 P0 前置能力。完整用户目标仍包含业务接入、过载防护与 customer 运行时支持，这些是后续变更而非删除范围。本次不改变前端行为、模型选择、数据库 schema、云资源或部署。

## 要求与场景

- FR-1：导入 HarnessApp 不创建环境 Agent、默认 App 或数据库服务；显式访问默认 ASGI App 与模块 CLI 保持兼容。
- FR-2：ShortTermMemory(session_service=service) 复用同一个 BaseSessionService，序列化和 repr 排除该对象；冲突的存储配置明确失败；原后端构造和回调仍支持。
- FR-3：create_session 定点 get，不存在才 create，不列历史、不记录数据库 URL；存储和取消错误传播，新建回调只在实际创建时执行。
- FR-4：既有默认 HTTP 合同、SDK 调用方与业务测试保持通过；回归只使用合成身份/配置和本地存储。

两个调用方导入类时都不启动默认运行时；ASGI 工具读取 app 时缓存一个默认 App。注入已有服务时，Runner 和 App 都复用它。用户历史多且目标存在时只需一次定点读取。存储失败或取消时不创建替代状态、不返回空成功。

## 设计与合同影响

移除默认 Agent 的提前导入和默认 App 的提前构建；提供 create_default_harness_app 与缓存的 get_default_harness_app。模块 __getattr__ 保留旧 app/harness_app 导入及 Uvicorn module:app；模块执行调用 getter。公开类路径不变。默认工厂缓存由进程内锁保护，并发首次访问只构造一个 App；清空缓存是私有测试辅助接口，不是用户请求 API。

新增 Pydantic 输入，别名为 session_service，排除 repr/dump；保留现有只读 session_service 属性。只有没有 db_url/backend/db_kwargs/backend_configs 冲突时才采用注入存储，歧义配置拒绝。调用方负责服务释放，本变更不关闭外部注入服务。保留并说明已有 after-load 回调包装行为；不同回调包装不能共享同一个服务。

删除 DatabaseSessionService 的无条件 list_sessions 分支，保留 get/create 与 after-create 回调语义。同一缺失 ID 并发创建仍遵循存储后端冲突规则，本变更不宣称提供分布式会话租约。

## 任务与修改位置

- T-1（FR-1）：先在 tests/cloud/test_harness_app_embedding.py 写回归，再改 veadk/cloud/harness_app/app.py。
- T-2（FR-2/FR-3）：先在 tests/test_short_term_memory.py 写回归，再改 veadk/memory/short_term_memory.py。
- T-3（FR-4）：定向 HTTP/会话测试、相关 Harness 发布门禁与更广 Python 回归；同步双语合同及验证记录。

## 验证与验收

AC-1：通过环境 Agent 模块哨兵证明导入不会访问该模块；显式默认工厂及原 HTTP 测试通过。
AC-2：注入本地服务保留对象身份/状态，并拒绝冲突配置；原本地/SQLite 构造仍通过。
AC-3：本地 SQLite 的 list_sessions 换为失败哨兵后仍可创建/续接；取消/错误及回调回归通过；日志不包含合成 URL 哨兵。
AC-4：执行 `uv run --extra dev pytest tests/test_short_term_memory.py tests/cloud/test_harness_app_embedding.py tests/cloud/test_harness_app_http.py tests/cloud/test_harness_app_contract.py`；交付前执行 AGENTS.md 的 pre-commit 与更广门禁。不据此宣称真实模型/MCP 通过。

## 风险与评审记录

惰性模块属性可能影响反射，需验证显式导入与 module:app 加载。输入别名不能通过 Pydantic 序列化泄漏服务。存储回调包装为原有可变行为，需保持明确。不新增网络或存储权限。

用户范围批准：2026-10-20 明确要求按已交付 SkyEyes 蓝图实施。因没有 review-spec 技能，修改代码/测试前已直接评审要求/合同、导入兼容、状态归属、取消、凭证保护及双语一致性，无未解决设计阻塞。运行验证见下方记录，尚未执行真实服务验收。


## 实现与验证记录（2026-10-20）

基线：`402a3da9cc1a9b4201411d660b51dd6bf023f06a` 加包含本设计的阶段改动。Python 3.12.13、google-adk 2.7.1、LiteLLM 1.83.14、agentkit-sdk-python 0.8.9、Pydantic 2.12.5。隔离 editable SDK 是开发环境，不是最终业务依赖锁或发布制品。

- pass：已建立失败基线（11 failed / 5 passed）；默认缓存并发回归在加锁前失败，共构造四个 App。
- pass：实现后 App/HTTP/schema/会话/Runner/发布门禁共 114 项定向检查通过；修改 Python 文件的 Ruff 0.11.12 检查通过。
- pass：相关扩展回归共 193 项通过，覆盖 `tests/cloud`、`tests/runner`、`tests/integrations/agentkit/test_app.py`、`tests/test_runner.py`、`tests/test_short_term_memory.py`、`tests/extensions/harness/test_runner_plugins.py` 和 `tests/test_harness_sidecar_release_gate.py`。
- 首次扩展运行有六项缺少可选知识库/记忆测试依赖，已在本地与发布门禁补充必需的 llama-index core、OpenAI-like embedding 包。另一次扩展运行因本地包装器禁止所有 socket，阻止了十项回环代理替身测试；调整包装器为允许回环、禁止外部连接/DNS 后，193 项全部通过。未修改生产网络行为。
- 发布约束：App 与会话回归和对应源码触发路径已加入 `.github/workflows/harness-sidecar-release-gate.yaml`；CI 实际执行为 not_run。
- fail：首次全仓双 worker 回归为 7357 passed、85 failed、2 项收集错误、55 skipped、4 xfailed。定向检查证实本地包装器关闭 OpenTelemetry、未加载 AnyIO 插件，以及缺少可选 anthropic 依赖。环境修正及基线 sidecar 断言修正见下文；保留此首次失败记录。
- pass：最终回归前已与官方 origin/main 的 402a3da 同步；pre-commit run --all-files 的 Ruff 检查/格式、Gitleaks、依赖策略和 YAML 密钥扫描均通过。测试工作流采用既有允许的 example 占位值，没有绕过扫描规则。Go 仅安装于任务本地目录，归档已按官方 SHA-256 校验。
- not_run：业务制品安装、真实模型/MCP/customer 验收和部署。对应交付结论仍以完成这些检查为前提。

本地使用 `.codex/run_offline_tests.py` 包装器调用仓库 `.venv`，采用临时 HOME、合成配置并禁止外部 socket。首次并行运行的 socket 保护只作用于主进程；现已通过临时 sitecustomize 为继承环境的 Python 子进程启用保护，并保留内存 tracing、加载 AnyIO 插件。包装器运行 `python -m pytest`，显式加载 asyncio/coverage/AnyIO 插件；它仅是本地执行辅助，提交的 CI 直接运行已列出的 pytest 路径。知识库/记忆测试必需包为 `llama-index-core>=0.14.0,<0.15` 与 `llama-index-embeddings-openai-like>=0.2.2,<0.3`。


### 发布回归核对（2026-10-20）

修正隔离测试环境（内存 OpenTelemetry、AnyIO 插件、Node PATH、anthropic 1.3.0 和 openai-codex 0.159.2）后，原失败只剩一条已有 sidecar 测试。用 402a3da 的纯源码归档也能复现：test_run_wraps_child_with_sidecar_environment 断言端口为 18787，但实际 binding 提供动态分配的回环代理。测试和 sidecar 实现均与基线逐字节一致。

T-4 / AC-5：捕获真实 start_harness_sidecar 返回的公开 SidecarBindingSpec，断言子进程收到的模型 URL、MCP URLs 与其完全一致，同时验证回环主机、/api/v3 路径和非零端口。保留真实子进程与 sidecar 生命周期。这是完成嵌入交付门禁所需的验证修正，不改变 sidecar 生产行为及组件合同。已直接审查：原失败有复现，新断言验证实际配置导出，不通过固定端口或绕过 Runtime 消除失败；范围仍属于用户批准的集成及交付验证。

- pass：修正后的 sidecar runtime 测试文件共 15 项通过；工作流的覆盖率测试集合共 144 项通过，sidecar.py 分支覆盖率为 96%，超过要求的 91%。未改变 sidecar 生产代码。

### 阶段检查点（2026-10-20）

- fail：最终隔离双 worker 全仓运行（通过上述包装器执行 `pytest -n 2 -m "not codex_smoke and not piagent_smoke"`）为 7507 passed、6 failed、50 skipped、4 xfailed、6 subtests passed，耗时 423.98 秒。没有额外排除测试，仅使用仓库默认的 smoke 排除条件。
- 五项失败依赖外部 DNS：`tests/cli/test_github_cicd.py::test_list_github_delivery_versions_returns_recorded_versions` 和 `tests/frontend/server/artifacts/test_artifact_library.py` 中全部四项测试。GitHub 测试列提交时未传入客户端替身；artifact URL 校验在替代下载之前解析合成域名，两者均被离线保护拒绝。使用官方 402a3da 的纯源码归档及同一隔离环境，复现完全相同的五项失败。
- `tests/plugins/test_codex_sandbox_upload.py::test_upload_retries_while_new_session_data_plane_starts` 仅在全仓运行失败，被替换的 sleep 记录到额外调用；当前源码和纯基线的隔离复跑均通过。顺序/后台工作影响的根因仍需调查，不能因此将全仓门禁改写为通过。
- pass：调整工作流合成 Key 占位值后，重新运行工作流合同测试通过；双语链接/合同 ID 与 diff 空白检查通过。
- 用户要求有阶段进展就提交到独立分支。本次是供审阅的开发检查点，保留剩余回归调查，不是发布、固定制品验收或完整集成蓝图完成。远端 CI 和真实业务验收仍为 not_run。
