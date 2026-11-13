import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from wordcaps import server
from wordcaps.bridge import BridgeError, BridgeOffline
from wordcaps.server import App, serve


class FakeBridge:
    def call(self, func, args=None, **_):
        if func == "GetTimelineInfo":
            return {"fps": 25, "width": 1920, "height": 1080, "startFrame": 0, "endFrame": 2500}
        if func == "PlaceCaptions":
            return {"placed": len(args["clips"]), "failed": 0, "tracks": [2]}
        return {}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(bridge=FakeBridge())
        cls.server = serve(cls.app, 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, body=None, token=None, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        request.add_header("X-WordCaps-Token", token if token is not None else self.app.token)
        if host:
            request.add_header("Host", host)
        if body is not None:
            request.data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_given_the_index_when_served_then_the_session_token_is_embedded(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as response:
            html = response.read().decode("utf-8")

        self.assertIn(self.app.token, html)

    def test_given_a_wrong_token_when_calling_the_api_then_it_is_forbidden(self):
        status, payload = self.request("/api/layout", {}, token="nope")

        self.assertEqual(status, 403)
        self.assertIn("Token", payload["error"])

    def test_given_a_foreign_host_header_when_calling_the_api_then_it_is_forbidden(self):
        status, _ = self.request("/api/layout", {}, host="evil.example:80")

        self.assertEqual(status, 403)

    def test_given_words_when_requesting_a_layout_then_clips_come_back(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}, {"text": "mundo", "start": 0.5, "end": 1}]

        status, payload = self.request("/api/layout", {"words": words, "settings": {"max_words": 2}})

        self.assertEqual(status, 200)
        self.assertEqual([c["text"] for c in payload["result"]["clips"]], ["HOLA", "MUNDO"])

    def test_given_invalid_settings_when_requesting_a_layout_then_the_error_is_a_400(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}]

        status, payload = self.request("/api/layout", {"words": words, "settings": {"mode": "spin"}})

        self.assertEqual(status, 400)
        self.assertIn("Modo desconocido", payload["error"])

    def test_given_an_srt_when_importing_then_words_come_back(self):
        content = "1\n00:00:00,000 --> 00:00:01,000\nhola mundo\n"

        status, payload = self.request("/api/import-srt", {"content": content})

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["result"]["words"]), 2)

    def raw_post(self, path, body: bytes, content_length: int):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        try:
            connection.putrequest("POST", path)
            connection.putheader("X-WordCaps-Token", self.app.token)
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            if body:
                connection.send(body)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_given_invalid_json_when_posting_then_the_error_is_a_400(self):
        status, payload = self.raw_post("/api/layout", b"{nope", 5)

        self.assertEqual(status, 400)
        self.assertIn("JSON", payload["error"])

    def test_given_an_invalid_content_length_when_posting_then_the_error_is_a_400(self):
        for length in ("abc", "-1"):
            with self.subTest(length=length):
                connection = http.client.HTTPConnection("127.0.0.1", self.port)
                connection.putrequest("POST", "/api/layout")
                connection.putheader("X-WordCaps-Token", self.app.token)
                connection.putheader("Content-Length", length)
                connection.endheaders()
                response = connection.getresponse()
                response.read()
                connection.close()
                self.assertEqual(response.status, 400)

    def test_given_an_oversized_body_when_posting_then_it_is_refused_before_reading(self):
        status, _ = self.raw_post("/api/layout", b"", 60 * 1024 * 1024)

        self.assertEqual(status, 413)

    def test_given_an_unknown_job_when_polling_then_the_error_is_a_404(self):
        status, _ = self.request("/api/jobs/doesnotexist")

        self.assertEqual(status, 404)

    def test_given_a_partial_timeline_when_requesting_a_layout_then_the_error_is_a_400(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}]

        status, payload = self.request("/api/layout", {"words": words, "timeline": {"fps": 25}})

        self.assertEqual(status, 400)
        self.assertIn("timeline", payload["error"])

    def test_given_wrongly_typed_settings_when_requesting_a_layout_then_the_error_is_a_400(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}]
        for settings in ({"glyph_widths": [1]}, {"color": 7}, {"keywords": "a"}):
            with self.subTest(settings=settings):
                status, _ = self.request("/api/layout", {"words": words, "settings": settings})
                self.assertEqual(status, 400)

    def test_given_a_route_that_crashes_when_called_then_the_error_is_a_json_500(self):
        def crash(_):
            raise RuntimeError("boom")

        self.app.routes[("POST", "/api/crash")] = crash
        try:
            with mock.patch("wordcaps.server.traceback.print_exc"):
                status, payload = self.request("/api/crash", {})
        finally:
            del self.app.routes[("POST", "/api/crash")]

        self.assertEqual(status, 500)
        self.assertIn("boom", payload["error"])

    def test_given_resolve_reports_an_error_when_a_route_calls_it_then_the_error_is_a_502(self):
        def offline(_):
            raise BridgeError("Resolve no responde")

        self.app.routes[("POST", "/api/offline")] = offline
        try:
            status, payload = self.request("/api/offline", {})
        finally:
            del self.app.routes[("POST", "/api/offline")]

        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "Resolve no responde")

    def test_given_an_unknown_model_when_transcribing_then_the_error_is_a_400(self):
        for path in ("/api/transcribe", "/api/run-all"):
            with self.subTest(path=path):
                body = {"model": "gigante", "settings": {}, "template": {"name": "x"}}
                status, payload = self.request(path, body)
                self.assertEqual(status, 400)
                self.assertIn("gigante", payload["error"])

    def test_given_a_transcribe_request_when_posted_then_the_job_returns_the_transcript(self):
        transcript = {"words": [{"text": "hola", "start": 0, "end": 1}], "timeline": {}}

        with mock.patch.object(server.workflows, "transcribe_timeline", return_value=transcript) as transcribe:
            _, payload = self.request("/api/transcribe", {"model": "base", "language": "es"})
            job = self.wait_for_job(payload["result"]["job"])

        self.assertEqual(job["result"], transcript)
        self.assertEqual(transcribe.call_args.args[2:], ("base", "es"))

    def test_given_a_run_all_request_when_posted_then_the_job_runs_with_the_parsed_settings(self):
        with mock.patch.object(server.workflows, "run_all", return_value={"placed": 1}) as run_all:
            _, payload = self.request("/api/run-all", {"settings": {"max_words": 2}, "template": {"name": "x"}})
            job = self.wait_for_job(payload["result"]["job"])

        self.assertEqual(job["result"], {"placed": 1})
        self.assertEqual(run_all.call_args.args[4].max_words, 2)

    def test_given_the_status_when_requested_then_resolve_and_whisper_state_come_back(self):
        status, payload = self.request("/api/status")

        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["resolve"]["online"])
        self.assertEqual(payload["result"]["whisper"]["defaultModel"], "small")

    def test_given_resolve_is_closed_when_requesting_the_status_then_it_reports_offline_with_the_reason(self):
        offline = mock.Mock()
        offline.call.side_effect = BridgeOffline("DaVinci Resolve no responde.")

        with mock.patch.object(self.app, "bridge", offline):
            status, payload = self.request("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["resolve"], {"online": False, "error": "DaVinci Resolve no responde."})

    def test_given_no_resolve_folder_when_installing_the_script_then_the_error_is_a_400(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = {"WORDCAPS_RESOLVE_SUPPORT_DIR": directory + "/none", "WORDCAPS_DATA_DIR": directory}
            with mock.patch.dict(os.environ, missing):
                status, payload = self.request("/api/install-script", {})

        self.assertEqual(status, 400)
        self.assertIn("DaVinci Resolve", payload["error"])

    def test_given_the_defaults_when_requested_then_settings_and_animations_come_back(self):
        status, payload = self.request("/api/defaults")

        self.assertEqual(status, 200)
        self.assertIn("pop", payload["result"]["animations"])
        self.assertNotIn("glyph_widths", payload["result"]["settings"])

    def test_given_a_place_request_when_posted_then_a_job_runs_to_completion(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}, {"text": "mundo", "start": 0.5, "end": 1}]
        body = {"words": words, "settings": {}, "template": {"name": "WordCaps Word"}}

        _, payload = self.request("/api/place", body)
        job = self.wait_for_job(payload["result"]["job"])

        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"]["placed"], 2)

    def wait_for_job(self, job_id: str) -> dict:
        deadline = time.monotonic() + 5
        job = self.request(f"/api/jobs/{job_id}")[1]["result"]
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            job = self.request(f"/api/jobs/{job_id}")[1]["result"]
        return job

    def test_given_a_place_request_without_template_when_posting_then_it_asks_for_one(self):
        words = [{"text": "hola", "start": 0, "end": 0.5}]

        status, payload = self.request("/api/place", {"words": words, "settings": {}})

        self.assertEqual(status, 400)
        self.assertIn("plantilla", payload["error"])


if __name__ == "__main__":
    unittest.main()
