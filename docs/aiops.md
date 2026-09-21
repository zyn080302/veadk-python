# AIOps extensions

`veadk.aiops` provides public configuration and plugin contracts. These interfaces
ship in `veadk-python`; a separate `agentkit-aiops-sdk` package is not required.

```python
from veadk.aiops import AgentConfig, AgentPlugin
from veadk.aiops.hosting import create_server

plugin = AgentPlugin(name="my_tools", tools_factory=lambda context: [])
config = AgentConfig(name="my_agent", customer_instruction="Customer additions")

# The host must separately install its platform-specific AIOps binary wheel.
app = create_server(config, (plugin,))
```

Public modules:

| Module | Purpose |
| --- | --- |
| `veadk.aiops` | `AgentConfig`, `AgentManifest`, `AgentPlugin`, `BuildContext` |
| `veadk.aiops.hosting` | Lazy entry points: `create_agent`, `create_app`, `create_server` |
| `veadk.aiops.services` | Host-service calls for reviewed tool adapters |

Installing or importing these interfaces does not install or load the private
engine. Hosting entry points raise an actionable error when the binary engine
is absent. Failures in the engine's own dependencies are preserved.

The `agentkit-aiops-agent` repository, engine, investigation logic and core
system prompt remain proprietary. None is included in this source tree or the
veADK wheel. Customer instructions use an additive configuration field; there is
no public field for replacing the core prompt or loading a custom core prompt.

For source migration, replace `agentkit_aiops_sdk` imports with `veadk.aiops`,
including `.hosting`, `.services`, `.manifest`, `.config` and `.plugin`. Use a
matching engine release and veADK wheel that includes these interfaces. Older
published wheels retain their original dependency contract.

## Source-preserving Studio updates

Applications that wrap MCP tools may set a callable
`_veadk_studio_mcp_overlay_handler` on each Agent. During App initialization,
Studio passes that Agent's selected canonical MCP entries to the handler and
leaves its tools intact. The handler must apply the selection through its own
adapters or verify that construction already applied exactly that selection.
Empty selections are meaningful. An exception fails startup; Studio never falls
back to adding unwrapped tools after a handler error. Agents without a handler
retain Studio's default MCP replacement behavior.

The private AIOps runtime resolves the image overlay before domain factory
construction and verifies it during App initialization. Its per-Agent environment
copy keeps credential values out of shared process configuration and Studio drafts.

## Customer instructions in Runtime configuration

The matching AIOps engine reads `AIOPS_CUSTOMER_INSTRUCTION` at startup. When
present, this value takes precedence over manifest additions and local SQLite;
an empty string explicitly clears the additions. Only customer text belongs in
this variable. The proprietary core prompt remains separate and is injected
first at the model boundary. Without the variable, local development retains
the existing SQLite behavior.

For a cloud Runtime, Studio's **Save and publish** action updates this variable
through `GET/PUT /web/runtime-instruction/{runtime_id}/{app_name}?region=...`.
The route requires management permission, Runtime ownership and an editable
review state. It preserves other environment values and publishes configuration
without rebuilding the image. Existing instances keep their startup value until
the new Runtime version is ready. Reopen or reload the editor to confirm the
published version; acceptance of a request is not confirmation of activation.

The editor checks the observed Runtime version and serializes writes within its
Studio process. AgentKit does not provide a conditional update operation, so
this is not an atomic lock against other Studio instances or control-plane
writers. After an uncertain response, verify the Runtime before retrying.
Values must contain no NUL and fit within 64 KiB in UTF-8; the platform may
enforce a lower environment limit. The variable is Runtime-wide, so this mode
is intended for one independently configured AIOps agent per Runtime.
