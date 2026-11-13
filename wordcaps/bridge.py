from __future__ import annotations

import base64
import binascii
import itertools
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import paths
from .lua_literal import lua_string, to_lua

PING = "Ping"
GET_TIMELINE_INFO = "GetTimelineInfo"
LIST_TEMPLATES = "ListTemplates"
CREATE_TEMPLATE_CLIP = "CreateTemplateClip"
EXPORT_AUDIO = "ExportAudio"
GET_EXPORT_STATUS = "GetExportStatus"
PLACE_CAPTIONS = "PlaceCaptions"

ERROR_KEY = "error"
ACK_KEY = "WordCapsAck"
RESPONSE_KEY = "WordCapsResponse"
PROGRESS_KEY = "WordCapsProgress"
_MARKER_BASE = 0xE000
_POLL_SECONDS = 0.1


class BridgeError(Exception):
    pass


class BridgeOffline(BridgeError):
    pass


def pref_value(text: str, key: str) -> str | None:
    matches = re.findall(rf'(?<![A-Za-z0-9_]){re.escape(key)} = "([^"]*)"', text)
    return matches[-1] if matches else None


def _restore_string(value: str) -> str:
    if not any(_MARKER_BASE <= ord(ch) <= _MARKER_BASE + 0xFF for ch in value):
        return value
    raw = bytearray()
    for ch in value:
        code = ord(ch)
        if _MARKER_BASE <= code <= _MARKER_BASE + 0xFF:
            raw.append(code - _MARKER_BASE)
        else:
            raw.extend(ch.encode("utf-8"))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("mbcs" if paths.is_windows() else "latin-1", errors="replace")


def _restore(value: Any) -> Any:
    if isinstance(value, str):
        return _restore_string(value)
    if isinstance(value, list):
        return [_restore(item) for item in value]
    if isinstance(value, dict):
        return {_restore_string(key): _restore(item) for key, item in value.items()}
    return value


def decode_response(value: str, request_id: str) -> dict | None:
    response_id, _, encoded = value.partition(":")
    if response_id != request_id or not encoded:
        return None
    try:
        body = json.loads(base64.b64decode(encoded, validate=True).decode("ascii"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return _restore(body)


def encode_request(request_id: str, func: str, args: dict) -> str:
    return f"return {{ id = {lua_string(request_id)}, func = {lua_string(func)}, args = {to_lua(args)} }}\n"


class ResolveBridge:
    def __init__(
        self,
        mailbox: Path | None = None,
        prefs_locator: Callable[[], Path | None] = paths.fusion_prefs_path,
    ) -> None:
        self._mailbox = mailbox or paths.mailbox_dir()
        self._prefs_locator = prefs_locator
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    @property
    def request_path(self) -> Path:
        return self._mailbox / "request.lua"

    def call(
        self,
        func: str,
        args: dict | None = None,
        timeout: float = 30.0,
        ack_timeout: float = 4.0,
        on_progress: Callable[[str], None] | None = None,
    ) -> Any:
        with self._lock:
            self._mailbox.mkdir(parents=True, exist_ok=True)
            self._delete_request()
            request_id = f"{int(time.time() * 1000)}-{next(self._counter)}"
            temporary = self._mailbox / "request.lua.tmp"
            temporary.write_text(encode_request(request_id, func, args or {}), encoding="ascii")
            os.replace(temporary, self.request_path)
            try:
                body = self._wait_for_response(func, request_id, timeout, ack_timeout, on_progress)
            finally:
                self._delete_request()
        if ERROR_KEY in body:
            raise BridgeError(body[ERROR_KEY])
        return body.get("result")

    def _wait_for_response(
        self,
        func: str,
        request_id: str,
        timeout: float,
        ack_timeout: float,
        on_progress: Callable[[str], None] | None,
    ) -> dict:
        started = time.monotonic()
        acknowledged = False
        last_progress = None
        while True:
            text = self._read_prefs()
            if text:
                response = pref_value(text, RESPONSE_KEY)
                if response:
                    body = decode_response(response, request_id)
                    if body is not None:
                        return body
                acknowledged = acknowledged or pref_value(text, ACK_KEY) == request_id
                progress = pref_value(text, PROGRESS_KEY)
                if on_progress and progress and progress.startswith(request_id + ":") and progress != last_progress:
                    last_progress = progress
                    on_progress(progress.split(":", 1)[1])
            elapsed = time.monotonic() - started
            if not acknowledged and elapsed > ack_timeout:
                raise BridgeOffline(
                    "DaVinci Resolve no responde. Abre Resolve y lanza Workspace > Scripts > WordCaps."
                )
            if elapsed > timeout:
                raise BridgeError(f"Resolve no terminó '{func}' en {timeout:.0f} s.")
            time.sleep(_POLL_SECONDS)

    def _read_prefs(self) -> str | None:
        prefs = self._prefs_locator()
        if prefs is None:
            return None
        try:
            return prefs.read_text(encoding="latin-1")
        except OSError:
            return None

    def _delete_request(self) -> None:
        for _ in range(5):
            try:
                self.request_path.unlink()
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.05)
