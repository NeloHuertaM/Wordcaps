from __future__ import annotations

import time
from pathlib import Path

from . import paths, whisper
from .bridge import (
    EXPORT_AUDIO,
    GET_EXPORT_STATUS,
    GET_TIMELINE_INFO,
    PLACE_CAPTIONS,
    BridgeError,
    ResolveBridge,
)
from .jobs import Job
from .layout import CaptionSettings, Frame, build_clips
from .words import Word

EXPORT_TIMEOUT_SECONDS = 30 * 60
EXPORT_RENDERING = "rendering"
EXPORT_DONE = "done"
EXPORT_FAILED = "failed"
PLACE_TIMEOUT_BASE_SECONDS = 120
PLACE_TIMEOUT_PER_CLIP_SECONDS = 1


def _find_rendered_audio(directory: Path, name: str) -> Path:
    for candidate in sorted(directory.glob(name + ".*")):
        if candidate.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg"):
            return candidate
    raise BridgeError(f"Resolve terminó el render pero no encuentro {name}.wav en {directory}.")


def export_timeline_audio(bridge: ResolveBridge, job: Job) -> Path:
    directory = paths.work_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"wordcaps-audio-{int(time.time())}"
    job.report("Renderizando el audio del timeline en Resolve")
    bridge.call(EXPORT_AUDIO, {"dir": str(directory), "name": name}, timeout=60)
    deadline = time.monotonic() + EXPORT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = bridge.call(GET_EXPORT_STATUS, timeout=30)
        state = status["state"]
        if state == EXPORT_RENDERING:
            job.report("Renderizando el audio del timeline en Resolve", (status.get("progress") or 0) / 100)
        elif state == EXPORT_DONE:
            return _find_rendered_audio(directory, name)
        elif state == EXPORT_FAILED:
            raise BridgeError("El render del audio falló: " + str(status.get("error")))
        else:
            raise BridgeError("Resolve perdió el trabajo de render del audio.")
        time.sleep(1)
    raise BridgeError(f"El render del audio tardó más de {EXPORT_TIMEOUT_SECONDS // 60} minutos.")


def transcribe_timeline(bridge: ResolveBridge, job: Job, model: str, language: str) -> dict:
    timeline = bridge.call(GET_TIMELINE_INFO)
    audio = export_timeline_audio(bridge, job)
    try:
        words = whisper.transcribe(audio, model, language, job.report)
    finally:
        audio.unlink(missing_ok=True)
        audio.with_suffix(".json").unlink(missing_ok=True)
    return {"words": [w.to_dict() for w in words], "timeline": timeline}


def place_captions(bridge: ResolveBridge, job: Job, words: list[Word], settings: CaptionSettings, template: dict) -> dict:
    job.report("Leyendo el timeline")
    timeline = bridge.call(GET_TIMELINE_INFO)
    layout = build_clips(words, settings, Frame.from_timeline(timeline))
    clips = layout["clips"]
    if not clips:
        raise BridgeError("No hay palabras dentro de la duración del timeline.")
    job.report(f"Creando {len(clips)} clips Text+ en Resolve", 0)

    def on_progress(value: str) -> None:
        done, _, total = value.partition("/")
        job.report(f"Creando {len(clips)} clips Text+ en Resolve", int(done) / max(1, int(total)))

    result = bridge.call(
        PLACE_CAPTIONS,
        {
            "templateId": template.get("id"),
            "templateName": template.get("name"),
            "lanes": layout["lanes"],
            "clips": clips,
        },
        timeout=PLACE_TIMEOUT_BASE_SECONDS + PLACE_TIMEOUT_PER_CLIP_SECONDS * len(clips),
        on_progress=on_progress,
    )
    return {**result, "clips": len(clips), "groups": len(layout["groups"])}


def run_all(bridge: ResolveBridge, job: Job, model: str, language: str, settings: CaptionSettings, template: dict) -> dict:
    transcript = transcribe_timeline(bridge, job, model, language)
    words = [Word.from_dict(w) for w in transcript["words"]]
    placed = place_captions(bridge, job, words, settings, template)
    return {**placed, "words": transcript["words"]}
