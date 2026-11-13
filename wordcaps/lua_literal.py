from __future__ import annotations

import math
from typing import Any

_PLAIN_BYTES = frozenset(range(0x20, 0x7F)) - {ord('"'), ord("\\")}


def lua_string(text: str) -> str:
    parts = []
    for byte in text.encode("utf-8"):
        if byte in _PLAIN_BYTES:
            parts.append(chr(byte))
        else:
            parts.append(f"\\{byte:03d}")
    return '"' + "".join(parts) + '"'


def to_lua(value: Any) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Cannot encode non-finite number {value!r} as Lua")
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(to_lua(item) for item in value) + "}"
    if isinstance(value, dict):
        fields = (f"[{lua_string(str(key))}]={to_lua(item)}" for key, item in value.items())
        return "{" + ",".join(fields) + "}"
    raise TypeError(f"Cannot encode {type(value).__name__} as Lua")
