import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from wordcaps.bridge import BridgeError, ResolveBridge
from wordcaps.layout import CaptionSettings, Frame, build_clips
from wordcaps.paths import PROJECT_DIR
from wordcaps.words import Word

IMAGE = "alpine:3.20"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@unittest.skipUnless(docker_available(), "Docker is needed to run the Lua bridge")
class LuaBridgeEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="wordcaps-e2e-"))
        cls.addClassCleanup(shutil.rmtree, cls.directory, True)
        (cls.directory / "bridge").mkdir()
        cls.container = f"wordcaps-e2e-{uuid.uuid4().hex[:8]}"
        cls.addClassCleanup(subprocess.run, ["docker", "rm", "-f", cls.container], capture_output=True)
        subprocess.run(
            [
                "docker", "run", "-d", "--rm", "--name", cls.container,
                "-v", f"{PROJECT_DIR}:/src:ro",
                "-v", f"{cls.directory}:/work",
                IMAGE, "sh", "-c",
                "apk add --no-cache luajit >/dev/null && luajit /src/tests/lua/run_bridge.lua /work/bridge /work/Fusion.prefs",
            ],
            check=True,
            capture_output=True,
        )
        cls.bridge = ResolveBridge(cls.directory / "bridge", lambda: cls.directory / "Fusion.prefs")
        deadline = time.monotonic() + 120
        while True:
            try:
                cls.ping = cls.bridge.call("Ping", timeout=10, ack_timeout=5)
                break
            except BridgeError:
                if time.monotonic() > deadline:
                    raise

    def test_given_the_lua_bridge_when_pinging_then_it_reports_the_resolve_version(self):
        self.assertEqual(self.ping["version"], "21.1.0")

    def test_given_a_layout_when_placing_through_the_lua_bridge_then_every_clip_is_placed(self):
        timeline = self.bridge.call("GetTimelineInfo")
        words = [Word("¡Canción", 0.0, 0.4), Word("increíble!", 0.4, 1.0), Word("ñu", 1.2, 1.5)]
        layout = build_clips(words, CaptionSettings(), Frame.from_timeline(timeline))

        result = self.bridge.call(
            "PlaceCaptions",
            {"templateName": "WordCaps Word", "lanes": layout["lanes"], "clips": layout["clips"]},
        )

        self.assertEqual(result["placed"], len(layout["clips"]))
        self.assertEqual(result["failed"], 0)
        self.assertEqual(layout["lanes"], 2)
        self.assertEqual(result["tracks"], [3, 4])

    def test_given_a_lua_error_when_calling_then_it_arrives_as_a_bridge_error_in_spanish(self):
        with self.assertRaisesRegex(BridgeError, "No encuentro la plantilla 'Ñandú'"):
            self.bridge.call("PlaceCaptions", {"templateName": "Ñandú", "lanes": 1, "clips": []})


if __name__ == "__main__":
    unittest.main()
