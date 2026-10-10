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

"""Materialize fixed public CLI inputs before running the offline release gate."""

import hashlib
from pathlib import Path
import sys
import urllib.request

from veadk.cli.studio_legacy_bundle import LEGACY_CLI_SHA256


def main(root: Path) -> None:
    for version, expected in LEGACY_CLI_SHA256.items():
        path = root / version / "agentkit-linux-x64.tar.gz"
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        url = f"https://agentkit-cli.tos-cn-beijing.volces.com/{version}/{path.name}"
        with urllib.request.urlopen(url, timeout=120) as response:
            if response.geturl() != url or response.status != 200:
                raise ValueError("Historical CLI download origin mismatch")
            content = response.read(80 * 1024 * 1024 + 1)
        if (
            len(content) > 80 * 1024 * 1024
            or hashlib.sha256(content).hexdigest() != expected
        ):
            raise ValueError("Historical CLI checksum mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
