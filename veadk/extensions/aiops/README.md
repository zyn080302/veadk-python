# Optional AI OPS extension

[中文](README.zh.md)

`AIOpsExtension` explicitly composes a fresh veADK Agent with a separately installed AI OPS backend. Importing veADK, importing the extension, or constructing an extension does not load Core or discover installed backends. Ordinary Agent/Runner and HarnessExtension users do not need Core.

```python
from veadk import Agent
from veadk.extensions.aiops import AIOpsExtension, AgentConfig, AgentPlugin

# Supply model credentials using your existing veADK environment setup.
fresh_agent = Agent(name="operations")
extension = AIOpsExtension(
    AgentConfig(name="operations", instruction_source="harness_config"),
    plugins=(AgentPlugin("domain", tools_factory=lambda context: []),),
)
agent = extension.apply(fresh_agent)
```

The native veADK Runner runs the resulting Agent. Use `extension.create_app(agent=fresh_agent)` when domain plugins supply ADK App plugins. Supply an uncomposed Agent; do not apply twice or reuse an Agent already owned by another App. `enabled=False` makes `apply(agent)` return that exact object without loading Core; creation methods raise while disabled. The extension owns no server process and has no `close()` lifecycle.

## Installation and version boundary

Install a matching veADK distribution with the `codex` extra and the platform-specific Core distribution supplied with the template. veADK does not depend on or install Core. An absent backend produces an actionable error only on explicit activation.

This API is introduced by this change; older veADK releases need the generic provider hook before they can use it. Existing Core 0.1.46 imports the legacy contract names and works against the new source API. Its published metadata pins a previous SDK build, so a normal package upgrade requires a newly matched Core/SDK release pair. Do not force an incompatible dependency resolution. This SDK change neither publishes that pair nor upgrades an existing template image or Runtime.

## Backend registration

A trusted installed package may register its composition module:

```toml
[project.entry-points."veadk.aiops.backends"]
my_ops = "my_ops.backend"
```

```python
# my_ops/backend.py
api_version = 1

def create_agent(config, plugins, *, agent=None):
    # Compose a fresh Agent using your engine and return it.
    ...

def create_app(config, plugins, *, agent=None):
    # Return the native ADK App, retaining domain ADK plugins.
    ...
```

Select it with `AIOpsExtension(backend="my_ops")`. API version must be integer `1`. Duplicate names or malformed APIs fail before composition; selected-plugin errors never trigger fallback. For existing templates only, the default `agentkit` name can import the fixed `agentkit_aiops` package when no registration is installed. Other names must be registered. Backend objects are cached per extension. Installing and selecting a backend grants it Python execution privileges: neither model output nor editable JSON may choose an import expression.

## Tools, Skills and native execution

`AgentPlugin` retains tool/MCP factories, Skill directories and ordinary ADK callback/App-plugin factories. Stateful tools must be created per Agent. With current Core, `instruction_source="harness_config"` and empty plugins preserve an empty Skill/tool template; the legacy `auto` mode can add the built-in report Skill. Read the backend's domain configuration contract before changing modes.

The generic callable-only `CodexRuntimeConfig.provider_factory` opens an invocation-scoped async context and yields a `CodexProviderEndpoint`. The endpoint can decorate already admitted tool executors; tool names and schemas remain under the existing SDK admission path. Codex continues owning its loop and session history. The provider context closes on normal completion, error, cancellation and explicit stream close. Consumers abandoning a stream must close it, for example with `contextlib.aclosing`.

The factory is excluded from serialized configuration, repr and JSON schema. Credentials stay inside the provider; unrelated Agent headers are not forwarded to its endpoint. Optional shell, compaction and tool-output settings retain native defaults unless configured. `network_access=False` is not an outbound firewall under the read-only sandbox.

## Compatibility and limits

Legacy `veadk.aiops.config/plugin/manifest` imports alias the canonical extension classes. Legacy hosting functions keep their behavior. `hosting.create_server` still contains backend legacy compatibility behavior; this change does not remove all historical patches. The new extension rejects `report_only=True` before Core loading because the current implementation patches SDK globals.

The extension is a Python composition API, not the Studio Harness HTTP interface. Existing `/invoke` and configuration/update endpoints are owned by the template host. Studio Skill/MCP update compatibility does not require enabling this SDK extension. See the [component contract](../../../specs/aiops-extension/README.md) and [verification record](../../../prd-spec/features/aiops-extension/2026-10-15-optional-plugin.md).
