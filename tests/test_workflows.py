import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from wordcaps import workflows
from wordcaps.bridge import BridgeError
from wordcaps.jobs import Job, JobManager
from wordcaps.layout import CaptionSettings
from wordcaps.words import Word

TIMELINE = {"fps": 30, "width": 1080, "height": 1920, "startFrame": 0, "endFrame": 900}


class ScriptedBridge:
    def __init__(self, statuses, on_done=None):
        self.statuses = list(statuses)
        self.on_done = on_done
        self.calls = []

    def call(self, func, args=None, **kwargs):
        self.calls.append((func, args, kwargs))
        if func == "GetTimelineInfo":
            return TIMELINE
        if func == "ExportAudio":
            self.export_args = args
            return {"started": True}
        if func == "GetExportStatus":
            status = self.statuses.pop(0)
            if status["state"] == "done" and self.on_done:
                self.on_done(self.export_args)
            return status
        if func == "PlaceCaptions":
            kwargs["on_progress"]("25/50")
            return {"placed": len(args["clips"]), "failed": 0, "tracks": [3]}
        raise AssertionError(func)


class ExportAudioTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="wordcaps-wf-")
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.dict(os.environ, {"WORDCAPS_DATA_DIR": self.data})
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(workflows.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_given_a_render_that_progresses_when_exporting_then_progress_is_reported_and_the_wav_returned(self):
        def write_wav(args):
            Path(args["dir"], args["name"] + ".wav").write_bytes(b"RIFF")

        bridge = ScriptedBridge([{"state": "rendering", "progress": 40}, {"state": "done"}], on_done=write_wav)
        job = Job(id="j")
        reports = []
        job.report = lambda stage, progress=None: reports.append(progress)

        audio = workflows.export_timeline_audio(bridge, job)

        self.assertEqual(audio.suffix, ".wav")
        self.assertIn(0.4, reports)

    def test_given_a_failed_render_when_exporting_then_resolves_error_is_raised(self):
        bridge = ScriptedBridge([{"state": "failed", "error": "Disco lleno"}])

        with self.assertRaisesRegex(BridgeError, "Disco lleno"):
            workflows.export_timeline_audio(bridge, Job(id="j"))

    def test_given_resolve_lost_the_job_when_exporting_then_it_says_so(self):
        bridge = ScriptedBridge([{"state": "idle"}])

        with self.assertRaisesRegex(BridgeError, "perdió"):
            workflows.export_timeline_audio(bridge, Job(id="j"))

    def test_given_a_finished_render_without_a_file_when_exporting_then_the_missing_file_is_named(self):
        bridge = ScriptedBridge([{"state": "done"}])

        with self.assertRaisesRegex(BridgeError, "no encuentro"):
            workflows.export_timeline_audio(bridge, Job(id="j"))

    def test_given_a_render_that_never_ends_when_exporting_then_it_times_out(self):
        bridge = ScriptedBridge([])
        clock = mock.patch.object(workflows.time, "monotonic", side_effect=[0, 10**6])

        with clock, mock.patch.object(workflows, "EXPORT_TIMEOUT_SECONDS", 120):
            with self.assertRaisesRegex(BridgeError, "tardó más de 2 minutos"):
                workflows.export_timeline_audio(bridge, Job(id="j"))


class TranscribeTimelineTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="wordcaps-tr-"))
        self.addCleanup(shutil.rmtree, self.data, True)
        self.audio = self.data / "audio.wav"
        self.audio.write_bytes(b"RIFF")
        self.audio.with_suffix(".json").write_text("{}", encoding="utf-8")
        exporter = mock.patch.object(workflows, "export_timeline_audio", return_value=self.audio)
        exporter.start()
        self.addCleanup(exporter.stop)

    def test_given_a_transcription_when_it_finishes_then_words_and_timeline_return_and_the_audio_is_deleted(self):
        with mock.patch.object(workflows.whisper, "transcribe", return_value=[Word("hola", 0, 0.5)]):
            result = workflows.transcribe_timeline(ScriptedBridge([]), Job(id="j"), "small", "es")

        self.assertEqual(result, {"words": [{"text": "hola", "start": 0, "end": 0.5}], "timeline": TIMELINE})
        self.assertFalse(self.audio.exists())
        self.assertFalse(self.audio.with_suffix(".json").exists())

    def test_given_whisper_fails_when_transcribing_then_the_audio_is_still_deleted(self):
        with mock.patch.object(workflows.whisper, "transcribe", side_effect=RuntimeError("whisper")):
            with self.assertRaises(RuntimeError):
                workflows.transcribe_timeline(ScriptedBridge([]), Job(id="j"), "small", "es")

        self.assertFalse(self.audio.exists())

    def test_given_run_all_when_it_finishes_then_the_result_carries_the_words_and_the_placement(self):
        with mock.patch.object(workflows.whisper, "transcribe", return_value=[Word("hola", 0, 0.5)]):
            result = workflows.run_all(ScriptedBridge([]), Job(id="j"), "small", "es", CaptionSettings(), {"name": "x"})

        self.assertEqual(result["words"], [{"text": "hola", "start": 0, "end": 0.5}])
        self.assertEqual(result["placed"], 1)


class PlaceCaptionsTests(unittest.TestCase):
    def test_given_words_when_placing_then_progress_from_resolve_reaches_the_job(self):
        bridge = ScriptedBridge([])
        job = Job(id="j")
        words = [Word("hola", 0, 0.5), Word("mundo", 0.5, 1.0)]

        result = workflows.place_captions(bridge, job, words, CaptionSettings(), {"name": "WordCaps Word"})

        self.assertEqual(result["placed"], 2)
        self.assertEqual(job.progress, 0.5)

    def test_given_words_past_the_timeline_when_placing_then_nothing_is_sent_to_resolve(self):
        bridge = ScriptedBridge([])

        with self.assertRaisesRegex(BridgeError, "No hay palabras"):
            workflows.place_captions(bridge, Job(id="j"), [Word("tarde", 100, 101)], CaptionSettings(), {"name": "x"})

        self.assertNotIn("PlaceCaptions", [c[0] for c in bridge.calls])


class JobManagerTests(unittest.TestCase):
    def test_given_work_that_raises_when_run_then_the_job_fails_with_the_message(self):
        manager = JobManager()

        def explode(job):
            raise RuntimeError("se rompió")

        with mock.patch("wordcaps.jobs.traceback.print_exc"):
            job = wait_until_finished(manager.start(explode))

        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "se rompió")


def wait_until_finished(job: Job) -> Job:
    deadline = time.monotonic() + 5
    while job.state == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    return job


if __name__ == "__main__":
    unittest.main()
