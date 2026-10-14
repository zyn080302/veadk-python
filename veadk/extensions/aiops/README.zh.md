# 可选 AI OPS 扩展

[English](README.md)

`AIOpsExtension` 将一个新的 veADK Agent 显式接入独立安装的 AI OPS 后端。导入 veADK、导入扩展或构造扩展对象，都不会加载 Core 或发现已安装后端。普通 Agent/Runner 和 HarnessExtension 用户不需要 Core。

```python
from veadk import Agent
from veadk.extensions.aiops import AIOpsExtension, AgentConfig, AgentPlugin

# 模型凭证沿用已有 veADK 环境配置。
fresh_agent = Agent(name="operations")
extension = AIOpsExtension(
    AgentConfig(name="operations", instruction_source="harness_config"),
    plugins=(AgentPlugin("domain", tools_factory=lambda context: []),),
)
agent = extension.apply(fresh_agent)
```

结果由原生 veADK Runner 运行。领域插件提供 ADK App 插件时，使用 `extension.create_app(agent=fresh_agent)`。传入尚未装配的 Agent，不要重复 apply 或复用其他 App 已持有的 Agent。`enabled=False` 时，`apply(agent)` 原样返回对象且不加载 Core；创建方法会明确报错。扩展不持有服务进程，没有 `close()` 生命周期。

## 安装与版本边界

安装配套的、带 `codex` extra 的 veADK 发行包，以及模板提供的对应平台 Core 发行包。veADK 不依赖、也不自动安装 Core。缺少后端只在显式启用时产生可操作的错误。

此 API 由本改动引入；旧 veADK 需要先具备通用 provider hook 才能使用。现有 Core 0.1.46 通过旧合同名称导入，可与新源码 API 配合。它的已发布元数据仍锁定旧 SDK 构建，因此正常包升级需要重新配套发布 Core/SDK。不要强行绕过依赖解析。本 SDK 改动没有发布这组配套包，也不会升级现有模板镜像或 Runtime。

## 后端注册

可信的已安装 Python 包可以注册装配模块：

```toml
[project.entry-points."veadk.aiops.backends"]
my_ops = "my_ops.backend"
```

```python
# my_ops/backend.py
api_version = 1

def create_agent(config, plugins, *, agent=None):
    # 使用后端装配并返回新的 Agent。
    ...

def create_app(config, plugins, *, agent=None):
    # 返回原生 ADK App，保留领域 ADK 插件。
    ...
```

通过 `AIOpsExtension(backend="my_ops")` 选择。API 版本必须是整数 `1`。重名注册或不合规 API 在装配前失败；选定插件加载失败后绝不回退。仅为兼容现有模板，默认 `agentkit` 在没有注册项时可以导入固定的 `agentkit_aiops` 包。其他名称必须注册。后端对象在单个扩展实例内缓存。安装和选择后端意味着允许执行其 Python 代码；模型输出或可编辑 JSON 都不能指定导入表达式。

## 工具、Skill 与原生执行

`AgentPlugin` 保留工具/MCP 工厂、Skill 目录和普通 ADK 回调/App 插件工厂。带状态工具必须按 Agent 创建。当前 Core 在 `instruction_source="harness_config"` 且插件为空时保持 Skill/tool 为空；旧 `auto` 模式可能添加内置报告 Skill。切换模式前应遵循后端的领域配置合同。

通用、仅接受 callable 的 `CodexRuntimeConfig.provider_factory` 打开单次调用的异步上下文，返回 `CodexProviderEndpoint`。端点可装饰已经获准的工具执行器；工具名称和 schema 仍由 SDK 原有准入路径控制。Codex 继续管理循环和会话历史。provider 上下文在正常结束、异常、取消和显式关闭流时释放。消费者提前停止读取时必须关闭流，例如使用 `contextlib.aclosing`。

工厂不进入序列化配置、repr 或 JSON schema。凭证留在 provider 内部；Agent 上无关的请求头不会转发到其端点。Shell、压缩、工具输出设置未显式配置时保留原生默认值。只读 sandbox 下的 `network_access=False` 不是出口防火墙。

## 兼容与限制

旧 `veadk.aiops.config/plugin/manifest` 路径导出相同的规范扩展类型。旧 hosting 方法保留行为。`hosting.create_server` 仍包含后端的旧兼容行为；本改动没有移除所有历史补丁。新扩展在加载 Core 前拒绝 `report_only=True`，因为当前实现会修改 SDK 全局对象。

此扩展是 Python 装配 API，不是 Studio Harness HTTP 接口。`/invoke` 和配置/更新端点由模板 host 提供。Studio 的 Skill/MCP 更新兼容并不要求启用此 SDK 扩展。参见[组件合同](../../../specs/aiops-extension/README.zh.md)与[验证记录](../../../prd-spec/features/aiops-extension/2026-10-15-optional-plugin.zh.md)。
