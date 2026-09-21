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

"""Resolve the separately installed binary AIOps engine.

Installing this SDK does not install the private engine. Customers can develop
veADK tools locally; execution also requires the platform-specific runtime wheel.
"""

from importlib import import_module


def _resolve(module, name):
    try:
        target = import_module(module)
    except ModuleNotFoundError as error:
        if error.name == "agentkit_aiops":
            raise RuntimeError(
                "AIOps execution requires the separately installed binary runtime"
            ) from None
        raise
    return getattr(target, name)


def create_agent(*args, **kwargs):
    return _resolve("agentkit_aiops", "create_agent")(*args, **kwargs)


def create_app(*args, **kwargs):
    return _resolve("agentkit_aiops", "create_app")(*args, **kwargs)


def create_server(*args, **kwargs):
    return _resolve("agentkit_aiops", "create_server")(*args, **kwargs)


__all__ = ["create_agent", "create_app", "create_server"]
