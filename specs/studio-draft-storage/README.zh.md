# Studio 草稿存储

[English](README.md)

- 组件：studio-draft-storage；状态：draft；修订日期：2026-10-10。
- 范围：frontend/src/create/agentDraftStorage.ts 和 mcpAuth.ts；测试：frontend/tests/agentDraftStorage.test.mjs。
- 相关设计：[AI OPS Harness 模板](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.zh.md)。

## 职责与接口
浏览器通过 writeWorkspaceDrafts/loadWorkspaceDrafts 保存用户隔离的工作区草稿，由 sanitizeAgentDraftForStorage 脱敏。MCP 原值只留在内存；后端负责凭证解析并校验 Agent/名称/URL 身份。本组件不负责资源鉴权或部署授权。

## 合同
- CON-1：MCP authToken 原值及 deployment.envValues 中对应的值不得进入序列化草稿，覆盖子 Agent 和工作流节点。
- CON-2（拟修复）：服务端确认 credentialConfigured=true 的工具，在为编辑回填原值后仍保留已有 authTokenEnv。保存、读取和生成发布参数后引用保持，刷新不会删除鉴权。
- CON-3：新输入或替换的临时密钥不变成持久凭证。明确清空时删除引用和已配置标记。不推测缺失引用，不挂载其他端点的密钥。
- CON-4：prepareMcpAuth 从发布草稿移除界面凭证标记和密钥原值；后端仍负责引用身份、缺失原值及端点变更校验。

## 状态、持久化和失败
localStorage 的版本1格式保持兼容。序列化同步执行、不修改原草稿，重复保存读取保持幂等。非法格式和存储失败沿用现有错误。已损坏草稿无法恢复被删除的引用，应重新打开具体已部署 Agent。不新增日志、密钥存储、网络调用或全局可变状态。

## 验证与变更记录
CON-1 至 CON-4 对应 agentDraftStorage.test.mjs 的回填/保存/读取/发布参数测试及既有 mcpAuth 测试，由 npm --prefix frontend test 和强制前端 Harness 门禁执行。构建与真实浏览器刷新更新验收单独报告。2026-10-10 修复当前为设计状态，未宣称线上成功。
