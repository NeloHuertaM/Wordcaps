from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wordcaps.bridge import BridgeError, BridgeOffline, ResolveBridge, decode_response, encode_request, pref_value


def lua_response(request_id: str, body: dict) -> str:
    text = json.dumps(body, ensure_ascii=False)
    marked = "".join(
        "".join(f"\\u{0xE000 + b:04x}" for b in ch.encode("utf-8")) if ord(ch) > 127 else ch for ch in text
    )
    return request_id + ":" + base64.b64encode(marked.encode("ascii")).decode("ascii")


class FakeResolve:
    def __init__(self, directory: Path, reply, progress: str | None = None) -> None:
        self.mailbox = directory / "bridge"
        self.prefs = directory / "Fusion.prefs"
        self.reply = reply
        self.progress = progress
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()

    def _loop(self):
        handled = None
        while not self.stop.is_set():
            request = self.mailbox / "request.lua"
            try:
                text = request.read_text(encoding="ascii")
            except OSError:
                text = ""
            match = re.search(r'id = "([^"]+)", func = "([^"]+)"', text)
            if match and match.group(1) != handled:
                handled = match.group(1)
                if self.progress:
                    self.prefs.write_text(
                        f'WordCapsAck = "{handled}",\nWordCapsProgress = "{handled}:{self.progress}",\n',
                        encoding="latin-1",
                    )
                    time.sleep(0.4)
                self.prefs.write_text(self._prefs_text(handled, self.reply(match.group(2))), encoding="latin-1")
            time.sleep(0.02)

    @staticmethod
    def _prefs_text(request_id: str, body: dict | None) -> str:
        response = f'\t\t\tWordCapsResponse = "{lua_response(request_id, body)}",\n' if body is not None else ""
        return (
            "{\n\tGlobal = {\n\t\tWordCaps = {\n"
            f'\t\t\tWordCapsAck = "{request_id}",\n'
            f"{response}"
            "\t\t},\n\t},\n}\n"
        )


class PrefsParsingTests(unittest.TestCase):
    def test_given_similar_keys_when_reading_a_pref_then_only_the_exact_key_matches(self):
        text = 'XWordCapsAck = "wrong",\n WordCapsAck = "right",'

        self.assertEqual(pref_value(text, "WordCapsAck"), "right")

    def test_given_marked_bytes_when_decoding_then_utf8_text_is_restored(self):
        value = lua_response("7-1", {"result": {"name": "Canción"}})

        self.assertEqual(decode_response(value, "7-1"), {"result": {"name": "Canción"}})

    def test_given_a_response_for_another_request_when_decoding_then_it_is_ignored(self):
        self.assertIsNone(decode_response(lua_response("7-1", {"result": 1}), "7-2"))

    def test_given_a_half_written_value_when_decoding_then_it_is_ignored(self):
        self.assertIsNone(decode_response("7-1:eyJyZXN1", "7-1"))

    def test_given_a_request_when_encoding_then_it_is_a_lua_chunk_returning_a_table(self):
        chunk = encode_request("1-1", "Ping", {"x": "ñ"})

        self.assertEqual(chunk, 'return { id = "1-1", func = "Ping", args = {["x"]="\\195\\177"} }\n')


class ResolveBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="wordcaps-test-"))
        self.addCleanup(shutil.rmtree, self.directory, True)

    def bridge(self) -> ResolveBridge:
        return ResolveBridge(self.directory / "bridge", lambda: self.directory / "Fusion.prefs")

    def test_given_a_running_bridge_when_calling_then_the_result_comes_back_and_the_request_is_removed(self):
        with FakeResolve(self.directory, lambda func: {"result": {"func": func, "name": "Año"}}):
            result = self.bridge().call("Ping", timeout=5)

        self.assertEqual(result, {"func": "Ping", "name": "Año"})
        self.assertFalse((self.directory / "bridge" / "request.lua").exists())

    def test_given_progress_from_resolve_when_calling_then_it_reaches_the_callback_once(self):
        seen = []

        with FakeResolve(self.directory, lambda func: {"result": {}}, progress="10/40"):
            self.bridge().call("PlaceCaptions", timeout=5, on_progress=seen.append)

        self.assertEqual(seen, ["10/40"])

    def test_given_a_handler_error_when_calling_then_a_bridge_error_carries_its_message(self):
        with FakeResolve(self.directory, lambda func: {"error": "No hay proyecto"}):
            with self.assertRaisesRegex(BridgeError, "No hay proyecto"):
                self.bridge().call("GetTimelineInfo", timeout=5)

    def test_given_resolve_acknowledges_but_never_answers_when_calling_then_it_times_out_naming_the_function(self):
        with FakeResolve(self.directory, lambda func: None):
            with self.assertRaisesRegex(BridgeError, "no terminó 'PlaceCaptions' en 1 s") as raised:
                self.bridge().call("PlaceCaptions", timeout=1, ack_timeout=0.5)

        self.assertNotIsInstance(raised.exception, BridgeOffline)

    def test_given_no_bridge_when_calling_then_it_reports_offline_after_the_ack_timeout(self):
        started = time.monotonic()

        with self.assertRaises(BridgeOffline):
            self.bridge().call("Ping", timeout=10, ack_timeout=0.3)

        self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
