# Codex runtime tests

## What runs where

| File | Needs `openai-codex`? | Runs locally by default |
| --- | --- | --- |
| `test_codex_runtime.py` | no | yes |
| `test_codex_shim_rounds.py` | no | yes |
| `test_codex_tracing.py` | no (a stub SDK is installed) | yes |
| `../differential/` | no (a stub SDK is installed) | yes |
| `test_codex_runtime_sdk.py` | **yes** (`pytest.importorskip`) | **no — silently skipped** |
| `test_codex_sdk_protocol.py` | **yes** (`pytest.importorskip`) | **no — silently skipped** |
| `test_codex_runtime_smoke.py` | yes | no — opt in with `CODEX_RUN_SMOKE=1` |
| `test_codex_real_model_probe.py` | yes | no — opt in with `CODEX_RUN_PROBE=1`, spends real tokens |

The last two are the only tests that touch the real SDK types, and they are the
ones a developer machine is most likely to skip without noticing. `openai-codex`
is an optional extra; CI installs it (`uv sync --all-extras` in
`.github/workflows/unit-tests.yaml`), a checkout usually does not. A green local
run therefore does **not** mean the SDK contract holds.

To run them locally:

```bash
uv sync --all-extras     # official SDK and bundled CLI: 0.163.0
PYTHONPYCACHEPREFIX=/private/tmp/veadk-pycache \
  .venv/bin/python -m pytest tests/runtime/codex/test_codex_sdk_protocol.py -v
```

Confirm they are not skipping:

```bash
.venv/bin/python -m pytest tests/runtime/codex -q -rs   # -rs lists skip reasons
```

## Select the CLI used by native tests

The current native target is Codex CLI **0.164.0**, selected separately from
Python SDK 0.163.0 and its required packaged CLI 0.163.0. From the repository
root, install and select the official executable before running serial tests:

```bash
npm install --prefix .codex0164 --no-save @openai/codex@0.164.0
export VEADK_CODEX_BIN="$(pwd)/.codex0164/node_modules/.bin/codex"
"$VEADK_CODEX_BIN" --version
CODEX_RUN_SMOKE=1 uv run --extra dev --extra codex pytest \
  tests/runtime/codex -m codex_smoke -p no:xdist -rs
```

Without `VEADK_CODEX_BIN`, the official SDK chooses its bundled executable;
that does not verify 0.164.0. The mandatory final-selection, terminal-status and cleanup regressions run via `python scripts/check_codex_terminal_integrity.py`; the wheel builder and CI use the same entry point.
The gate also exercises a trusted CLI path change through the real runtime:
an idle process created for the previous path must close, while the stored
thread resumes under the newly selected binary. All 25 required cases must
execute without skips.

This integration preserves mainline's process reuse, isolation and crash
recovery. It adds the public, programmatic `provider_factory` extension and
`shell_enabled` control, retains final-answer phase metadata, rejects
failed/interrupted/missing terminal status as success, and waits for executor
cleanup before releasing provider resources. A pooled cleanup timeout makes
the process ineligible for reuse; closing it still waits for pending cleanup.
Existing downstream imports such as `native_bridge` are not supplied by this
SDK; those applications must migrate their provider and final-response
contracts before replacing a wheel.

CLI 0.164.0 may emit native permission/environment developer messages in
addition to the application instruction. The workload tests check that the
application instruction occurs exactly once in **every model request**, and
that warm reuse does not grow developer history. They retain the result,
request-count, concurrency and shutdown assertions. A fixed total of one
developer message is not the compatibility contract.

这些回归保留主线的进程复用、隔离和崩溃恢复，并检查终稿阶段、失败终态和工具清理。
切换可信 CLI 路径必须关闭旧空闲进程；进程池清理超时不得提前释放 Provider。
CLI 0.164.0 的原生权限说明可能形成独立 developer 消息，回归检查每次模型请求中的
应用指令恰好出现一次，以及 warm 路径上下文不累积。旧 `native_bridge` 消费方仍需
迁移应用 Provider 和终稿合同；本地模拟模型测试不代表真实业务模型质量或云端验收。
When testing an installed wheel in a separate directory, also copy
`examples/piagent_with_mcp/mcp_order_server.py` at the same relative location:
the stdio MCP test actually starts this fixture as a subprocess.

## Connect to local test databases with Colima

On macOS, Docker commands can fail with `Cannot connect to the Docker daemon`
at `unix:///var/run/docker.sock` even when Colima is running. If you use Colima
to host the MySQL and PostgreSQL test databases, check its status and select
its Docker context explicitly from any directory:

```bash
colima list
docker context ls
docker --context colima info --format '{{.OSType}}'
```

For Colima's default profile, expect `Running` in `colima list`, a `colima`
context in `docker context ls`, and `linux` from the final command. Use
`docker --context colima` for subsequent container commands so they reach the
same daemon without changing the default context for other projects. For a
named Colima profile, use its context name from `docker context ls` instead

Set `VEADK_TEST_MYSQL_URL` and `VEADK_TEST_POSTGRES_URL` to the databases'
published host ports before running the tests. Selecting a Docker context
does not set these URLs; without them, the corresponding database cases skip

## Why the differential suite still runs without the SDK

`veadk/runtime/codex/runtime.py` imports `openai_codex` at module scope, so
`Agent(runtime="codex")` is unimportable without the extra. The differential
harness installs a minimal stub into `sys.modules`
(`tests/runtime/differential/fake_codex_sdk.py::install_openai_codex_stub`) from
a *fixture*, never at import time — pytest finishes collection, and therefore
evaluates every `importorskip("openai_codex")`, before the first test runs, so
the stub cannot turn a legitimate skip into a spurious pass.

The stub only replaces the names the runtime imports. `AsyncCodex` is always
replaced by `ShimDrivingCodex`, which POSTs a real `stream: True`
`/v1/responses` request at the real `ResponsesShim` over `httpx.ASGITransport`
(in-process, no socket, no Codex binary, xdist-safe) and reads its endpoint out
of the `config.toml` that `_prepare_codex_home` generated.

For the direct mode (Codex calls the provider itself and reaches ADK tools
through VeADK's MCP bridge) the replacement is `DirectDrivingCodex` instead:
it reads `model_providers` / `mcp_servers` from `thread_start(config=...)` and
credentials from `CodexConfig.env`, calls the model through the (patched)
`litellm.aresponses` with no shim in between, and speaks real streamable-HTTP
MCP to each configured server. Select it with
`monkeypatch.setattr(runtime_module, "AsyncCodex", DirectDrivingCodex)` (or a
`DirectDrivingCodex.configured(...)` subclass).

## No network, no ports, no binary

Apart from the two opt-in files above (`test_codex_runtime_smoke.py`,
`test_codex_real_model_probe.py`), nothing in this directory or in
`../differential/` binds a port, spawns the Codex CLI, or reaches the network —
with two exceptions:
`test_codex_runtime.py::test_tool_executor_supports_stdio_mcp_toolset` spawns a
real Python subprocess from `examples/`, and
`../differential/test_fake_direct_codex.py` binds a FastMCP server to
`127.0.0.1:0` (loopback, ephemeral port, so still xdist-safe). Both are bounded
by explicit timeouts so they cannot hang a `pytest -n 16` run.

`test_codex_shim_rounds.py` constructs `ResponsesShim` directly rather than
calling `get_shim`, so the process-global `_SHIMS` cache (and its uvicorn
servers) is never populated; an autouse fixture asserts that. The one test that
must exercise `get_shim` — the cache is what it tests — swaps `_SHIMS`/`_RETIRED`
for empty ones, restores them in a `finally` before that fixture runs, and stubs
`start()` so nothing binds a port.

## Real-model probe (`test_codex_real_model_probe.py`)

A tiny, fixed canary against a **real model**, to run **once per Codex PR
before merge** instead of a large example (`examples/codex_ops_assistant`
spends ~2M tokens a run). It is marked `codex_probe` and skipped unless opted
in; it **must not run in CI** — it spends real tokens and depends on model
behaviour.

Scenario: two turns in one session, `RunConfig(max_llm_calls=15)`. Turn 1 calls
the ADK tool `fetch_latency_samples` (a six-row CSV), then three shell steps —
save `latency.csv`, average p99, max p99. Turn 2 computes the min from the same
file.

What it catches (each one a regression we have hit):

| Failure | How it shows up |
| --- | --- |
| Ark rejects a forwarded request field (e.g. `reasoning.summary`) | a turn errors instead of completing |
| replayed tool history out of order (ADK results at the tail) | `LlmCallsLimitExceededError`, or a command issued more than twice |
| model copies Codex's shell wrapper (`/bin/zsh -lc '/bin/zsh -lc ...'`) | a recorded command still starts with `<path>/sh\|bash\|zsh -c\|-lc` |
| ADK tool executed more than once | fetch counter is not exactly 1 |
| multi-turn context lost | turn 2 does not report min 120 |
| cost regression | summed token usage over `CODEX_PROBE_MAX_TOKENS` |

Answers must contain average 322.83 (or 322.8), max 980 and min 120.

Cost: ~75K tokens total (one run with `deepseek-v4-flash` used ~52K + ~23K,
about 40 s of model time). Token usage is read from the `usage_metadata` the
runtime attaches once per invocation (the Codex thread's cumulative total,
which already includes the shim's ADK-tool rounds). The cap defaults to
150000; override with `CODEX_PROBE_MAX_TOKENS`.

Run it (sequentially, never under `pytest -n`):

```bash
export CODEX_RUN_PROBE=1
export MODEL_AGENT_API_KEY=...       # Ark API key
export MODEL_AGENT_API_BASE=https://ark.cn-beijing.volces.com/api/v3
export MODEL_AGENT_NAME=...          # model/endpoint id
PYTHONPYCACHEPREFIX=/private/tmp/veadk-pycache \
  .venv/bin/python -m pytest tests/runtime/codex/test_codex_real_model_probe.py \
  -p no:xdist -s -rs
```

`-s` prints each turn's commands, final answer and token count, which is the
first thing to read when it fails. Without the env vars (or without the
`openai-codex` extra) it is skipped with a message naming what to set.
