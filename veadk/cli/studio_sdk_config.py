# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Keep Studio's per-deployment SDK configuration out of build artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Iterator


_config_lock = RLock()


def sdk_build_config(config: dict[str, Any]) -> dict[str, Any]:
    """Write only build identity; the SDK receives the full config in memory.

    An environment key need not contain 'secret' to hold a credential. Do not
    serialize any Runtime environment, authentication or SDK-generated values.
    """
    common = config.get("common", {})
    return {
        "common": {
            key: deepcopy(common[key])
            for key in ("agent_name", "entry_point", "python_version", "launch_type")
            if key in common
        },
        "launch_types": {},
    }


@contextmanager
def sdk_memory_config(
    config_path: Path, config: dict[str, Any] | None
) -> Iterator[None]:
    """Retain real SDK save callbacks in memory for this exact build only.

    AgentKit reloads configuration between build and deploy. Merely suppressing
    writes loses the built image; copy callbacks into the same input dictionary
    so the next executor receives them. Other SDK callers keep their normal
    persistence behavior. Studio already serializes deployments; this lock also
    protects nested callers and restoration on exceptions.
    """
    if config is None:
        yield
        return

    from agentkit.toolkit.config import AgentkitConfigManager

    target = config_path.resolve()
    with _config_lock:
        original_save = AgentkitConfigManager._save_config

        def save(manager: Any) -> None:
            if Path(manager.config_path).resolve() != target:
                original_save(manager)
                return
            updated = deepcopy(manager._data)
            config.clear()
            config.update(updated)

        AgentkitConfigManager._save_config = save
        try:
            yield
        finally:
            AgentkitConfigManager._save_config = original_save
