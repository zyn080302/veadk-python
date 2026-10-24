# 保留经过批准的最终正文展示用途

[English](2026-10-24-customer-final-answer-purpose.md)

变更 ID：`customer-final-answer-purpose`；创建/修订：2026-10-24；状态：approved。
组件：[runtime-customer-adk-events](../../../specs/runtime-customer-adk-events/README.zh.md)，CON-2/CON-7。

## 背景与证据

固定 SDK 基线 `a2e6a536171f33183ec579327cdd6566b77f7c08` 有意在重建展示 Event 时排除远端 metadata。SkyEyes 当前由服务端模型适配层区分批准后的最终正文请求与工具旁白。丢弃用途标注会使下游 HTTP 和页面无法安全展示真实正文增量。允许任意 Part metadata 或全部远端 metadata 会削弱现有隔离。

业务方案正本为 `/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/quality-20261022/docs/project/final-answer-stream-design-20261024.md`。适配层、SDK、HTTP 和页面均已有冻结的离线红绿证据；真实模型验收与最终发布制品仍未完成。

## 目标、范围与场景

让 `CustomerAdkEventStream` 仅保留明确且经过校验的最终正文展示标注。这是展示合同，不是研究交付授权或新的鉴权机制。批准和原始来源由配置的 Host 负责。不改公开 Python 签名、依赖、模型、工具调度、Part schema、用户输入、Session 键或持久化 schema。

- FR-1：Host 返回已批准正文增量时，投影保留 `customMetadata.skyeyes_output_purpose={"version":1,"purpose":"final_answer"}`，使用本地 Event 身份；消费者在 Host 完成前收到增量。
- FR-2：其他远端 metadata 继续排除。支持无歧义 snake/camel 别名。保留对象恰好两个字段，version 为整数 1（不是 bool/float），purpose 为精确枚举。非法保留值以 `invalid_output_purpose` 失败，错误不含输入值。
- FR-3：只允许模型正文 Event 使用该标注；不得包含 thought、工具、用户回显或无内容事件。它不授权工具执行，也不修改本地身份/状态。
- FR-4：完整答案仍须等待调度器成功/ACK/清理；取消、错误、缺终帧沿用原失败语义。metadata 不拼造最终文本、不重播增量。

## 设计与合同影响

在 `events.py` 增加一个私有 metadata 投影函数，读取既有顶层 custom-metadata 别名，构建新的白名单对象。创建本地 Event 前检查标注和内容兼容。SDK 不通过推断把 provider 或输入 metadata 提升为用途授权。业务 Host 必须在自己完成批准检查后才生成标注。

现有 Runtime journal 与 ADK 序列化已保留本地 Event 的 custom metadata。用合成本机传输测试真实调度器/Event 流，保留现有排除任意 metadata 的断言。队列容量、期限、取消和清理归属不变。既有单事件 1 MiB/4096 事件限制下，每个 Event 新增固定量校验，不增加网络调用或持久状态。

CON-2 增加严格限定的展示例外；CON-7 定义标注合同。其他组件合同不变：通道分帧、工具及 Session 归属不变。旧 SDK 会忽略标注；下游业务部署须单独构建、验证新的固定制品。

## 任务与验收

| 要求 | 任务 | 验收 | 验证 |
| --- | --- | --- | --- |
| FR-1 | T-1：先新增稳定失败测试，再实现投影函数 | AC-1：完成前收到两个增量，本地身份和精确用途保留 | `tests/runtime/customer/test_output_purpose.py` |
| FR-2/FR-3 | T-2：校验结构/内容与白名单 | AC-2：非法标注/别名/thought/工具/用户事件拒绝，任意 metadata 不保留，输入不变 | 新负例与原 `test_events.py` |
| FR-4 | T-3：取消和完成清理测试 | AC-3：取消关闭流，不拼造或输出最终帧 | 新流测试及现有 customer 回归 |
| FR-1–FR-4 | T-4：SDK 扩展门禁、新制品和安装版消费者联调 | AC-4：测试与 pre-commit 绿色，安装制品与新不可变源码一致 | SDK 门禁及 SkyEyes 安装版 Host/HTTP/历史/页面测试 |

在本 checkout 的专项命令为 `uv run --extra dev pytest tests/runtime/customer/test_output_purpose.py tests/runtime/customer/test_events.py`；扩展门禁为 `uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"`；提交前为 `uv run --extra dev pre-commit run --all-files`。可以用已准备的 SDK 开发 Python 执行相同 pytest 命令，不安装或修改原环境，须记录解释器地址。新增文件自动进入单元测试及既有 customer Harness 门禁。

## 评审、授权与交付记录

用户已明确授权修复全部客户问题并继续完整质量目标，其中包括最终正文流式链路。本 SDK 变更是既有范围的必要实现，不增加云操作或部署。按持续授权无需另行请求许可。`review-spec` 不可用，已直接进行同等设计评审：双语等价、精确白名单、本地身份、工具/thought 排除、固定错误、取消、兼容性及下游制品要求已审查，没有未解决设计阻塞。

远端同步 `git pull --ff-only skyeyes-user feat/skyeyes-harness-20261020` 通过，仍为 `a2e6a536`，用户仓库映射已核实。独立分支为 `fix/skyeyes-final-stream-20261024`。其他 SDK 工作树 dirty、旧 wheel 和原安装环境全部保留。

2026-10-24 验证对应未变更 SDK 基线 `a2e6a536171f33183ec579327cdd6566b77f7c08`，加本次范围内的 `events.py` 修改与新增测试：

- `pass`：冻结旧源码的全部22项新测试均发生实际断言失败；候选与原事件测试组合95项通过。证据：`.codex/output-purpose-complete-frozen-red.xml` 与 `.codex/output-purpose-green-v2.xml`。
- `fail`，保留：第一次完整门禁为83失败、7856通过、50跳过、4 xfail；本地环境影响日志捕获、OpenTelemetry span 和子进程 Node 查找。没有为隐藏失败修改生产源码或已安装依赖。
- `pass`：使用仅含允许字段环境的新子进程，复测所有受影响模块及新测试，538项、0失败/错误、29跳过。证据：`.codex/output-purpose-sdk-environment-recheck.xml`。
- `pass`：新的隔离环境完整 SDK 门禁报告7999项、0失败/错误、50跳过、4 xfail。证据：`.codex/output-purpose-sdk-full-v2.xml`。解释器：`/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.venv/bin/python`；命令：`python -m pytest -n 2 -m "not codex_smoke and not piagent_smoke" --junitxml=<evidence path>`。本次未关闭日志或 OpenTelemetry；首轮失败和复测结果均保留。
- `pass`，仅候选：新 wheel `1.1.18.dev17+ga2e6a5361.sff6cfde173d0` 绑定冻结来源目录 SHA256 `ff6cfde173d03e4d6cac95f483657bfe88476c867cf37983f56246ec2ef00b4e`；wheel SHA256 `a967e6f36369b9f18f7e4f65fd8f12afeda5d16234308cb880fa6e6b635902b4`。其中 `events.py` 与冻结候选逐字一致，已知本地凭证匹配0。候选使用本次文档更新前的快照，未提交，不是发布制品。
- `pass`：安装候选经本地包路径/版本解析核验，叠加既有 Office overlay，在新的本地环境及仅含允许字段的进程环境中通过全部95项用途/事件测试，无失败、错误或跳过。证据：`/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/quality-20261022/.codex/final-stream-installed-sdk-events-20261024.xml`。这仍是安装版 SDK 单元检查，跨进程 Host/HTTP/历史验收待完成。
- `pass`，仅候选：SkyEyes `candidate-v4` 验证实际独立固定 Host、安装版 SDK、业务 SSE、签名 JWT 分页及再次发送。正常完成和 provider EOF 两项均在 provider 完成被阻止时显示两个批准增量，下一轮复用原业务回执。全部测试无跳过，替身进程停止。相同最终测试在未改 SDK 上，两项等待点断言均失败（`old-sdk-red-v3`），依赖/来源核验先通过。证据：`/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/quality-20261022/.codex/final-stream-native-candidate-v4-20261024.json` 及对应旧 SDK 报告。提供方/MCP 使用本机替身，不是真实模型验收。
- `pass`：真实 JWT 历史投影回归在旧业务投影产生3处断言失败，精确用途白名单修复后历史/公开输出相邻29项通过。修复位于业务投影，不修改 SDK 存储。
- `pass`，限定范围：安装候选的 SkyEyes PostgreSQL 53、评测307、后端1302通过；首次完整运行随后因隔离浏览器缓存缺 Chromium 失败，仅失败的前端范围使用既有缓存后通过，74份前端/入口摘要未变。后续新增复核流式测试须重新取得当前源码门禁。
- `pass`，仅候选：SkyEyes `candidate-v6`的标准与B14分别通过独立固定Host / 安装SDK / SSE / JWT历史 / 再次发送验证。每组执行全部5项普通和财务/控制复核正文测试，0跳过，进程已停止。旧SDK（`old-sdk-red-v4`）在业务源码与测试摘要完全相同时产生5项实际断言失败，均已到达provider等待点；原普通、财务、控制及恢复仍通过。安装版完整门禁同时通过PG53、评测308、后端1302与完整前端，587份输入（含73份前端）无变化。证据：`/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/quality-20261022/docs/project/evidence/final-stream-installed-chain-gates-20261024.json`。
- `pass`：定点 fetch `skyeyes-user/feat/skyeyes-harness-20261020`，确认远端基线仍为 `a2e6a536`，与本分支 HEAD 相同。旧 `skyeyes-user/main` 是祖先，并非前移基线。原 dirty 工作树禁用 autostash 的 rebase 拒绝执行，未改文件；clean 隔离 checkout 先成功 rebase 到实际基线，再逐字复制并暂存本功能六文件，原 dirty 工作树保持不变。
- `pass`：隔离 checkout 的 `python -m pre_commit run --all-files` 五项全通过：Ruff check、Ruff format、staged Gitleaks、依赖策略与 YAML 密钥检查。新测试及双语 PRD 已显式暂存以进入密钥扫描，没有文件被修改。随后 `python -m pytest tests/runtime/customer -n 2 -m "not codex_smoke and not piagent_smoke"` 全部378项通过，0失败/错误/跳过，六文件输入摘要未变。两者均使用上文记录的现有开发解释器。证据：`.codex/final-stream-post-sync-precommit-first-20261024.json` 与 `.codex/final-stream-post-sync-customer-units-20261024.json`，报告和 XML 已归档到业务证据正本。这些检查先于本次文档状态同步，生产/测试字节没有变化。
- `fail`，保留：Devbox2 接收无凭证候选上下文并核验全部187依赖 wheel，但任务所在文件系统剩余0字节，准备在服务启动前停止。Devbox1 接收隔离上下文后，因三份固定旧依赖输入全部缺失而失败。对这两个精确任务目录的定点复核确认均未准备完成；Devbox2 剩余0字节，Devbox1 剩余69,849,088字节，均没有准备好的 Host 或业务 Python 环境。没有重启准备、传输凭证、调用模型或写入 Runtime。
- `pass`：双语验证记录同步后，pre-commit 五项同样全部通过；生产/测试字节仍与此前378项和完整7999项测试一致。最终文档摘要及各项结果记录在 `.codex/final-stream-post-sync-precommit-final-20261024.json` 和业务归档中。
- `not_run`：最终提交制品与真实模型验收仍待完成。本机浏览器/替身联调不证明真实模型质量或延迟。

方案保持 approved，尚未完成。风险：旧 SDK 会丢标注，错误配置 Host 可能标错文本，业务批准边界需独立验证。本候选未提交、推送或部署。


## 最新消费端验证与源码检查点（2026-10-24）

消费端应用的正式API现已验证普通对话、企业查询、产品帮助、Word、PPT、Excel及后续轮次在完成前交付最终正文增量。发布构建回执的SDK SHA256等于候选wheel SHA256 `a967e6f36369b9f18f7e4f65fd8f12afeda5d16234308cb880fa6e6b635902b4`；wheel中的 `veadk/runtime/customer/events.py` 与当前源码逐字节相同（SHA256 `36ff4dd42d81ccbb224bc98fda174f424905057f9559265868d02fd219f35bfc`）。这些是真实提供方/MCP/API观察，超出此前本机替身检查。客户实际页面及原反馈可信身份绑定仍未验收；其他业务企业内链失败保留，不能据此认定SDK用途投影存在缺陷。之前未完成准备的记录描述各自历史尝试。

新的有界定点fetch确认目标远端基线仍为 `a2e6a536171f33183ec579327cdd6566b77f7c08`。源码检查点仅允许本功能六份代码、测试、规范和设计文件。原dirty工作树保持，clean隔离checkout先同步再运行pre-commit和单元测试。最终提交版wheel、客户页面验收及完整业务交付仍需各自证据。本记录不宣称完整客户质量目标完成。
