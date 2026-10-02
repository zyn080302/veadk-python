"""Portable Studio configuration contract; no private Runtime dependency or I/O."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any


def normalize_global_context(value: Any) -> dict[str, Any] | None:
    """Copy and validate public scalar settings without echoing untrusted values.

    Capacities are explicit caller budgets, not assertions about a model family.
    Thinking and credentials are deliberately not configurable through this object.
    """
    if value is None:
        return None
    error = "Invalid Studio global context configuration"
    if not isinstance(value, Mapping):
        raise ValueError(error)
    integers = {
        "context_window": (1, None),
        "input_limit": (1, None),
        "output_reserve": (1, None),
        "summary_context_window": (1, None),
        "summary_input_limit": (1, None),
        "media_token_reserve": (1, None),
        "safety_margin": (0, None),
        "keep_recent_turns": (1, None),
        "summary_max_tokens": (128, 8192),
        "max_summary_calls": (1, 4),
    }
    numbers = {
        "target_ratio": 1,
        "trigger_ratio": 1,
        "summary_trigger_ratio": 1,
        "summary_timeout_seconds": 60,
        "summary_time_budget_seconds": 90,
    }
    if set(value) - (set(integers) | set(numbers) | {"mode", "summary_model"}):
        raise ValueError(error)
    for name, (minimum, maximum) in integers.items():
        if name in value:
            item = value[name]
            if (
                type(item) is not int
                or item < minimum
                or (maximum is not None and item > maximum)
            ):
                raise ValueError(error)
    for name, maximum in numbers.items():
        if name in value:
            item = value[name]
            if (
                type(item) not in (float, int)
                or not 0 < item <= maximum
                or not math.isfinite(item)
            ):
                raise ValueError(error)
    if value.get("mode", "auto") != "auto":
        raise ValueError(error)
    if "summary_model" in value:
        model = value["summary_model"]
        if not isinstance(model, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", model
        ):
            raise ValueError(error)
    if not (
        0
        < value.get("target_ratio", 0.6)
        < value.get("trigger_ratio", 0.8)
        <= value.get("summary_trigger_ratio", 0.95)
        <= 1
    ):
        raise ValueError(error)
    # An explicit capacity must leave room for output and framing. The input
    # limit may be larger than this remainder: Runtime takes the smaller bound.
    for window, output, default_output in (
        ("context_window", "output_reserve", None),
        ("summary_context_window", "summary_max_tokens", 2048),
    ):
        reserve = value.get(output, default_output)
        if (
            window in value
            and reserve is not None
            and value[window] <= reserve + value.get("safety_margin", 1024)
        ):
            raise ValueError(error)
    return dict(value)
