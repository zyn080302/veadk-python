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

The last two verify the real SDK types; the separate native CI job also drives
the real app-server. These protocol tests are easy to skip locally. `openai-codex`
is an optional extra; CI installs it (`uv sync --all-extras` in
`.github/workflows/unit-tests.yaml`), a checkout usually does not. A green local
run therefore does **not** mean the SDK contract holds.

To run them locally:

```bash
uv sync --extra codex --group dev  # pinned SDK/CLI 0.157.0
PYTHONPYCACHEPREFIX=/private/tmp/veadk-pycache \
  uv run --no-sync python -m pytest tests/runtime/codex/test_codex_sdk_protocol.py -v
```

Confirm they are not skipping:

```bash
uv run --no-sync python -m pytest tests/runtime/codex -q -rs   # -rs lists skip reasons
```

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

## I/O boundaries

Most unit and differential tests use an in-process HTTP transport. The live
stream tests also bind loopback sockets to verify delivery timing and disconnect
cleanup. The opt-in Codex smoke tests launch the real CLI against a synthetic
loopback backend. None of these tests require an external model or business MCP.
`test_codex_runtime.py::test_tool_executor_supports_stdio_mcp_toolset` starts a
bounded local Python subprocess from `examples/`.

The real SDK contract tests also cover typed message phases and tool boundaries:
commentary is partial, tool preambles cannot enter the final model callback, and
call/result IDs remain paired. Plain dict fixtures cannot substitute for the
SDK's generated enum and notification types.

`test_codex_shim_rounds.py` constructs `ResponsesShim` directly rather than
calling `get_shim`, so the process-global `_SHIMS` cache (and its uvicorn
servers) is never populated; an autouse fixture asserts that. The one test that
must exercise `get_shim` — the cache is what it tests — swaps `_SHIMS`/`_RETIRED`
for empty ones, restores them in a `finally` before that fixture runs, and stubs
`start()` so nothing binds a port.
