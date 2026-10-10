# Codex provider extension

[中文版](README.zh.md)

Component: codex-provider-extension. Status: draft. Date: 2026-10-10.

CON-1: `CodexRuntimeConfig.provider_factory` is an optional trusted callable, excluded from dumps/repr. Serialized configuration cannot select executable factories. Ordinary SDK execution stays unchanged. A factory receives the current Agent and invocation context and returns an async context manager yielding a `CodexProviderEndpoint` with endpoint, credential and extra-body handling declaration. The runtime validates the result, runs the existing Codex implementation and closes the provider on completion, short circuit, error, cancellation or consumer disconnect. Exceptions propagate; the SDK does not switch silently to another provider.

CON-2: Factories are per invocation; endpoint credentials never mutate shared Agent configuration or process environment. The current SDK retains tool execution, history and final-event ownership. An adapter must not claim compatibility by changing those contracts. The endpoint is not persisted with session data; the original Agent identity remains the thread key. No provider is started when a factory is absent.

Tests: tests/runtime/codex/test_provider_extension.py. Related [design](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.md). Implementation and live verification pending.

### Execution policy preservation
The trusted provider endpoint may decorate each already registered SDK tool executor through `wrap_tool_executor(name, executor)`. The SDK still owns schemas, callbacks, invocation identifiers, tool admission/counting, output events and history; a decorator only adds invocation-local capacity/closeout checks and delegates once or rejects explicitly. No arbitrary tool registration or second loop is introduced. Factory teardown encloses tool unregistration. Typed optional `compact_prompt` and `tool_output_token_limit` configure native maintenance and output budgets; absent values preserve upstream defaults. `shell_enabled=false` disables native shell for this template. Core reuses its existing task pool and compaction validation, with regression for cancellation, exclusive tools, invalid summaries and 429 before release.
