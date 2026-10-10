# 保留源码更新的发布流程

[English](2026-10-10-mpa-lifecycle.md)

Change ID: studio-source-preserving-lifecycle | Date: 2026-10-10 | Status: implemented


## 最终验收（2026-10-10）

本最终记录替代下方历史验证检查点的待验收状态。AC-1 至 AC-3 及 FR-4：pass。最终前端强制门禁 Node 1386 项、React 72 项、生产构建及打包资产通过；pre-commit 通过。正常 Studio 确认流程将授权旧应用从 V55 更新至 V56，MPA Profile 写入为零，页面成功结束。再次打开恢复两项 Skill 和五个 MCP 引用；新会话 Skill/MCP 验收通过。首次 MCP 参数错误由模型纠正，过程仍保留；之前 V55 页面失败没有改记为成功。云端 Studio 和受保护客户 Agent 均未更新。

## 证据与范围
已授权旧应用的更新已完成构建和 Runtime 发布，状态 Ready，四个 MCP 认证均保持；随后 ProjectPreview 在 profile_applying 阶段报 mpa_operation_service_unavailable。Boolean(agentDraft) 把恢复得到的应用草稿判断成 MPA 发布。保留源码更新负责 Skill/MCP 覆盖层，不应调用 MPA Profile 管理。

## 要求与设计
- FR-1：从 CustomCreate 向 ProjectPreview 传递已有 source-preserving/regenerate 编辑方式。明确的保留源码更新不进入 MPA 阶段、不调用 Profile API、不生成 MPA 重试；Runtime 发布成功后正常完成。
- FR-2：普通新建 MPA、regenerate 更新保留 Profile 下发、真实错误处理和 smoke 语义。交由 GitHub 的更新保持现有行为。不得捕获并忽略 MPA API 错误。
- FR-3：Skill/MCP 选择、源码打包、凭证、Runtime 目标、发布次数和普通接口合同均保持。本修复不更新云 Studio 或客户 Agent。

复用 ProjectPreview、确认窗口和全局任务状态。本次只修正流程选择，不涉及样式、输入框、新依赖或视觉组件设计。用一个有类型的可选属性传递现有编辑元数据，不按 Runtime 或 Agent 名称判断。组件合同：[AI OPS extension](../../../specs/aiops-extension/README.zh.md) CON-16。独立 Vulcan/MPA 工作台继续属于 MPA 流程。

## 任务与验收
- T-1 / AC-1：渲染真实 ProjectPreview，发布保留源码 fixture，断言发布一次、Profile 调用零次、终态成功且不含 Profile 进度。修改生产代码前记录 RED。
- T-2 / AC-2：覆盖 regenerate 成功、真实 Profile 错误和非 MPA 代码包路径；组件回归加入强制 npm test。
- T-3 / AC-3：通过前端测试、生产构建、资产完整性和 pre-commit。重开已发布测试 Agent，经 GUI 完成计划中的第二次 Skill/MCP 更新，验收新候选及首条对话。

## 评审与授权
用户已有指令要求完成旧应用的 Studio 更新验证并修复过程中发现的问题。本修复在该授权范围内，不涉及额外资源。review-spec 不可用，执行直接评审：显式编辑元数据、MPA 默认行为不变、无凭证传输变化、保留真实错误、不重复云发布；中英文共同核对，无设计阻塞。

## 验证与风险
FR-4，第二次更新验收发现：当运行时代码拥有动态提示词时，完整的保留源码快照可能含空静态提示词。仅对显式 source-preserving 校验，根节点和子节点不报 missingPrompt；身份、描述、拓扑、凭证、MCP冲突校验保持。新建/重新生成仍严格校验。不得虚构提示词或修改运行时提示词。修复前测试 CustomCreate 的实际校验函数，并保留后端不可修改提示词回归。直接设计评审确认仍在同一已授权更新范围，无新增权限或API。

当前已发布候选保持可用；GUI 失败任务保留为失败证据，不改写为成功。对所有结构化草稿跳过 Profile 会破坏 MPA，因此必须同时测试两种编辑方式。真实云验收和最终文档待完成。

## 2026-10-10 验证记录
真实组件修复前1失败/4通过，修复后5通过；强制前端门禁1,382项Node测试和72项组件测试通过，生产构建通过，资产校验113文件/350引用通过，隔离all-files pre-commit通过。证据 `.codex/source-lifecycle-{red,green,frontend-tests,build,assets,precommit}.log`。第二次GUI发布的真实验收尚未执行。
