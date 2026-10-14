# 可选的 AI OPS 扩展

[English](2026-10-15-optional-plugin.md)

变更 ID：aiops-extension。日期：2026-10-15。状态：implemented（已实现）。组件合同：[aiops-extension](../../../specs/aiops-extension/README.zh.md)。

## 证据与范围

主线 d55fe8fa 已有 HarnessExtension，尚无 veadk.aiops 命名空间及单次调用 provider factory。现有 AI OPS SDK 分支提供配置、插件、manifest 和 hosting 接口；已安装的 Core 0.1.46 导入这些合同。Core 在公共 provider 可用时使用它，否则修改旧 SDK 内部实现。用户明确要求先更新客户测试 Studio，再按 HarnessExtension 方式插件化。该独立任务已完成：Studio Revision 53 经正式发布 API 更新旧数据库，三轮真实问答通过；不声称使用页面发布按钮验收。

## 目标与需求

- FR-1：通过 veadk.extensions.aiops 提供 AIOpsExtension。只导入 veadk 或扩展时，不加载、安装、启动 Core，不发现第三方插件；显式 apply/create 才启用执行。
- FR-2：通过 veadk.aiops.backends entry point 组选择已安装后端，API 版本为 1。选择属于可信 Python 配置。拒绝重名、不兼容 API 和后端错误。兼容现有镜像时，仅默认 agentkit 名称可在无注册项时解析固定的 agentkit_aiops 模块；注册后端加载失败不能回退。
- FR-3：旧 veadk.aiops 与新的扩展路径保持 AgentConfig、AgentPlugin、BuildContext、AgentManifest 类型身份一致。原 hosting 签名继续可用，默认依赖不引入私有 Core。
- FR-4：关闭扩展时，apply 原样返回传入 Agent，不加载后端、不调用领域工厂。启用时只装配一次新 Agent，保留 Core 领域插件语义。扩展不拥有进程或调用资源。
- FR-5：只在原 Codex runtime 增加通用可选 provider 接口。默认 direct/shim 行为、原生工具循环与历史归属保持；完成、异常、取消、提前关闭流均释放 provider。工具准入名称/schema 仍由 SDK 决定。Shell、压缩提示词、工具结果预算仅显式配置才改变默认值。
- FR-6：新扩展在加载 Core 前要求公共 provider 接口，拒绝当前仍修改 SDK 全局实现的 report_only。现有 hosting.create_server 仍是旧兼容入口，不将其描述为无全局补丁的扩展生命周期。

不包含：修改 Studio UI、更新客户 Agent/镜像、替代 Codex 循环、重写 Core 运维逻辑、迁移全部旧服务器补丁。SDK 改造不需要新的云端写入。

## 设计与场景

AIOpsExtension(config=AgentConfig(...), plugins=(...), enabled=True, backend="agentkit") 提供 apply(agent)、create_agent()、create_app()。显式对象保存配置与懒加载后端；不在导入时扫描插件，不写环境变量。后端 API 1 提供兼容 config/plugins/agent 参数的 create_agent、create_app 工厂。领域插件仍使用普通函数、工具及 ADK 回调。精确选择的注册后端只加载一次；包括传递依赖缺失在内的错误均传播。

未安装 Core 时，普通 Agent 与关闭状态的 apply 仍可用；显式创建 AI OPS 时报告明确依赖错误。指定名称出现两个注册项时，加载前拒绝。provider 流被取消或提前关闭时，异步上下文只关闭一次。并发调用分别使用独立 endpoint 和已准入工具执行器。

合同的实际定义移入 extensions/aiops，旧模块重新导出相同类型。通用 provider_factory 只接受 callable，从序列化/schema 排除，配置复制时保留，不接受 Studio 字符串。provider 拥有认证与传输，不接收无关模型 headers。Core 继续独立发布。

## 任务与文件

- T-1 / FR-1–4,6：扩展模块、旧兼容导出、后端注册合同、双语 README 与例子。
- T-2 / FR-5：runtime/codex/config.py、provider_extension.py、runtime.py；复用已审查 provider 行为，不带入其他分支变动。
- T-3：合同、负例、导入测试，provider 生命周期和原生运行测试，打包 entry point 集成及 CI 门禁。
- T-4：候选 SDK 与实际已安装 Core 装配验证；基线回归、pre-commit、审查；仅把此 SDK 的公开代码提交推送到用户 fork。

## 验收与命令

| 需求 | 任务 | 验收 | 证据 |
|---|---|---|---|
| FR-1–4,6 | T-1,3 | AC-1：无隐式依赖/发现、类型身份兼容、关闭状态准确、后端选择校验 | tests/extensions/aiops；pass |
| FR-5 | T-2,3 | AC-2：默认传输等价、provider 生命周期隔离、工具准入 | tests/runtime/codex；pass |
| FR-1–6 | T-4 | AC-3：实际 Core 经扩展创建可用 Agent/App，未修改 SDK 全局实现 | 本地隔离集成；pass，源码 2 项、已安装 SDK 2 项 |
| FR-1–6 | T-3,4 | AC-4：必需门禁与公开 diff 合格 | pytest -n 2 -m "not codex_smoke and not piagent_smoke"；pre-commit run --all-files；pass（固定扫描器等价执行见下） |

使用仓库环境的 uv run --extra dev。原生 smoke 通过 CODEX_RUN_SMOKE=1 串行运行，必须实际执行。无凭证的本地协议夹具验证接线，不把客户数据发给模型。此 SDK 变动无需线上云/浏览器测试；独立的 Studio API 验收已经完成。

## 审查、授权与风险

用户在本次请求中明确批准按插件方式实施并减少存量影响；本设计落实该方向，不引入破坏性变化或生产发布。review-spec 技能不可用，直接审查 API 归属、可选依赖、重复注册、错误传播、取消、普通 Agent 隔离、兼容性及双语一致性，未发现设计阻断项。

风险：旧 Core 在显式调用 create_server 时仍应用旧服务器补丁，文档会说明，不声称已经移除。新 SDK 不会自动改变现有镜像。后端缺失只在启用时出错。现有 Core 0.1.46 发行包仍锁定旧 SDK。源码 API 兼容及候选 wheel 运行不等于普通依赖解析安装通过；客户升级前需要匹配的 Core/SDK 发行版本。

## 已执行验证（2026-10-15）

范围：本分支基于 origin/main d55fe8fa，最终检查前已 fetch/rebase。使用现成仓库环境：`UV_PROJECT_ENVIRONMENT=../database-v4-skill-mcp-20261013/.venv PYTHON_DOTENV_DISABLED=1 uv run --no-sync --extra dev`。

- `pytest -n 2 -m "not codex_smoke and not piagent_smoke"`：pass，7089 passed、53 skipped、4 xfailed、6 subtests passed。使用两个 worker 控制本机资源。
- 扩大 runtime/Harness 回归：pass，555 passed、25 skipped、13 deselected。首次因 `OTEL_SDK_DISABLED=true` 禁用了待测行为，出现 29 项 tracing 失败；移除该测试环境设置后全部恢复，原失败证据本地保留。
- `CODEX_RUN_SMOKE=1 ... pytest -m codex_smoke -p no:xdist -rs`：pass，12 项实际执行，2 项缺数据库测试配置跳过。包含真实本地 CLI/provider/MCP 循环与最终答复；没有调用云模型或使用客户数据。
- 候选 SDK 加 Core 0.1.46 源码：pass，2 项；已安装候选 SDK wheel 加 Core 源码：pass，2 项。均验证连续问答及 SDK 函数身份不变。私有 Core 夹具保留在公开 SDK 仓库之外。
- Wheel：pass，14 个源码文件一致，默认依赖不含 Core；验证版本 `0.0.0` 不是发行版本。
- Pre-commit：pass，Ruff 检查/格式化、Gitleaks 8.24.2、依赖策略、YAML 密钥检查。首次在 Go 安装阶段退出 143；重跑使用已核对同版本本地 Gitleaks，仅在临时配置调整该 hook 执行语言/路径，原 `git --pre-commit --redact --staged --verbose` 扫描范围及其他检查保持一致。仓库 hooks 未改，没有跳过扫描器。
- 实现审查：pass，检查可选启用、旧类型身份、callable 不序列化、provider 生命周期、并发调用隔离、工具准入。旧服务器补丁与发行包依赖锁定仍是已说明的边界。
- 云发布及模板升级：not_applicable，此项仅修改 SDK，没有写客户 Runtime。
- 主线同步后：`pytest tests/extensions/aiops tests/runtime/codex tests/test_harness_sidecar_release_gate.py -m "not codex_smoke" -q`：pass，393 passed、25 skipped、14 deselected，退出 0。
