# AI OPS 主线与 Studio 更新整合

[English](2026-10-10-mainline-integration.md)

- 变更 ID：aiops-mainline-studio
- 日期：2026-10-10
- 状态：implemented


## 最终验收（2026-10-10）

状态：implemented。上游已同步至 `812faadfe9952d47d1efc7b0a32595beafa58b91`，私有 Core 和插件基线仍为 c51d2640、440ddeea。保留继承的 Studio 指导升级修复，不改变正常升级默认行为。下方历史检查点保留原失败和待验收证据。

AC-1 至 AC-9 在授权范围内均 pass。主线兼容已通过 [Harness 模板设计](../../features/aiops-harness-template/2026-10-10-harness-template.zh.md) 完成，覆盖当前/历史 SDK 门禁及真实原生 CLI。SDK 回归：7159 passed、70 skipped、4 xfailed。前端：Node 1386 项、React 72 项；build/assets、pre-commit 通过，Pyright 无新增诊断。

第二次 Studio 更新由 V55 经正常确认页面发布至 V56。再次打开后保留两项 Skill 和五个带认证的 MCP；Skill 激活回执和终稿包含 h2，MCP 手册调用在模型纠正首次参数错误后成功。V60 保留新主线镜像并恢复旧入口环境，新会话重复 Skill/MCP 验收通过。九个保护 Runtime 的版本/配置摘要不变。中文教程含已检查的真实脱敏截图。云端 Studio Function 和更新通道未升级；客户需要使用包含这些修复的 Studio 版本。

## 证据与范围
VeADK 上游主线为 171d8d86。较新的线上 SDK 使用 native7 并提供 veadk.aiops；主线缺少该包，且移除了 native_bridge/native_responses。本次验证的旧应用实际使用 SDK 1.1.7.dev33+g788459adf.baisheng.20260919.4。Core 主线 c51d264 仍导入已移除模块。APP 主线为 440ddeea。Studio 升级修复 f94b5960、5ca502ad、814da374 尚未进入上游主线。

用户授权主线拉齐和旧应用 Agent 的真实 Studio Skill/MCP 更新。客户 v4-2 及其余旧 v4 Agent 受保护。禁止云资源枚举和实例远程 shell。

## 要求与设计
- FR-1：从已核验主线建立隔离分支，保留其他工作树。整合三个已有 Studio 升级修复，不改变正常升级默认行为。
- FR-2：恢复公开 AI OPS 配置、插件、托管入口，保持与私有内核分离。保留当前上游 Codex 实现。实际 Core 兼容及强制门禁通过前，不部署主线 wheel。
- FR-3：Studio 更新保留应用源码、现有环境与凭证，以及 Skill/MCP 语义。凭证只保留在进程或授权密钥存储中，不进入源码或报告。
- FR-4：只对授权应用 Runtime 从真实 Studio 提交一次更新，跟踪同一任务与候选到完成，验证首次对话及修改后的 Skill/MCP，再比对受保护资源摘要。
- FR-5：交付中文客户教程，包含实际脱敏截图和验证结果，明确区分待完成步骤。

## 任务与验收
| 任务 | 要求 | 验收 | 检查 |
|---|---|---|---|
| T-1 | FR-1 | AC-1：隔离树包含已获取主线 | Git 祖先及基线检查 |
| T-2 | FR-1 | AC-2：保持升级兼容 | 历史消费者、指导升级、CLI 合同测试；发布门禁 |
| T-3 | FR-2 | AC-3：公开合同与实际 Core 装配可用 | 公开合同测试、Core tools/check.py、APP tests/run_regression.sh |
| T-4 | FR-3 | AC-4：保持源码与凭证边界 | 来源保持更新前后端回归及必需构建、类型门禁 |
| T-5 | FR-4 | AC-5：真实页面更新、首次对话通过；其他 Runtime 版本与配置不变 | 候选、任务、发布证据与定点前后比对 |
| T-6 | FR-5 | AC-6：客户可按图操作 | 教程、图片和链接审查 |

## 合同影响与风险
三个既有修复的移植保持 Studio 升级合同不变。恢复 veadk.aiops 及适配变化后的 Codex runtime，须在实施前另行评估组件合同。不能用旧 native runtime 覆盖上游模块。当前导入不兼容阻止在生产使用主线 SDK。浏览器登录及精确 Runtime 连接尚未完成。

## 评审与验证记录
用户授权来自本轮主线拉齐及仅验证旧 v4 应用的请求，三个已实现升级修复的本地整合属于该范围。新增 runtime 行为调整仍在评审中。review-spec 不可用，直接按同等要求审查：明确源码保护、凭证边界、禁止枚举、首次对话验收和发布证据来源。主线工作树 AC-1 已通过，其余验收 not_run。设计创建时产品代码未改，云写入为0。

## 来源保持更新的 MCP 回归
2026-10-10：已发布 native7 的 tests/aiops/test_mcp_overlay.py 在主线3项全失败。生成的 sitecustomize 替换应用自有 MCP 工具，没有调用 _veadk_studio_mcp_overlay_handler，绕过应用策略所有权、隐藏处理器错误、丢失应用包装层。恢复既有处理器分支：可调用处理器负责更新；非法处理器拒绝；异常继续上报；保持对子Agent递归。这是恢复已部署扩展合同，不增加 MCP 执行机制。回归须纳入强制门禁。主线 Studio 升级检查：macOS 293通过、8跳过；跳过的Linux执行场景仍未验证。

## 配置加载回归
主线 RED：5 项失败（3 项缺失 helper 导入、2 项真实部署载荷缺少 overlay 环境）。恢复既有 native 部署合同：继承可信 Runtime 的 PYTHONPATH，且启动路径只前置一次；通过 SDK launch 配置显式传递 overlay 路径。继续拒绝浏览器环境覆盖。实际部署回归与 helper 用例进入 credentials 强制门禁。这次有界拉齐不迁移 Codex 引擎。

## 再次打开来源保持更新
FR-3 还要求第二次更新使用最新镜像配置，保留应用代码与 MCP 归属。恢复 native7 已有 sourceOverlay 公共元数据校验、恢复优先级和 MCP 图节点身份恢复。清单无效或缺失时阻止编辑，但不影响 Agent 运行。实现前恢复原有六种清单回归；测试只含合成凭证，纳入强制门禁。

## 多次更新 Skill 选择
三项离线 RED 复现：第二次更新后，被删除的基础镜像 Skill 重新出现；应保留的 Skill 丢失时却不报错。恢复既有 final.json 合同：最终选择精确一致、构建时验证不可读的旧 overlay Skill、清除被替换的配置目录、依据 OCI 清单和白化层恢复当前有效目录。保留主线对 MCP 凭证处理的改进。使用实际 Google ADK SkillToolset 验证生成的启动脚本，并覆盖离线 OCI 镜像层及既有恢复回归。

## 离线验证检查点（2026-10-10）
- 完整 Python 回归：6767 通过、74 跳过、无失败/错误；两个 worker，冻结的 dev/codex/extensions/sandbox 依赖。
- 强制后端门禁：coverage 149通过/1跳过，lifecycle 9通过，credentials 121通过，release 81通过；sidecar覆盖率96%（阈值91%）。
- 前端测试和构建通过；sidecar 22项通过，行覆盖100%、分支94.44%。pre-commit含密钥扫描通过。
- 授权 Devbox 隔离目录的 Linux 历史消费者检查：4通过，无跳过。
- Pyright 定点复验已消除新增的 OCI 测试诊断。上游诊断仍存在，不能称全量类型检查通过。
- 真实本机 Studio 已恢复唯一旧应用 V46 及其1个 Skill/5个 MCP，ZIP 导入已选中验收 Skill。Runtime 尚无写入。FR-4 通过两次独立更新测试 MCP 移除后恢复原有5个服务，每次只提交一次。
- AC-3 在主线 SDK 上的真实 Core 装配仍被已删除的 native 引擎导入阻塞。这些检查不支持直接替换已部署的 SDK wheel。AC-5/6 待完成。

## 启动导入顺序 badcase
首次真实 GUI 更新构建成功，但候选在开始提供服务前导入 `google.adk.tools.skill_toolset` 失败。镜像存在独立的系统和应用 Python 环境。生成的 `sitecustomize` 会在应用选择依赖路径前主动导入 `google.adk.apps.app`，可能缓存错误的 ADK 包。镜像配置读取被拒，因此镜像级 PYTHONPATH 丢失仍未确认。

FR-6 / T-7 / AC-7：注册 overlay 不得在解释器初始化时导入应用包。为 `google.adk.apps.app` 注册一次性导入观察器，在其正常 loader 执行完成后才修改 App；保留 loader 行为、移除观察器，并幂等处理已加载的 App。应用加载错误必须传播。本次保留现有 Runtime 环境处理。增加独立进程回归，以旧系统 ADK 和实际安装的应用 ADK 复现，并覆盖已加载模块和 loader 失败，纳入既有强制 `tests/aiops` 门禁。不升级依赖、不执行远程 shell。直接审查：属于用户授权 Studio 验证中 FR-3 的修复，无公共 API 变更。真实验收仍待完成。


## 旧应用 MCP 启动兼容
第二次 GUI 候选已越过导入顺序错误，但在 App 构建前报错：`Studio MCP source manifest is required`。精确发布源码在启动时读取 `MCP_SERVERS_JSON`，自行持有工具策略包装，没有 overlay handler。部署路径错误删除了应用自管 MCP 所需的环境字段。同一旧应用仅允许一个报告 Skill，因此真实验证采用完整同名替换原报告 Skill，不再新增第二个 Skill。

FR-7 / T-8 / AC-8：仅应用自管 MCP，且可信原配置包含 `VEADK_STUDIO_ENABLED=true|1` 和 `MCP_SERVERS_JSON` 时采用旧环境清单启动合同。根据服务端验证的最终草稿及凭证引用重建清单；全部移除 MCP 时显式写入空列表。凭证只进入 Runtime 环境。在 `mcp.json` 旁生成公开的 `mcp-bootstrap.json` 模式描述。扁平启动合同限定单个根 Agent，拒绝有歧义的图。在 App 构建时验证实际环境与公开映射及引用凭证完全一致，然后保留应用工具；显式应用 overlay handler 仍持有更新责任。缺失、格式错误或不一致时用固定错误拒绝，不回显任何值。其他应用、Sidecar、平台路径保持既有行为。

验证：补充真实部署 payload RED 回归、生成启动器的包装保持/空清单/拓扑/不一致/凭证边界测试，并在公共仓库之外运行准确历史消费者的离线检查。现有强制 credentials 门禁已经覆盖这些测试路径。评审：用户限定的 Studio 验证授权覆盖此兼容修复，没有扩大资源或产品范围；直接设计评审无剩余阻塞，真实验收仍待完成。保留失败候选证据，不宣称旧 Agent 已运行主线 SDK。
## 应用身份保留
第三次候选构建成功，但 MCP 身份校验失败。定点版本元数据证实原版本含有 `HARNESS_NAME`，失败候选没有；四个 MCP 凭证引用均匹配。覆盖全部 `HARNESS_` 字段的环境过滤误把应用身份当作平台 Sidecar 状态。历史 SDK 从 `HARNESS_NAME` 派生根 Agent 名称，缺失时使用默认的 `harness_app`。

FR-8 / T-9 / AC-9：保留源码更新应保留可信原应用的 `HARNESS_NAME`，不受 Sidecar 是否开启影响。继续清理旧 Sidecar 计划、绑定、摘要和凭证。普通代码生成部署沿用既有过滤行为；继续拒绝浏览器环境覆盖。增加先失败的实际部署参数回归、使用过滤后环境的离线 App 启动测试，以及 Sidecar 开关和缺失应用名称的边界测试，纳入强制门禁。审查：这是用户授权范围内对 FR-3 的修复，不改变公共 API，不放宽 MCP 身份校验。真实验收仍待完成。
