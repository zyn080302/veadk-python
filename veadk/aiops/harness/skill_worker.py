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

"""Internal fixed worker; credentials only arrive on stdin, never argv/logs."""

import contextlib
import json
import logging
import os
import sys
from pathlib import Path


def materialize(item, root):
    environment = item["environment"]
    os.environ.update(environment)
    if environment.get("CLOUD_PROVIDER") == "byteplus":
        for suffix in ("ACCESS_KEY", "SECRET_KEY", "SESSION_TOKEN"):
            os.environ["BYTEPLUS_" + suffix] = environment.get(
                "VOLCENGINE_" + suffix, ""
            )
    from veadk.skills.materializer import materialize_remote_skill, skill_version_key
    from veadk.skills.utils import load_skills_from_cloud

    matches = [
        skill
        for skill in load_skills_from_cloud(item["space_id"])
        if skill.id == item["skill_id"]
    ]
    if len(matches) != 1 or str(skill_version_key(matches[0])) != item["version"]:
        raise ValueError("Selected Skill version is unavailable")
    return materialize_remote_skill(matches[0], cache_dir=root)


def main():
    logging.disable(logging.CRITICAL)
    try:
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            from loguru import logger

            logger.remove()
            item = json.loads(sys.stdin.buffer.read(128 * 1024))
            directory = materialize(item, Path(sys.argv[1]).resolve())
        result = {"directory": str(directory)}
    except Exception:
        result = {"error": "Selected Skill could not be prepared"}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
