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

"""Malformed transport data must fail before CLI installation or execution."""

import bz2

import pytest

from veadk.cli.studio_cli_delta import MAX_CLI_ARCHIVE_BYTES, restore_cli_archive


def _number(value):
    return (abs(value) | ((1 << 63) if value < 0 else 0)).to_bytes(8, "little")


def _patch(controls, differences, extra, size):
    control = bz2.compress(b"".join(_number(v) for row in controls for v in row))
    diff = bz2.compress(differences)
    return (
        b"BSDIFF40"
        + _number(len(control))
        + _number(len(diff))
        + _number(size)
        + control
        + diff
        + bz2.compress(extra)
    )


def test_copy_modular_addition_insert_and_backward_seek():
    delta = _patch([(3, 1, -3), (3, 0, 0)], b"\0\0\1\0\0\0", b"!", 7)
    assert restore_cli_archive(b"ab\xff", delta, target_size=7) == b"ab\0!ab\xff"


def test_out_of_range_source_bytes_are_zero():
    delta = _patch([(0, 1, -2), (4, 0, 0)], b"12\0\0", b"!", 5)
    assert restore_cli_archive(b"ab", delta, target_size=5) == b"!12ab"


@pytest.mark.parametrize(
    "field", ["header", "size", "negative", "overrun", "trailing", "truncated"]
)
def test_reject_malformed_delta(field):
    patch = _patch([(3, 0, 0)], b"\0" * 3, b"", 3)
    if field == "header":
        patch = b"INVALID!" + patch[8:]
    elif field == "size":
        patch = patch[:24] + _number(MAX_CLI_ARCHIVE_BYTES + 1) + patch[32:]
    elif field == "negative":
        patch = _patch([(-1, 0, 0)], b"", b"", 3)
    elif field == "overrun":
        patch = _patch([(4, 0, 0)], b"\0" * 4, b"", 3)
    elif field == "trailing":
        patch += bz2.compress(b"hidden")
    else:
        patch = patch[:-1]
    with pytest.raises(ValueError, match="delta"):
        restore_cli_archive(b"abc", patch, target_size=3)


def test_reject_compressed_output_bomb():
    patch = _patch([(3, 0, 0)], b"\0" * 1_000_000, b"", 3)
    with pytest.raises(ValueError, match="delta"):
        restore_cli_archive(b"abc", patch, target_size=3)
