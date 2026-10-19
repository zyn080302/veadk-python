# Harness 服务嵌入

[English](README.md)

组件 ID：harness-service。日期：2026-10-20。状态：本地已实现，发布验证待完成。
关联已批准变更：[harness-service-integration](../../prd-spec/features/harness-service-integration/2026-10-20-public-app-and-session.zh.md)。

## 职责与接口

HarnessApp 负责 HTTP/ADK 适配；调用方提供 Agent 和 ShortTermMemory。模型执行、身份授权和后端存储分别负责。

- CON-1：从 `veadk.cloud.harness_app.app` 导入 `HarnessApp` 不创建默认 Agent/App。`create_default_harness_app()` 显式创建，`get_default_harness_app()` 按进程缓存。旧模块 `app`、`harness_app` 属性与模块执行复用缓存默认实例。
- CON-2：`ShortTermMemory(session_service=service)` 接受已有 BaseSessionService，只读属性返回同一对象；显式冲突存储配置拒绝；输入对象排除 repr/序列化。调用方负责释放；原回调包装会修改 get_session，共享服务不能配置不同回调包装。
- CON-3：`create_session` 只定点读取 app/user/session，不存在才创建；不列历史、不记录数据库 URL。创建回调仅在新建后执行，存储失败/取消向上传播；重复创建遵循后端冲突语义。
- CON-4：委托的 ADK `/run`、`/run_sse` 按轮应用 `HarnessApp.max_llm_calls`。`None` 保留 ADK 默认，非正数保持 RunConfig 语义。不存在的会话仍返回 404；事件拆分、metadata、错误与断连取消由 ADK 负责。显式 Harness 覆盖保留原优先级。这是模型次数默认值，不是租户配额控制；A2A/实时音频不在此保证内。设计与验证：[HTTP 调用上限](../../prd-spec/bugfixes/harness-http-call-limit/2026-10-20-delegated-run-limit.zh.md)。

## 状态、兼容与隔离

默认运行时缓存仅在本进程显式访问时创建。原后端构造、HTTP 路由与会话 schema 保持兼容。不隐式增加身份授权或分布式租约。注入服务对象不进入公开 memory 序列化字段。既有连接配置字段保留原序列化行为，调用方必须将这些字段视为敏感内容，不得记录或发布。验证不需要云操作。

## 验证与变更记录

CON-1 对应 tests/cloud/test_harness_app_embedding.py 和既有 HTTP 测试。CON-2/CON-3 对应 tests/test_short_term_memory.py，覆盖注入、序列化、冲突、原本地/SQLite 行为、回调、定点读取、异常和取消。命令和证据见关联 PRD；定向合同已通过关联 PRD 所列检查，更广交付要求仍待完成。
