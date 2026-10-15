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

"""Run the fixed AI OPS template on the Harness App port."""

import asyncio
import sys

import uvicorn

from veadk.aiops.harness.host import prepare_server


async def serve():
    server = await prepare_server()
    await uvicorn.Server(
        uvicorn.Config(server, host="0.0.0.0", port=8000, access_log=False)
    ).serve()


def main():
    try:
        asyncio.run(serve())
    except Exception:
        sys.exit("AI OPS Harness configuration could not be prepared")


if __name__ == "__main__":
    main()
