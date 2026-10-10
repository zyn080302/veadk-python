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

"""Bounded BSDIFF40 reconstruction; execution still requires the target CLI pin."""

from __future__ import annotations

import bz2

MAX_CLI_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_CLI_TAR_BYTES = 300 * 1024 * 1024
_MAX_CONTROL_BYTES = 4 * 1024 * 1024
_ERROR = "Studio CLI delta is invalid."


def _integer(value: bytes) -> int:
    if len(value) != 8:
        raise ValueError(_ERROR)
    number = int.from_bytes(value, "little")
    magnitude = number & ((1 << 63) - 1)
    return -magnitude if number & (1 << 63) else magnitude


def _decompress(value: bytes, limit: int) -> bytes:
    decoder = bz2.BZ2Decompressor()
    try:
        result = decoder.decompress(value, max_length=limit + 1)
    except (OSError, EOFError) as error:
        raise ValueError(_ERROR) from error
    if len(result) > limit or not decoder.eof or decoder.unused_data:
        raise ValueError(_ERROR)
    return result


def restore_cli_archive(
    original: bytes,
    delta: bytes,
    *,
    target_size: int,
    max_bytes: int = MAX_CLI_ARCHIVE_BYTES,
) -> bytes:
    """Restore bytes with fixed memory/output bounds and no external commands.

    Callers must authenticate original, delta, and restored output. This parser
    only implements the data format; it does not confer authenticity on a patch.
    """
    if (
        not 0 < max_bytes <= MAX_CLI_TAR_BYTES
        or not 0 < len(original) <= max_bytes
        or not 32 < len(delta) <= MAX_CLI_ARCHIVE_BYTES
        or not 0 < target_size <= max_bytes
        or delta[:8] != b"BSDIFF40"
    ):
        raise ValueError(_ERROR)
    control_size = _integer(delta[8:16])
    difference_size = _integer(delta[16:24])
    if (
        control_size <= 0
        or difference_size <= 0
        or _integer(delta[24:32]) != target_size
        or 32 + control_size + difference_size >= len(delta)
    ):
        raise ValueError(_ERROR)
    middle = 32 + control_size
    end = middle + difference_size
    controls = _decompress(delta[32:middle], _MAX_CONTROL_BYTES)
    differences = _decompress(delta[middle:end], target_size)
    extra = _decompress(delta[end:], target_size)
    if not controls or len(controls) % 24:
        raise ValueError(_ERROR)

    output = bytearray()
    old_position = diff_position = extra_position = 0
    for offset in range(0, len(controls), 24):
        add, insert, seek = (
            _integer(controls[offset + n : offset + n + 8]) for n in (0, 8, 16)
        )
        if (
            add < 0
            or insert < 0
            or len(output) + add + insert > target_size
            or diff_position + add > len(differences)
            or extra_position + insert > len(extra)
        ):
            raise ValueError(_ERROR)
        for block in range(0, add, 1024 * 1024):
            count = min(1024 * 1024, add - block)
            start = old_position + block
            changes = differences[diff_position + block : diff_position + block + count]
            if 0 <= start <= len(original) - count:
                source = original[start : start + count]
                output.extend(
                    source
                    if changes.count(0) == count
                    else bytes((a + b) & 255 for a, b in zip(source, changes))
                )
            else:
                output.extend(
                    (
                        change
                        + (original[start + i] if 0 <= start + i < len(original) else 0)
                    )
                    & 255
                    for i, change in enumerate(changes)
                )
        diff_position += add
        output.extend(extra[extra_position : extra_position + insert])
        extra_position += insert
        old_position += add + seek
        if abs(old_position) > 2 * max_bytes:
            raise ValueError(_ERROR)
    if (
        len(output) != target_size
        or diff_position != len(differences)
        or extra_position != len(extra)
    ):
        raise ValueError(_ERROR)
    return bytes(output)
