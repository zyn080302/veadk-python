# 原生 customer 附件适配

[English](2026-10-20-customer-native-attachments.md)

ID：customer-native-attachments。创建/修订：2026-10-20。状态：approved（实现及验收待完成）。

## 背景与范围

SkyEyes 已允许 PNG/JPEG/WebP/PDF 内联附件，以及带展示元数据的文本附件。CustomerRuntime._new_message 与事件投影目前仅接受文本 Content；原生 HTTP 外层请求限制为 2 MiB。固定原生 Host 校验 Google Content，并在数据库中保留媒体；普通用户输入不通过 SSE 回显。其现有 policy 以追加方式组合模型回调。只放开输入校验不能完成接入。

目标：通过标准 Harness App、Runtime、Host 与会话历史完整保留有界原生用户 Content，PDF 仅在业务 Host 模型边界转换。本改动不增加 URI 获取、媒体输出、工具执行、Shared 附件合同、生产部署、分布式会话恢复或共享额度实现；这些仍是 SkyEyes 整体蓝图中的工作。

## 场景与要求

- FR-1：原生协议下，图片/PDF 或带元数据的文本附件完整到达 Host；元数据为有界 JSON，不解释为配置。接受无歧义的 snake/camel 别名。允许仅附件输入。Shared 仍只接受文本。
- FR-2：远端副作用前校验单个 user Content，最多 8 parts、3 个内联 blob，仅 PNG/JPEG/WebP/PDF；单 blob 4 MiB、解码合计 5 MiB、文本合计 1 MiB、消息 JSON 7 MiB。接受规范的标准或 URL-safe Base64（GenAI JSON 使用 URL-safe），规范化为标准 Base64，匹配文件头；可选 display_name 为 1–180 字符。元数据为 JSON 对象，合计 16 KiB、深度最多 8、单消息最多 256 个值。未知字段、URI/fileData、thought/function parts、歧义别名、错误/空负载或资源超限报固定码，不包含输入。
- FR-3：CustomerRuntime 的原生初始请求使用独立 8 MiB 外层预算；CustomerChannelClient 新增 max_initial_request_bytes=None，默认继承 max_request_bytes。仅原生首个 HTTP 使用它；工具及批量回包默认仍为 2 MiB，输出事件仍为 1 MiB。在 Session HTTP 之前校验完整首包。Shared 大小限制不变。
- FR-4：原附件保留在本地 ADK 与远端 Host 历史中；续问只发送新消息。完成展示的恢复不重放附件/工具；本地 journal 仅记录投影后的 assistant/tool 事件。不增加 store 表结构或大小上限。取消、身份隔离、ACK 与最终答案顺序不变。
- FR-5：SkyEyes 在 Host before-model 回调链中、customer policy 之后组合已有可取消且受限的 PDF renderer。保留原回调及用户事件，只改变模型请求副本。渲染失败/取消不能继续调用模型；图片/文本保留内容与元数据。

## 设计与合同影响

新增内部 messages.py 校验器，由 Runtime 和原生通道输入投影复用。默认投影仍仅文本；CustomerAdkEventStream 从 dispatcher client 判断原生能力。规范化别名，不静默丢弃数据。Shared 不自动获得附件能力。原生首包与后续工具回包使用独立预算。不能为容纳输入而增加 SSE 预算：固定 Host 不回显普通用户附件，原输出限制仍必需。

受影响合同：runtime-customer CON-4、runtime-customer-channel CON-4、runtime-customer-adk-events CON-1。SDK 不解释 tycAttachment/tycTransport，业务边界负责其校验。不改前端、依赖、状态迁移、身份、远端操作或配置覆盖。原附件是调用方私有数据；不记录日志，测试不使用客户真实媒体。

## 任务与验收

| 要求 | 任务 | 验收 | 验证 | 状态 |
| --- | --- | --- | --- | --- |
| FR-1/FR-2 | T-1 校验器、Runtime/投影接通 | AC-1 原字节与元数据保真；非法输入在 HTTP 前拒绝 | tests/runtime/customer/test_native_attachments.py | pass（源码联调；安装制品待验收） |
| FR-3 | T-2 原生首包独立预算与预校验 | AC-2 大型合法输入成功；超限输入/配置和工具批次不发送对应 HTTP | customer 附件/通道测试 | pass（源码联调；安装制品待验收） |
| FR-4 | T-3 真实 Runner/Harness/会话回归 | AC-3 首问/续问/历史/展示恢复/取消保持不变量 | SDK runtime 测试和业务 native-runtime 门禁 | pass（源码联调；安装制品待验收） |
| FR-5 | T-4 业务 Host 回调组合 | AC-4 固定真实 Host 收到渲染后的 PDF；原历史保留；失败/取消不调用模型 | 业务 native 与 native-runtime 门禁 | pass（源码联调；安装制品待验收） |
| 全部 | T-5 同步双语文档，先交付固定 SDK 再业务集成 | AC-5 必需门禁和绑定版本证据，推送独立分支 | AGENTS.md 门禁；固定安装 SDK 业务门禁 | not_run |

专项命令：python3 .codex/run_offline_tests.py tests/runtime/customer/test_native_attachments.py。SDK 全仓使用隔离环境等价执行 uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"；远端同步后、提交前执行 pre-commit。既有 .github/workflows/harness-sidecar-release-gate.yaml 已包含 tests/runtime/customer，自动覆盖新增回归。业务 scripts/check.py --scope native 与 --scope native-runtime 需要固定 customer/Host 源码和隔离环境；安装制品模式须在 SDK 交付之后执行。真实模型/Gateway 与客户原 20 题 A/B 仍是独立待完成验收。

## 风险与审查

Base64/JSON 副本增加内存，但受消息预算约束；并发准入属于后续蓝图工作。通用元数据限制可能拒绝不支持的客户端；SkyEyes 元数据在预算内。长期媒体历史会增长，保留策略/生产恢复仍需后续工作。不增加日志、令牌或媒体转储。模型回调顺序必须保留 customer 工具策略，须核验固定真实源码，不能只有 mock 回调测试。

review-spec skill 不可用，已直接完成同等审查：检查双语等价、职责、别名处理、输入输出预算分离、取消、保存边界、Shared 兼容及可执行门禁，无设计阻塞。授权来源：“你来按蓝图完成适配、性能优化”，以及独立分支提交推送授权；未授权合并或部署。approved 记录已有授权，不代表新确认。不声称生产完成或真实 A/B 已完成。

审查补充：真实 GenAI Blob 将 JPEG 字节序列化为 URL-safe Base64。首轮实现错误拒绝该合法 SDK 输出（1 项失败 / 149 项通过）；改为接受两种规范字母表，拒绝混用或非规范编码。这是原生 Content 字节保真的必要兼容。

## SDK 与固定 Host 源码阶段进展

2026-10-20，SDK 父版本 e5f036052：新增五个真实 Runner 回归在旧代码上均因 unsupported_user_message 失败。实现后 customer 专项 336 项通过。随后新增两项标准 Harness 媒体/历史测试，已纳入正在执行的全仓门禁。业务固定 Host 源码联调 7 项通过，覆盖实际跨进程 SDK/标准 Harness、原 MCP 工具及固定 Host，包括附件首问/续问/本地及 Host 原始历史。PDF Host 回归首先在原业务组合上失败，原因是 PDF 未转换直接进入模型。Host 源码模式证据不是固定 wheel、Linux 或生产验收。已获取 skyeyes-user 分支和 origin/main，均已是 HEAD 祖先（e5f036052 和 402a3da9），无需产生 rebase 改动。该检查点的最终门禁尚未完成；SDK 结果见下文，固定制品验收仍待完成。

## SDK 最终门禁（2026-10-20）

PASS：python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke' — 7899 passed、50 skipped、4 xfailed、6 subtests passed，408.13 秒。跳过/预期失败不计为验收通过。包含两条标准 Harness 附件路由。pre-commit 五项全部通过；双语链接与空白检查通过。源码范围为父版本 e5f036052 加本附件改动；最终运行期间没有修改运行时代码或测试。分支同步仍为前述已获取远端及祖先检查。

首次全仓为 7896 passed 和三项准备错误：隔离的 sidecar wheel 测试无法下载 setuptools/setuptools-scm。使用测试环境的 uv 0.13.1，在专用离线缓存准备公开构建依赖，三项原测试单独重跑成功，随后完整重跑得到上述结果。没有删除或弱化门禁。离线包装器使用合成配置并阻止 Python 非本机网络调用。

业务 c8f4308 已记录固定 Host 36 项及源码跨进程 7 项通过。T-1 至 T-4 具有源码模式证据。T-5 仍待干净 wheel、业务固定安装及对应制品验收；交付状态在[业务附件正本](/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/docs/project/customer-native-attachments-design.md)维护。不声称生产/云服务或客户原 20 题已通过。
