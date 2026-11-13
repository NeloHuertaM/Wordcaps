from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from wordcaps import installer, paths, whisper


def no_progress(stage, value=None):
    return None


class ExtractZipTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="wordcaps-zip-"))
        self.addCleanup(shutil.rmtree, self.directory, True)

    def make_zip(self, member: str) -> Path:
        archive = self.directory / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(member, b"x")
        return archive

    def test_given_a_member_that_escapes_the_destination_when_extracting_then_nothing_is_written(self):
        archive = self.make_zip("../evil.txt")

        with self.assertRaises(whisper.WhisperError):
            whisper._extract_zip(archive, self.directory / "out")

        self.assertFalse((self.directory / "evil.txt").exists())

    def test_given_a_regular_archive_when_extracting_then_files_land_inside_the_destination(self):
        archive = self.make_zip("Release/whisper-cli.exe")

        whisper._extract_zip(archive, self.directory / "out")

        self.assertTrue((self.directory / "out" / "Release" / "whisper-cli.exe").is_file())


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, length: int | None = None) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


def zip_bytes(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(member, b"exe")
    return buffer.getvalue()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="wordcaps-dl-"))
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.dict(os.environ, {"WORDCAPS_DATA_DIR": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def urlopen(self, *responses):
        return mock.patch.object(whisper.urllib.request, "urlopen", side_effect=list(responses))

    def test_given_a_missing_model_when_ensuring_then_it_is_downloaded_from_the_model_repository(self):
        with self.urlopen(FakeResponse(b"weights")) as urlopen:
            path = whisper.ensure_model("small", no_progress)

        self.assertEqual(path, self.data / "models" / "ggml-small-q5_1.bin")
        self.assertEqual(path.read_bytes(), b"weights")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin",
        )

    def test_given_a_model_on_disk_when_ensuring_then_nothing_is_downloaded(self):
        target = self.data / "models" / "ggml-base.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"cached")

        with self.urlopen() as urlopen:
            path = whisper.ensure_model("base", no_progress)

        self.assertEqual(path, target)
        urlopen.assert_not_called()

    def test_given_a_download_that_ends_early_when_ensuring_then_it_fails_and_leaves_no_model_behind(self):
        with self.urlopen(FakeResponse(b"wei", length=7)):
            with self.assertRaisesRegex(whisper.WhisperError, "se cortó"):
                whisper.ensure_model("small", no_progress)

        self.assertEqual(list((self.data / "models").iterdir()), [])

    def test_given_windows_without_whisper_when_installing_then_the_release_zip_is_extracted(self):
        release = {"tag_name": "v9", "assets": [{"name": "whisper-bin-x64.zip", "browser_download_url": "https://x/zip"}]}
        responses = (FakeResponse(json.dumps(release).encode()), FakeResponse(zip_bytes("Release/whisper-cli.exe")))

        with mock.patch.object(paths.sys, "platform", paths.WINDOWS), mock.patch.object(whisper.shutil, "which", return_value=None):
            with self.urlopen(*responses):
                cli = whisper.install_whisper_cli(no_progress)

        self.assertEqual(cli, self.data / "bin" / "whisper.cpp" / "Release" / "whisper-cli.exe")
        self.assertFalse((self.data / "bin" / "whisper-bin-x64.zip").exists())

    def test_given_a_release_without_the_windows_zip_when_installing_then_it_names_the_missing_asset(self):
        release = {"tag_name": "v9", "assets": []}

        with mock.patch.object(paths.sys, "platform", paths.WINDOWS), mock.patch.object(whisper.shutil, "which", return_value=None):
            with self.urlopen(FakeResponse(json.dumps(release).encode())):
                with self.assertRaisesRegex(whisper.WhisperError, "v9 .* whisper-bin-x64.zip"):
                    whisper.install_whisper_cli(no_progress)

    def test_given_a_whisper_cli_override_when_finding_then_it_wins_over_everything_else(self):
        cli = self.data / "custom" / "whisper-cli"
        cli.parent.mkdir()
        cli.write_bytes(b"")

        with mock.patch.dict(os.environ, {"WORDCAPS_WHISPER_CLI": str(cli)}):
            self.assertEqual(whisper.find_whisper_cli(), cli)

    def test_given_several_resolve_profiles_when_locating_prefs_then_the_newest_wins(self):
        profiles = self.data / "Support" / "Fusion" / "Profiles"
        for name, mtime in (("Default", 1_000), ("Other", 2_000)):
            prefs = profiles / name / "Fusion.prefs"
            prefs.parent.mkdir(parents=True)
            prefs.write_text("{}", encoding="utf-8")
            os.utime(prefs, (mtime, mtime))

        with mock.patch.dict(os.environ, {"WORDCAPS_RESOLVE_SUPPORT_DIR": str(self.data / "Support")}):
            self.assertEqual(paths.fusion_prefs_path(), profiles / "Other" / "Fusion.prefs")

    def test_given_macos_without_whisper_when_installing_then_it_points_to_homebrew(self):
        with mock.patch.object(paths.sys, "platform", paths.MACOS), mock.patch.object(whisper.shutil, "which", return_value=None):
            with self.assertRaisesRegex(whisper.WhisperError, "brew install whisper-cpp"):
                whisper.install_whisper_cli(no_progress)


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="wordcaps-whisper-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.audio = self.directory / "audio.wav"
        self.audio.write_bytes(b"RIFF")
        for target, value in (("install_whisper_cli", Path("whisper-cli")), ("ensure_model", Path("model.bin"))):
            patcher = mock.patch.object(whisper, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_whisper(self, returncode: int, output: dict | None, stderr: bytes = b""):
        def fake_run(command, **_):
            if output is not None:
                self.audio.with_suffix(".json").write_text(json.dumps(output), encoding="utf-8")
            return subprocess.CompletedProcess(command, returncode, b"", stderr)

        with mock.patch.object(whisper.subprocess, "run", side_effect=fake_run) as run:
            words = whisper.transcribe(self.audio, "small", "es", no_progress)
        return words, run.call_args.args[0]

    def test_given_word_level_output_when_transcribing_then_whisper_runs_with_word_flags_and_words_return(self):
        output = {"transcription": [{"offsets": {"from": 0, "to": 500}, "text": " hola"}]}

        words, command = self.run_whisper(0, output)

        self.assertEqual([w.text for w in words], ["hola"])
        self.assertEqual(command[5:11], ["-l", "es", "-ml", "1", "-sow", "-oj"])

    def test_given_whisper_fails_when_transcribing_then_the_tail_of_its_stderr_is_reported(self):
        with self.assertRaisesRegex(whisper.WhisperError, "failed to read audio"):
            self.run_whisper(1, None, b"loading\nerror: failed to read audio\n")

    def test_given_whisper_exits_cleanly_without_json_when_transcribing_then_it_is_an_error(self):
        with self.assertRaises(whisper.WhisperError):
            self.run_whisper(0, None)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="wordcaps-install-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.support = self.directory / "Support"
        environment = {
            "WORDCAPS_DATA_DIR": str(self.directory / "data"),
            "WORDCAPS_RESOLVE_SUPPORT_DIR": str(self.support),
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_given_no_resolve_folder_when_installing_then_it_explains_what_is_missing(self):
        with self.assertRaisesRegex(installer.InstallError, "No encuentro la carpeta de DaVinci Resolve"):
            installer.install()

    def test_given_a_resolve_folder_when_installing_then_the_launcher_has_real_paths_and_counts_as_installed(self):
        self.support.mkdir()
        self.assertFalse(installer.is_installed())

        launcher = installer.install()

        content = launcher.read_text(encoding="utf-8")
        self.assertNotIn("__WORDCAPS_", content)
        self.assertIn((self.directory / "data" / "bridge").resolve().as_posix(), content)
        self.assertEqual(launcher.parent, self.support / "Fusion" / "Scripts" / "Utility")
        self.assertTrue(installer.is_installed())

    def test_given_a_launcher_from_another_install_when_checking_then_it_is_not_installed(self):
        self.support.mkdir()
        launcher = installer.install()
        launcher.write_text("local core_path = [==[C:/old/wordcaps_core.lua]==]", encoding="utf-8")

        self.assertFalse(installer.is_installed())

    def test_given_a_non_ascii_path_when_rendering_the_launcher_then_it_is_refused(self):
        with self.assertRaisesRegex(installer.InstallError, "no ASCII"):
            installer.render_launcher(Path("C:/Usuarios/Íñigo/core.lua"), Path("C:/x"))


if __name__ == "__main__":
    unittest.main()
