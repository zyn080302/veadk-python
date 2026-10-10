# AI OPS 扩展合同

[English](README.md)

组件：aiops-extension | 修订：2026-10-10 | 状态：draft

公开模块：veadk/aiops。消费者：独立安装的私有 agentkit_aiops 内核。公开 SDK 负责配置、插件和清单类型、懒加载托管及服务转发，不包含调查内核或私有提示词。

- CON-1：AgentConfig 不可变，拒绝额外字段及核心提示词覆盖，取证后须预留报告时间。默认保持 exploration_seconds=900、invocation_seconds=2400、max_parallel_tools=4、sidecar_enabled=false、studio_enabled=false。
- CON-2：AgentPlugin 校验名称，通过工厂创建新工具。BuildContext 的 repr 不显示环境。插件可追加客户说明，不能替换私有核心提示词。
- CON-3：AgentManifest 读取可信本地 TOML 和显式 module:factory 引用；Skill 路径相对清单解析。不得接受模型生成的清单或导入配置。
- CON-4：hosting.create_agent/create_app/create_server 懒加载已安装的私有内核。内核未安装时给出可执行提示，其他依赖缺失保留错误。服务接口转发到同一内核，自身不实现预算或推理。
- CON-5：导入兼容不代表运行兼容。仍依赖已删除 Codex native 模块的 Core 版本，必须完成显式适配及内核、应用门禁后才能在上游主线执行；不得静默切换推理 runtime。

状态与并发仍由内核负责；转发层不增加任务、缓存、重试或持久化。本次从已发布 native7 SDK 恢复既有默认值和签名，不修改主线 Codex runtime。

验证：uv run --extra dev pytest tests/aiops/test_contracts.py。运行验收还须 Core tools/check.py、APP tests/run_regression.sh，以及授权真实更新与首次对话。缺失模块的 RED 记录为 .codex/aiops-contract-red.xml（6项失败）。不宣称线上兼容已通过。

关联变更：[主线整合](../../prd-spec/refactors/aiops-mainline-studio/2026-10-10-mainline-integration.zh.md)。

CON-6：Studio 来源保持 MCP 更新在存在 _veadk_studio_mcp_overlay_handler 时必须交给应用处理。保留领域工具包装层，处理器错误上报，非法处理器拒绝，并遍历子Agent；无处理器应用保持通用 MCP 替换，但通过 CON-11 旧启动合同校验的应用除外。由 tests/aiops/test_mcp_overlay.py 验证。

CON-7：来源保持部署通过 `VEADK_STUDIO_SKILL_OVERLAY`、`VEADK_STUDIO_OVERLAY_READY_FILE` 和 `PYTHONPATH` 中仅出现一次的启动路径前缀，启用镜像内的 overlay。原应用导入路径来自可信 Runtime 配置，继续禁止浏览器覆盖保留环境变量。SDK launch 载荷测试覆盖实际生效值。

CON-8：`sourceOverlay` 是公共元数据，包含 `schemaVersion=1` 及完整的 Agent 名称到 MCP 配置映射。只包含 MCP 名称、HTTP URL、传输类型和凭证环境变量引用，清单与响应都不得包含凭证。非法、缺失、重复键或软链接清单返回 `status=unavailable`，阻止编辑但不停止 Agent 运行。即使存在旧的普通 draft，再次打开仍优先保留源码；映射必须匹配完整 Agent 图，所有凭证引用必须在服务端可解析。由 `tests/integrations/agentkit/test_app.py` 和 `tests/cli/test_studio_rbac.py` 覆盖。

CON-9：`final.json` 定义精确的最终 Skill 选择。连续更新不能重新启用已取消选择的基础镜像 Skill，也不能静默丢弃应保留的 Skill。缺少该清单的旧 overlay 保持原合并语义。替换构建拒绝不可读取却要求保留的旧 overlay Skill，并清理旧 overlay 目录。OCI 恢复依据权威选择，目录 whiteout 和 opaque whiteout 只影响下层镜像。由 `tests/aiops/test_skill_overlay.py` 和 `tests/cli/test_legacy_runtime_recovery.py` 覆盖。

强制 `harness-sidecar-release-gate.yaml` 已纳入上述回归。当前整合已在本地实现，但真实 Studio 更新和首次对话验收完成前保持 draft；导入测试或平台跳过用例不足以证明验收通过。

CON-10：Overlay bootstrap 观察正常 App 导入，不提前导入应用包。保留应用依赖选择，在模块执行完成后只包装一次 App，移除观察器，并传播应用导入错误。由 `tests/aiops/test_overlay_startup.py` 的独立进程启动回归覆盖。

CON-11：仅在可信原配置显式启用 Studio 且含有 `MCP_SERVERS_JSON` 时，应用自管 MCP 才采用旧启动环境合同。Studio 根据最终验证的单根 Agent 草稿重建私有环境清单，全部移除时显式写空列表；镜像中仅保存无凭证的启动模式和 MCP 引用。生成的钩子校验实际环境与这些引用一致并保留应用工具包装，显式应用 handler 仍优先。无效配置或有歧义拓扑用固定错误拒绝，其他 MCP 归属路径不变。强制 credentials 门禁中的部署 payload 和生成启动器回归覆盖本合同。
CON-12：保留源码更新保留可信的 `HARNESS_NAME` 应用身份，不受 Sidecar 是否开启影响。该字段不属于 Sidecar 计划或凭证。既有 Sidecar 清理和浏览器环境覆盖限制保持；普通代码生成部署沿用原过滤行为。部署参数与生成 App 启动回归必须同时验证应用身份和 MCP 清单。

## Harness App 提案（2026-10-10）

CON-14：空的通用 Harness 配置不暴露 Skill 或工具。具体 Agent 插件拥有本地工具和领域资产；Studio 显式选择的 Skill、MCP 为最终配置，不回退到镜像中的旧选择。非 Harness 的历史 Agent 默认行为保持。Skill 下载隔离执行、受时间和资源限制，并在异常、取消时清理。不支持的内置能力和知识库绑定明确报错。

CON-15：`AgentConfig.instruction_source=harness_config` 使不可变 YAML 中的客户附加指令生效；宿主不挂载另一套 SQLite 编辑器，也不应用旧 source overlay。普通宿主仅在可信代码挂载了附加指令编辑器时返回 `instructionExtension=true`。Studio 单次运行快照可携带文本 Skill 和 `long_running` 工具声明；没有运行快照时不暴露 Studio 工具。能力标志仅声明已实现的协议功能。

CON-13：显式启用的 AI OPS 固定配置宿主消费 `agentkit-studio/servers/harness_app_server` 已准备的 `agentkit/v1` `AGENT_CONFIG` 合同。`GET /agent_config` 仅返回已校验的原始配置（环境引用，不含解析后的值），使用 `Cache-Control: no-store`；装配完成后才通过 `/healthz`。凭证只在进程内解析；非法、重复键、不安全、超限或未解析配置在 Ready 前失败。客户 `agent.instruction` 仅作为附加指令，不能替换私有系统规则。普通调用与 Studio 通道使用相同内核和会话存储。不改变 SDK 默认行为。实现及真实云验收待完成，见[功能设计](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.zh.md)。

### 保留源码覆盖文件系统
Studio 更新继承原镜像的运行用户。构建资产显式设置可读及可遍历权限，使用内容摘要目录，更新不依赖删除父镜像所有的文件。生成的布局标记、镜像环境与控制面 Runtime 环境必须选择同一版本。OCI Skill 恢复校验标记及当前版本清单，排除未启用的历史覆盖目录，并兼容旧固定路径。清单不保存凭证。

CON-16：明确的 source-preserving 更新沿用原应用发布流程。CustomCreate 向 ProjectPreview 传递 editMode；恢复得到结构化草稿不代表支持 MPA Profile。该方式不进入 MPA Profile/smoke 阶段或调用，regenerate/新建 MPA 及其错误处理保持。Runtime 发布失败仍为失败。真实 ProjectPreview 流程回归加入强制 npm test，仍须完成真实 GUI 验收。

CON-17：保留源码编辑允许缺少静态提示词，因为运行时提示词保持不可修改。其他校验以及普通新建/重新生成的提示词必填要求仍执行。
