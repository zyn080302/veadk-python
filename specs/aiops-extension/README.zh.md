# AI OPS 扩展合同

[English](README.md)

组件：aiops-extension。状态：active（已实现）。更新：2026-10-15。所属代码：veadk/extensions/aiops；兼容导出：veadk/aiops。[变更](../../prd-spec/features/aiops-extension/2026-10-15-optional-plugin.zh.md)。

- CON-1：AIOpsExtension、AgentConfig、AgentPlugin、BuildContext、AgentManifest 公开导入保持轻依赖。导入/构造时不加载 Core、不发现 entry point、不启动进程或网络、不改环境变量。
- CON-2：关闭时 apply(agent) 原样返回对象。create_agent/create_app 要求 enabled=True。启用时按可信名称精确选择 veadk.aiops.backends 注册项，要求 api_version=1 及 callable create_agent/create_app。默认 agentkit 仅在无注册项时兼容导入固定现有包。未知名称、重名、API 不兼容和内部依赖缺失均报错；后端失败不回退。解析结果由各扩展缓存，失败结果不缓存。
- CON-3：构造时固定配置与领域插件；每个 Agent 的工具工厂仍归 Core 管理。传入 Agent 必须未被装配；重复装配按 Core 原合同拒绝。并发调用不共享 provider 资源。注册项包含代码，属于可信安装输入，不能来自客户提示词或 JSON 导入字符串。
- CON-4：新扩展只支持公共可选原生 provider 接口。report_only 因当前后端修改 SDK 全局实现，在加载 Core 前拒绝。provider 生命周期绑定被消费的异步流，覆盖提前关闭、取消和异常。模型/工具历史仍由 Codex 管理。凭证排除 repr/配置序列化，不进入文档和测试。
- CON-5：旧 config/plugin/manifest 路径直接别名到实际定义。旧 hosting 包装保留签名及服务器行为，不保证移除了旧服务器兼容补丁。普通 Agent/Runner、HarnessExtension、默认包依赖及 Studio 路由保持。插件状态不持久化，原生 session 存储继续作为权威。

例子：AIOpsExtension(config=AgentConfig(name="ops", instruction_source="harness_config")).apply(fresh_agent)。create_app() 返回原生 ADK App，其生命周期由原生宿主管理。扩展不启动 sidecar，不提供没有实际资源可关闭的 close 方法。Core/provider 错误传播，不能转成空成功报告。

验证：tests/extensions/aiops 覆盖 CON-1–3、5；provider 合同/原生测试覆盖 CON-4；实际安装 Core 装配验证真实边界。CI 与执行结果记录在关联变更中，不代表已经云端部署。
