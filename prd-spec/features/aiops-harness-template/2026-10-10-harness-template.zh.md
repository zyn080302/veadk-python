# AI OPS Harness App 行业模板

[English](2026-10-10-harness-template.md)

- Change ID：aiops-harness-template
- 日期：2026-10-10
- 状态：implemented
- 授权：用户明确要求实现 Harness App 接口、更新镜像，并验证 Studio 参数更新。Runtime 写入仍仅限旧应用 v4；客户 v4-2、其他 Agent 和云端 Studio Function 受保护。


## 最终验收（2026-10-10）

状态：implemented。本记录替代下方历史检查点的待验收状态。同步的上游基线为 `812faadfe9952d47d1efc7b0a32595beafa58b91`。SDK `1.1.14.dev61+g812faadfe.aiopsharness2`、私有 Core 0.1.44 和领域插件 0.1.53 已在 Linux 构建并验证。

| 验收项 | 结果 | 证据范围 |
| --- | --- | --- |
| AC-1 / AC-3 | pass | YAML、引用隔离、空选择和真实宿主/通道回归；正式健康/配置/调用与同会话续接 |
| AC-2 | pass | Core 强制门禁：当前 SDK 257 项、真实 CLI 7 项、历史 SDK 302 项通过；当前链路跳过 15 项历史专用测试 |
| AC-4 | pass | 两个不可变镜像均 Succeeded，精确 digest、依赖及真实 CLI 自测通过；正式 Runtime 使用应用镜像验证 |
| AC-5 | pass | 实际 Studio 从 V55 再更新至 V56，MPA Profile 调用为零；Skill 激活回执和终稿含新标记，MCP 手册读取成功 |
| AC-6 | pass | 中文客户教程、已检查的真实脱敏截图与本地链接 |

新镜像在 V58/V59 完成正式 Harness 配置验收。V58 首次追问漏格式标记；同会话提醒后恢复，提醒没有提供答案或标记，也没有再次调用工具。V59 使用新配置，两轮均通过。不能报告为无条件首次格式遵循成功；真实原生回归已验证每次上游请求都保留客户附加指令。

V60 恢复原入口/环境并保留新镜像；新会话 Skill 激活、成对工具回执和终稿中的精确新标记、MCP 手册调用及 sourceOverlay 元数据均通过。九个受保护 Runtime 的版本和配置摘要保持不变。临时 TYPE 仅删除一次；随后 GetRuntime 省略系统标签，精确目标的 Tag.GetResources 已验证原完整标签摘要，没有追加写入。

最终 SDK 回归：7159 passed、70 skipped、4 xfailed。前端：Node 1386 项、React 72 项、生产构建及打包资产检查通过；变更文件 Pyright 新增诊断为零。领域插件双 SDK 门禁分别为 360 passed/1 skipped 和 352 passed/2 skipped。跳过项不能证明对应行为。

范围：通用镜像完成构建内自测，没有单独创建 Runtime；未登记或修改 Studio 模板选择器，未发布云端 Studio 更新通道。旧覆盖层 Skill 没有云绑定 ID，因此 Harness 验证使用零个云 Skill、五个 MCP；恢复后的旧入口验证实际两项 Skill。截图记录真实 V55/V56 页面，不能作为后续配置 API 发布的页面证据。原弹性范围仍为 0–10；Managed shared 不在范围内。

## 证据与目标
参考实现为 agentkit-studio/servers/harness_app_server。其固定配置镜像消费 AGENT_CONFIG（agentkit/v1），提供 GET /agent_config、/healthz、标准 invoke/session/SSE/A2A 及 studio-tool-channel/1 HTTP/SSE 接口。Studio 独立通过 TYPE=HARNESS 识别类型。当前 AI OPS Core 可组装 veADK Agent，但缺少这套可移植 YAML 宿主合同。Core 仍导入主线已删除的 native_bridge/native_responses；公共配置可导入或容器 Ready 不能证明兼容。

此前来源保持候选已加载报告 Skill，但第一次 MCP 文档调用失败且缺少 sourceOverlay，因此没有通过验收。本功能扩展此前集成范围，保留原回归证据。

## 需求与场景
- FR-1：通用镜像实现参考实现的固定配置 Harness App 合同，不依赖 Studio 后端，不复制 SDK 执行代码。给定准备好的 agentkit/v1 YAML 和独立注入的凭证，启动时构造一个 AI OPS Agent，并返回原始安全配置。
- FR-2：模型、客户附加指令、Skill、MCP 更新在部署重启后生效，并可回读用于下次编辑。空选择清除旧选择。非法或未解析的绑定须在 Ready 前明确失败；不生成替代 Agent，不允许任意导入路径。
- FR-3：保留 AI OPS 唯一推理内核、领域工具策略、预算、核心提示词保密及取消保障。公共 veADK 管公共合同，私有二进制管推理行为。修复 Core 与当前主线的兼容，不替换上游默认运行时，也不静默绕过提示词保护。
- FR-4：Studio HTTP/SSE 工具使用不可变的本轮快照，有界调用、身份与版本检查、取消及清理。只声明实际实现的能力。普通调用不能继承其他轮的工具、Skill 或凭证。
- FR-5：离线门禁通过后发布不可变候选镜像，只更新授权的旧应用 v4。恢复原五个 MCP 来源，验证真实 Skill/接口文档调用、配置往返、真实 Studio 编辑及保护资源摘要。
- FR-6：提供模板示例和含真实脱敏截图的中文教程，区分镜像能力、模板注册、本地 Studio 验证和尚未进行的云 Studio 发布。

## 设计与边界
veadk.aiops 下的公共适配模块校验版本化 YAML，挂载配置接口，复用 SDK Agent/App/session/tool 服务并懒加载私有内核。领域插件由可信镜像入口显式传入，不从 YAML 导入。不选择该宿主的既有应用保持原行为。Runtime 标签标识 Harness，纯参数更新保留镜像。凭证使用环境变量引用，不进入公开 YAML、错误、镜像、构建上下文或证据。

参考实现的 Managed shared 模式具有不同部署归属；本任务实现固定配置模板接口，普通调用与 Studio 通道使用同一执行链。没有新调查状态机或报告改写模型。原生运行兼容须在发布前单独验证。主线新增能力显式启用，保留 SDK 默认值。有状态工具通道需要单 worker 与实例亲和；不静默修改用户弹性配置。

## 任务与验收
| 任务 | 验收 | 验证 |
| --- | --- | --- |
| T-1 | AC-1：安全 YAML、引用与更新往返 | 先失败的 schema/凭证/重复键/空选择回归及参考消费者合同 |
| T-2 | AC-2：主线 SDK 上真实 Core 装配 | 实际内核测试，含最终传输、预算和事件；私有强制门禁 |
| T-3 | AC-3：配置、健康、调用、会话、通道 | 实际 ASGI 路由，身份/版本/迟到结果/取消反例 |
| T-4 | AC-4：不可变镜像复现接口 | Linux 隔离构建、依赖检查、镜像验证和 digest |
| T-5 | AC-5：v4 连续两次真实 Studio 编辑 | 真 UI 与正式 API、候选来源及全部保护资源摘要 |
| T-6 | AC-6：客户步骤与实测一致 | 截图及 Markdown 链接审阅 |

## 设计审查与风险
review-spec 不可用，直接审查设计。配置保持公开并兼容参考合同，私有凭证只在进程内解析；解析/传输与内核分责。不跨轮修改共享 Agent，不隐式回退，不公开私有提示词。行为修改前先写失败回归并纳入强制门禁。用户请求已授权此范围的实现，不扩展到其他 Runtime 或云 Studio 发布。主线内核兼容和精确镜像发布路径仍是待验收工作，不是已验证结论。

## 验证记录
设计建立时 AC-1 至 AC-6 为 not_run。此前 veADK 完整回归 6789 passed、74 skipped、无失败/错误（共 6863）。此前 V50 Skill 激活通过，MCP 文档调用失败；均不能作为新 Harness 实现通过的证据。

## 主线传输接入细化
当前 SDK 已拥有原生 Codex 线程与 MCP 执行，保留该路径。在 CodexRuntimeConfig 增加可选的程序化 provider factory，排除序列化，YAML 不可配置。它拥有每次调用的异步上下文，提供临时模型端点；默认路径不变。私有内核在此边界提供本地 Responses 传输适配：私有提示词、既有报告/收尾策略及后端选项只在发往 Provider 前于内存处理，不执行工具、不另存第二份会话。工具、历史、终稿事件与取消仍由 SDK 负责。factory 必须在提前返回、异常、取消和消费者断开时关闭。仅当前主线 SDK 使用此适配替代旧私有接线；历史兼容回归保留独立消费者验证环境。修改 runtime 前先补上下文生命周期与隔离 RED；新私有适配须通过实际 CLI/模型传输合同后才能发布镜像。

### 保留执行策略
用户明确：通用 Harness 默认没有 Skill 和工具，领域 Skill、本地工具和 MCP 适配器由具体 Agent 插件提供。空的 Harness 配置不能重新启用旧的 incident-report 兜底，也不注册 Skill 读取工具；已有非 Harness 消费者保持原行为。使用真实 Core 回归空选择和具体 Agent 本地工具。

完整门禁发现：Python 3.13 关闭已满的 A2A 派生队列时，会把 QueueShutDown 传给原任务。仅对已关闭且属于当前订阅的队列吞掉此异常，保留取消、其他异常和其他订阅。Skill worker 异常结果必须返回脱敏 HarnessConfigurationError 并清理临时资源。已有 RED 回归覆盖两处问题。

受信任 Provider endpoint 可通过 `wrap_tool_executor(name, executor)` 装饰 SDK 已注册的工具执行器。SDK 继续拥有 schema、回调、调用标识、工具准入及计数、结果事件和历史；装饰器只增加本次调用的容量/截止检查，委托一次或明确拒绝。不注册任意新工具，不引入第二个循环。工厂清理范围包含工具注销。可选类型化 `compact_prompt` 和 `tool_output_token_limit` 配置原生整理与输出预算；不配置时保持上游默认。模板用 `shell_enabled=false` 禁用原生 shell。Core 复用现有任务池与压缩校验，发布前回归取消、互斥工具、无效摘要和 429。

### 完整回归检查点
本轮完整套件结束：6,836 passed、74 skipped、1 failed。唯一失败是禁用通道 HTTP 测试仍断言旧的三个字段；已同步断言 skills=false 与 long_running_tools=false，符合显式能力合同。本次修正未更改产品行为，最终完整套件确认仍待完成。

### 静态验证
2026-10-10，pre-commit --all-files 通过。Pyright 检查30个新增/修改产品文件，报告47项；使用相同环境检查对应主线文件得到完全相同的47项，新增诊断为0。这不代表修复了仓库存量类型问题。禁用通道HTTP专项12项全部通过。

### SDK 最终完整回归
2026-10-10：最终完整 SDK 套件通过，6,837 passed、74 skipped、0失败/错误（共6,911项）。证据：`.codex/harness-full-regression-final.xml`。跳过项不证明相关行为通过；Linux打包、镜像和真实Studio验收仍待完成。

### 真实无状态缓存兼容问题
V51 已 Ready，但首次真实 Skill/MCP 调用在工具执行前失败。私有主线 Provider 将 SDK 默认 caching/expire_at 与 store=false 一起发送。同模型无业务数据对照：保留该组合返回400，仅移除这两个参数返回200；namespace 工具声明单独可接受。仅修改私有发送边界，省略依赖服务端存储的缓存参数，保留 store=false、原生历史、prompt_cache_key 和工具路由；SDK 默认行为及公共接口不变。补齐策略和严格真实 CLI/镜像夹具的 RED/GREEN，重建并重新真实验收。之前绿色门禁不覆盖这个新发现。

### 非 root 镜像的保留源码更新
首次 Studio h1 构建在更新 Runtime 前失败：镜像继承的非 root 用户无法读取从严格权限的本地归档复制进去、由 root 所有的校验文件。第二次更新时删除旧的 root 所有覆盖目录也会失败。保留原 USER、CMD 与 ENTRYPOINT；每次更新生成由内容摘要确定的独立覆盖目录，COPY 显式设置可读及可遍历权限，不删除父镜像文件。Runtime 与镜像环境必须指向同一新目录。公开且无凭证的布局标记为 OCI 恢复选择当前目录，并兼容旧固定路径。旧层按不可变镜像历史保留未启用资产；只能读取最终选择清单与当前目录。非法布局、符号链接、缺少当前清单和无法恢复的旧 Skill 必须拒绝。

本修复属于已授权的 Studio 更新验收必要范围。直接设计审查：没有新增远程执行、没有提高 Runtime 用户权限、布局标记不含私有数据，不影响普通生成 Agent 或非覆盖更新。先补严格归档权限、连续两次更新与旧文件删除、Runtime/镜像路径一致、旧路径迁移及非法标记回归，纳入强制门禁后再重试真实 GUI 构建。

### 非 root 覆盖层验证检查点
2026-10-10：RED 回归复现 5 项失败。针对性 GREEN：73 通过。当前强制后端 Workflow 全部通过：coverage 150 通过/1 跳过，覆盖率 96%（门槛 91%）；lifecycle 9 通过；credentials 211 通过；release 81 通过。完整 SDK 回归：7159 通过、70 跳过、4 xfailed，零意外失败/错误，430.164 秒。Pre-commit 通过；变更文件 Pyright 的 72 项存量诊断与冻结对照基线一致，新增 0。证据：`.codex/nonroot-overlay-full-r4.xml`、`.codex/nonroot-overlay-gates-r4/` 与 `.codex/nonroot-overlay-pyright-comparison-r4.json`。真实 GUI 已仅对授权旧应用提交重试，构建、发布与首条对话验收仍待完成。

### 刷新后恢复已回填的 MCP 凭证引用
V53 构建成功但启动失败：四个 MCP 条目丢失 Authorization 和全部凭证引用环境变量，V52 的五个连接仍带鉴权。恢复后的浏览器草稿保持 credentialConfigured=true，却没有 authTokenEnv。根因是保存草稿时，把服务端回填的已有凭证误当成新输入的临时密钥，连同已有引用一起删除。使用四个独立合成凭证的本地启动通过。

在已有 Studio 更新授权内，保留每个已配置工具的已有凭证引用，继续移除密钥原值和 deployment 中的值。新输入或替换的密钥仍只留在内存，明确清空鉴权的操作保持有效。不跨 Agent/名称/URL 复制凭证，不放宽领域校验，服务端继续按已发布快照核对身份后解析引用。已经损坏的旧草稿应重新打开具体已部署 Agent，不按工具位置猜测引用。回归覆盖回填→保存→刷新读取→生成发布参数，包含根 Agent、子 Agent 和工作流工具，验证密钥不持久化，并保留替换/删除的反向用例。现有前端发布门禁必须执行这些回归；更新 studio-draft-storage 组件合同，真实刷新后更新验收通过才可宣称完成。

直接设计评审：仅修状态序列化，不新增 API、密钥存储、远程 shell 或资源范围。用户已有授权覆盖本项必要修复；无视觉/组件改动。此检查点实现和真实验收尚未完成。

### 部署身份迁移问题
首次当前主线 Harness 发布在创建 App 前失败。使用其原环境离线启动可复现 HarnessConfigurationError：旧 HARNESS_NAME 保存带连字符的 Runtime 显示名称，而显式覆盖值必须是合法的 SDK Agent 标识；参考 Harness 同样拒绝该值。迁移环境改用经过校验的 YAML Agent 身份；旧入口恢复原环境。不放宽身份校验，也不把不同显式身份规范化到同一个命名空间。这是部署请求修正，不改变产品合同，无需重建相同 wheel。先保留失败的请求检查与原环境启动复现，再修正配置；下一次发布前把真实 Core 身份边界加入强制门禁。Runtime 版本元数据不返回系统标签，标签保留应读取 Runtime 元数据，并按 Key/Value 规范化比较。

### 真实追问验收
V58 首轮正式调用通过工具执行、配置标记与结果检查。同会话追问保留了计算结果且未调用工具，但遗漏要求的标记；保留本次失败验收。归因于模型行为前，扩展真实原生两轮传输回归，确认客户附加指令到达每次实际上游请求，包括续接和 429 重试。该现象本身不改变产品合同，也不需要额外 Runtime 发布。

新增原生传输断言已通过完整私有 Core 门禁：当前 SDK 257 项、真实 CLI 7 项、历史 SDK 302 项；当前路径跳过的 15 项只覆盖历史内部实现。每次实际首轮、工具后续、会话续接及 429 重试请求均保留客户附加指令。针对已观察到的格式遗漏没有修改产品代码。原线上会话仅补充遵守当前配置格式的提醒（不提供答案或标记），即恢复正确标记与记住的结果，且未调用工具。记录为经追问提醒后通过，不能写成首次成功。

已有 Runtime 的更新接受 Tags 字段但未改变资源标签；参考部署在创建时写 TYPE。本次授权迁移通过正式资源标签 API 对精确 Runtime 补写并验证 TYPE=HARNESS，恢复旧配置时只移除此新增标签。这是元数据操作，不需要重新构建镜像。
