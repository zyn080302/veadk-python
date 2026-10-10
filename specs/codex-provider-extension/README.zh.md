# Codex Provider 扩展

[English](README.md)

组件：codex-provider-extension。状态：draft。日期：2026-10-10。

CON-1：`CodexRuntimeConfig.provider_factory` 为可选可信 callable，不进入 dump/repr，序列化配置不能指定可执行 factory。普通 SDK 执行保持原样。factory 接收当前 Agent 与调用上下文，返回异步上下文管理器，产出包含端点、凭证和 extra-body 处理声明的 `CodexProviderEndpoint`。runtime 校验结果，运行既有 Codex 实现，在正常结束、短路、异常、取消或消费者断开时关闭 provider。异常继续传播，不静默切换 Provider。

CON-2：factory 按调用隔离；端点凭证不修改共享 Agent 配置或进程环境。工具执行、历史和终稿事件仍由当前 SDK 负责，适配不能以改变这些合同冒充兼容。端点不持久化到会话，线程键沿用原 Agent 身份。缺少 factory 时不启动任何 Provider。

测试：tests/runtime/codex/test_provider_extension.py。关联[设计](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.zh.md)。实现及真实验收待完成。

### 保留执行策略
受信任 Provider endpoint 可通过 `wrap_tool_executor(name, executor)` 装饰 SDK 已注册的工具执行器。SDK 继续拥有 schema、回调、调用标识、工具准入及计数、结果事件和历史；装饰器只增加本次调用的容量/截止检查，委托一次或明确拒绝。不注册任意新工具，不引入第二个循环。工厂清理范围包含工具注销。可选类型化 `compact_prompt` 和 `tool_output_token_limit` 配置原生整理与输出预算；不配置时保持上游默认。模板用 `shell_enabled=false` 禁用原生 shell。Core 复用现有任务池与压缩校验，发布前回归取消、互斥工具、无效摘要和 429。
