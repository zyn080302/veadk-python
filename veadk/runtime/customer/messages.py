"""Bound original user Content independently of tool and output event budgets."""

from __future__ import annotations

import base64
import binascii
import json
import math

from .protocol import CustomerChannelError

_MIB = 1024 * 1024
NATIVE_INITIAL_REQUEST_BYTES = 8 * _MIB


def _fields(value, allowed, aliases=None):
    if not isinstance(value, dict):
        raise ValueError
    result = {}
    for key, item in value.items():
        name = (aliases or {}).get(key, key)
        if name not in allowed or name in result:
            raise ValueError
        result[name] = item
    return result


def _json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


def _metadata(value, budget, depth=0):
    # Limit traversal before serialization/copy, including huge shallow arrays.
    budget[0] += 1
    if depth > 8 or budget[0] > 256:
        raise ValueError
    if isinstance(value, dict):
        if any(not isinstance(k, str) or len(k) > 16 * 1024 for k in value):
            raise ValueError
        return {k: _metadata(v, budget, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_metadata(v, budget, depth + 1) for v in value]
    if value is None or type(value) in (str, bool, int):
        if isinstance(value, str) and len(value) > 16 * 1024:
            raise ValueError
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError


def _blob(value):
    blob = _fields(
        value,
        {"mime_type", "data", "display_name"},
        {"mimeType": "mime_type", "displayName": "display_name"},
    )
    mime, encoded = blob.get("mime_type"), blob.get("data")
    if not isinstance(mime, str) or mime not in {
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/pdf",
    }:
        raise ValueError
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 4 * (
        (4 * _MIB + 2) // 3
    ):
        raise ValueError
    data = base64.b64decode(encoded, altchars=b"-_", validate=True)
    standard = base64.b64encode(data).decode()
    if not 0 < len(data) <= 4 * _MIB or encoded not in {
        standard,
        base64.urlsafe_b64encode(data).decode(),
    }:
        raise ValueError
    blob["data"] = standard
    valid = (
        data.startswith(b"%PDF-")
        if mime == "application/pdf"
        else data.startswith(b"\x89PNG\r\n\x1a\n")
        if mime == "image/png"
        else data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
        if mime == "image/jpeg"
        else data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError
    if "display_name" in blob:
        name = blob["display_name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 180:
            raise ValueError
        name.encode("utf-8")
    return blob, len(data)


def validate_user_message(message, *, attachments=False):
    """Return a detached normalized snapshot, or a fixed payload-free error."""
    try:
        content = _fields(message, {"role", "parts"})
        parts = content.get("parts")
        if content.get("role") != "user" or not isinstance(parts, list) or not parts:
            raise ValueError
        if attachments and len(parts) > 8:
            raise ValueError
        result = []
        text_bytes = blob_bytes = blob_count = metadata_bytes = 0
        nodes = [0]
        nonempty = False
        for raw in parts:
            part = _fields(
                raw,
                {"text", "inline_data", "part_metadata"} if attachments else {"text"},
                {"inlineData": "inline_data", "partMetadata": "part_metadata"}
                if attachments
                else None,
            )
            if ("text" in part) == ("inline_data" in part):
                raise ValueError
            if "text" in part:
                value = part["text"]
                if not isinstance(value, str) or len(value) > _MIB:
                    raise ValueError
                text_bytes += len(value.encode("utf-8"))
                nonempty |= bool(value.strip())
            else:
                part["inline_data"], size = _blob(part["inline_data"])
                blob_bytes += size
                blob_count += 1
                nonempty = True
            if "part_metadata" in part:
                metadata = part["part_metadata"]
                if not isinstance(metadata, dict):
                    raise ValueError
                metadata = _metadata(metadata, nodes)
                metadata_bytes += _json_bytes(metadata)
                if metadata_bytes > 16 * 1024:
                    raise ValueError
                part["part_metadata"] = metadata
            if text_bytes > _MIB or blob_count > 3 or blob_bytes > 5 * _MIB:
                raise ValueError
            result.append(part)
        normalized = {"role": "user", "parts": result}
        if not nonempty or _json_bytes(normalized) > (
            7 * _MIB if attachments else _MIB
        ):
            raise ValueError
        return normalized
    except (ValueError, TypeError, RecursionError, OverflowError, binascii.Error):
        raise CustomerChannelError("unsupported_user_message") from None
