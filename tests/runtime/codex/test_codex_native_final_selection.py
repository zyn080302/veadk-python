"""Control one integration mechanism at a time using the real pinned CLI."""

import asyncio
import os
from pathlib import Path

import pytest
from native_parity_support import run_stack, save_result


@pytest.mark.parametrize(
    "scenario",
    [
        "unphased_pair",
        "commentary_then_final",
        "two_finals",
        "explicit_then_unphased",
        "tool_then_progress",
        "explicit_before_tool",
    ],
)
@pytest.mark.codex_native
def test_final_selection_matches_official_sdk(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv("PARITY_CAUSE_OUTPUT", str(tmp_path))

    async def run():
        direct = await run_stack(tmp_path / "direct", "direct", scenario)
        native = await run_stack(tmp_path / "native", "veadk", scenario)
        path = Path(os.environ["PARITY_CAUSE_OUTPUT"]) / f"final-{scenario}.json"
        save_result(
            path,
            {
                "direct": direct,
                "veadk": native,
                "equal": direct["final"] == native["final"],
            },
        )
        assert (
            direct["final"] == native["final"]
        ), "veadk final differs from official SDK"

    asyncio.run(asyncio.wait_for(run(), 80))
