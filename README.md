<p align="center">
    <img src="assets/images/logo.png" alt="Volcengine Agent Development Kit Logo" width="50%">
</p>

# Volcengine Agent Development Kit

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Deepwiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/volcengine/veadk-python)

An open-source kit for agent development, integrated the powerful capabilities of Volcengine.

For more details, see our [documents](https://volcengine.github.io/veadk-python/).

A [tutorial](https://github.com/volcengine/veadk-python/blob/main/veadk_tutorial.ipynb) is available by Jupyter Notebook, or open it in [Google Colab](https://colab.research.google.com/github/volcengine/veadk-python/blob/main/veadk_tutorial.ipynb) directly.

## Installation

### From PyPI

```python
pip install veadk-python

# install extensions
pip install veadk-python[extensions]
```

### Build from source

We use `uv` to build this project ([how-to-install-uv](https://docs.astral.sh/uv/getting-started/installation/)).

```bash
git clone ... # clone repo first

cd veadk-python

# create a virtual environment with python 3.12
uv venv --python 3.12

# only install necessary requirements
uv sync

# or, install extra requirements
# uv sync --extra database
# uv sync --extra eval
# uv sync --extra cli

# or, directly install all requirements
# uv sync --all-extras

# install veadk-python with editable mode
uv pip install -e .
```

## Configuration

We recommand you to create a `config.yaml` file in the root directory of your own project, `VeADK` is able to read it automatically. For running a minimal agent, you just need to set the following configs in your `config.yaml` file:

```yaml
model:
  agent:
    provider: openai
    name: doubao-seed-1-6-250615
    api_base: https://ark.cn-beijing.volces.com/api/v3/
    api_key: # <-- set your Volcengine ARK api key here
```

You can refer to the [config instructions](https://volcengine.github.io/veadk-python/configuration/) for more details.

## Have a try

Enjoy a minimal agent from VeADK:

```python
from veadk import Agent
import asyncio

agent = Agent()

res = asyncio.run(agent.run("hello!"))
print(res)
```

## AgentKit application

Use the shared AgentKit application factory when your project needs AgentKit
APIs, VeADK's bundled Web UI, health checks, and agent-topology endpoints. This
keeps platform routes and lifecycle code out of your agent module:

```python
from veadk import Agent
from veadk.integrations.agentkit import create_agentkit_app

root_agent = Agent(name="customer_support")
app = create_agentkit_app(
    root_agent,
    enable_studio_tools=True,
)
```

Studio-owned dynamic tools and HTTP routes are separate Runtime capabilities.
Enable them explicitly with `enable_studio_tools=True` and
`enable_studio_routes=True`; both default to disabled.

See [`examples/generated_agentkit_project`](examples/generated_agentkit_project)
for a complete generated project.

The Agent Server metadata endpoint reports the root Agent's name, description,
model, sub-Agents, tools, skills, and mounted component summaries. Each Runtime
row in Studio has explicit connect and info actions; the info panel's tabs switch
between this live metadata and control-plane information without exposing prompts
or credentials. The same metadata advertises mounted smart-search sources, so
Studio can disable unavailable sources up front and query the Agent's web-search
tool, KnowledgeBase, or long-term memory without exposing component credentials.
Studio also manages user-owned Codex, OpenClaw, and Hermes AgentKit Sessions.
Users can create, reopen, inspect, and explicitly delete each Agent; leaving a
Codex conversation only disconnects it, while OpenClaw and Hermes expose their
main interface and Terminal through Studio.
When configuring skills, Studio can also browse account-scoped AgentKit Skill
Spaces and their paginated skill lists by region and project. These requests are
signed on the server, so browser clients never receive Volcengine credentials.

The Studio deployment flow lists Feishu, knowledge-base, short-/long-term
memory, and observability settings in their feature sections. Values entered
there are mirrored in the deployment environment-variable summary and converted
to VeADK runtime environment variables only when deploying; secrets are not
written to generated source or exported YAML. For multi-instance runtimes, use
a database-backed short-term memory store so sessions remain available across
instances.

When a cloud image build fails from the bundled Web UI, the deployment error
includes a credential-safe excerpt from the build log so dependency and
Dockerfile failures can be diagnosed directly.

When Studio connects to an AgentKit Runtime, users can rate completed answers
with like/dislike controls. Feedback is written server-side to per-Agent
`{agent_name}_good_case` and `{agent_name}_bad_case` evaluation sets, with
stable item keys so repeated clicks and rating changes remain idempotent.

## Native Codex integration (opt-in)

The Codex runtime supports `CodexRuntimeConfig(integration_mode="native")` with
the pinned official SDK/CLI 0.157.0. Codex owns MCP tool scheduling and the native
thread transcript; VeADK's executors still enforce tool callbacks, authentication
and confirmation. Agent instructions are appended as developer instructions,
preserving Codex's built-in prompt. The existing default remains `"shim"`.

The 0.157.0 app-server deprecates personality-based style selection: `friendly`
and `pragmatic` no longer select a style. Keep application style requirements in
the agent instructions; the compatibility field remains accepted.

```python
from veadk import Agent
from veadk.runtime.codex.config import CodexRuntimeConfig

agent = Agent(
    name="assistant",
    runtime="codex",
    codex_runtime_config=CodexRuntimeConfig(
        integration_mode="native",
        session_root="/persistent/veadk/codex/sessions",
        approval_mode="deny_all",
        sandbox="read_only",
        web_search="disabled",
    ),
)
```

Configure the agent's model and Responses endpoint through the normal VeADK
configuration. For providers accepting only function schemas, select
`responses_tool_format="functions"`; reversible encoding preserves native
namespace/custom tools and client-side tool search. Server-hosted tool search
cannot be represented by that mode and is rejected explicitly.

Each app/user/session/agent/branch maps to a private home and exclusive thread
lease. `VEADK_CODEX_SESSION_ROOT` overrides storage; the default is
`$XDG_STATE_HOME/veadk/codex/sessions` or `~/.local/state/veadk/codex/sessions`.
Containers need a persistent volume to retain threads across replacement, and
multi-instance deployments need shared storage with working file locks or
session affinity. The tool workspace has its own configured lifecycle.

Interrupted execution is not replayed automatically. After reconciling actual
tool effects, an administrator can use
`NativeSession.reconcile(root, ctx, invocation_id=..., effects_reconciled=True)`.
This marks the interruption reconciled and migrates the next turn; it does not
retry tools or edit Codex rollout files. Importing existing ADK history or a
callback rewriting earlier contents also starts a new thread with an explicit
history import. That migration is JSON-based and is not lossless native resume.

The required `codex-native` CI job exercises the real CLI with a local synthetic
Responses provider, including MCP tool results, thread continuity, callbacks,
confirmation/authentication, cancellation, terminal states and tool encoding.
Semantic answer quality still requires a same-model, same-tools comparison.

## Feishu bot channel

VeADK now provides `veadk.extensions.FeishuChannelExtension` for bridging a Feishu bot with a `Runner`. It maps `union_id` to `user_id`, and `thread_id` / `chat_id` to `session_id`, so VeADK memory and tracing can work directly in Feishu conversations.

```python
from veadk import Agent, Runner
from veadk.extensions import FeishuChannelExtension

agent = Agent()
runner = Runner(agent=agent, app_name="feishu_demo")
channel = FeishuChannelExtension(runner=runner)
```

Configure credentials with `TOOL_FEISHU_CHANNEL_APP_ID` and `TOOL_FEISHU_CHANNEL_APP_SECRET`, or in `config.yaml` under `tool.feishu_channel`.

## Contribution

Before making your contribution to our repository, please install and config the `pre-commit` linter first.

```bash
pip install pre-commit
pre-commit install
```

Before commit or push your changes, please make sure the unittests are passed ,otherwise your PR will be rejected by CI/CD workflow. Running the unittests by:

```bash
pytest -n 16
```

## Security and privacy

This project takes security seriously.
For vulnerability reporting and supported versions, see [SECURITY.md](SECURITY.md)

## Contact with us

Join our discussion group by scanning the QR code below:

<p align="center">
    <img src="assets/images/veadk_group_qrcode.jpg" alt="Volcengine Agent Development Kit Logo" width="40%">
</p>

## License

This project is licensed under the [Apache 2.0 License](./LICENSE).

## Offline native gate partition

The Python 3.12 unit-test job sets `VEADK_NATIVE_GATE_PARTITION=1` and excludes `codex_native`. The serial native job still runs every module required by `tests/runtime/codex/verify_native_report.py`; missing modules, failed tests, skipped tests and the missing real CLI HTTP case still fail the gate. Native-required unit tests run once on Python 3.12. Python 3.10 keeps its existing coverage because no native job replaces it there.

For local Python 3.12 validation, use the same partition for the ordinary full suite, then run the native job's explicit modules and its JUnit verifier. Use the pinned candidate environment and a temporary directory outside the repository for CLI write tests. A partitioned unit run alone is not a complete release gate.
