from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .words import Word, clean_words

Progress = Callable[[str, Optional[float]], None]

WHISPER_RELEASE_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
WINDOWS_ASSET = "whisper-bin-x64.zip"
MODEL_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
USER_AGENT = "WordCaps"
DEFAULT_LANGUAGE = "auto"
MAX_THREADS = 8
FALLBACK_CPU_COUNT = 4


@dataclass(frozen=True)
class WhisperModel:
    id: str
    filename: str
    size_mb: int
    label: str


BALANCED_MODEL = WhisperModel("small", "ggml-small-q5_1.bin", 181, "Equilibrado")
MODELS = {
    model.id: model
    for model in (
        WhisperModel("base", "ggml-base.bin", 148, "Rápido"),
        BALANCED_MODEL,
        WhisperModel("medium", "ggml-medium-q5_0.bin", 539, "Preciso"),
        WhisperModel("turbo", "ggml-large-v3-turbo-q5_0.bin", 574, "Máxima calidad"),
    )
}
DEFAULT_MODEL = BALANCED_MODEL.id


class WhisperError(Exception):
    pass


def _executable_name() -> str:
    return "whisper-cli.exe" if paths.is_windows() else "whisper-cli"


def find_whisper_cli() -> Path | None:
    override = os.environ.get("WORDCAPS_WHISPER_CLI")
    if override and Path(override).is_file():
        return Path(override)
    installed = sorted(paths.bin_dir().rglob(_executable_name()))
    if installed:
        return installed[0]
    on_path = shutil.which("whisper-cli")
    return Path(on_path) if on_path else None


def model_path(model_id: str) -> Path:
    if model_id not in MODELS:
        raise WhisperError(f"Modelo desconocido: {model_id}")
    return paths.models_dir() / MODELS[model_id].filename


def _download(url: str, target: Path, label: str, progress: Progress) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            progress(label, done / total if total else None)
    if total and done != total:
        partial.unlink(missing_ok=True)
        raise WhisperError(f"La descarga de {target.name} se cortó ({done} de {total} bytes). Vuelve a intentarlo.")
    os.replace(partial, target)


def _extract_zip(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise WhisperError(f"El zip de whisper.cpp contiene una ruta no válida: {member.filename}")
        bundle.extractall(root)


def install_whisper_cli(progress: Progress) -> Path:
    existing = find_whisper_cli()
    if existing:
        return existing
    if not paths.is_windows():
        raise WhisperError(
            "No encuentro whisper-cli. En macOS instálalo con 'brew install whisper-cpp' "
            "o indica su ruta en la variable WORDCAPS_WHISPER_CLI."
        )
    progress("Buscando la última versión de whisper.cpp", None)
    request = urllib.request.Request(WHISPER_RELEASE_API, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next((a for a in release.get("assets", []) if a.get("name") == WINDOWS_ASSET), None)
    if asset is None:
        raise WhisperError(f"La versión {release.get('tag_name')} de whisper.cpp no publica {WINDOWS_ASSET}.")
    archive = paths.bin_dir() / WINDOWS_ASSET
    _download(asset["browser_download_url"], archive, "Descargando whisper.cpp", progress)
    destination = paths.bin_dir() / "whisper.cpp"
    _extract_zip(archive, destination)
    archive.unlink()
    found = find_whisper_cli()
    if found is None:
        raise WhisperError("El paquete de whisper.cpp no contiene whisper-cli.")
    return found


def ensure_model(model_id: str, progress: Progress) -> Path:
    target = model_path(model_id)
    if target.is_file():
        return target
    model = MODELS[model_id]
    _download(MODEL_BASE_URL + model.filename, target, f"Descargando modelo {model.label} ({model.size_mb} MB)", progress)
    return target


def parse_whisper_json(data: dict) -> list[Word]:
    raw = []
    for segment in data.get("transcription", []):
        offsets = segment.get("offsets") or {}
        start = offsets.get("from")
        end = offsets.get("to")
        if start is None or end is None:
            continue
        raw.append(Word(str(segment.get("text", "")), start / 1000, end / 1000))
    return clean_words(raw)


def transcribe(
    audio: Path,
    model_id: str,
    language: str,
    progress: Progress,
) -> list[Word]:
    cli = install_whisper_cli(progress)
    model = ensure_model(model_id, progress)
    output_base = audio.with_suffix("")
    threads = str(max(1, min(MAX_THREADS, os.cpu_count() or FALLBACK_CPU_COUNT)))
    command = [
        str(cli), "-m", str(model), "-f", str(audio), "-l", language or DEFAULT_LANGUAGE,
        "-ml", "1", "-sow", "-oj", "-of", str(output_base), "-t", threads, "-np",
    ]
    progress("Transcribiendo audio (puede tardar unos minutos)", None)
    creation_flags = subprocess.CREATE_NO_WINDOW if paths.is_windows() else 0
    completed = subprocess.run(command, capture_output=True, creationflags=creation_flags)
    output = output_base.with_suffix(".json")
    if completed.returncode != 0 or not output.is_file():
        detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()[-5:]
        raise WhisperError("whisper.cpp falló: " + " | ".join(detail))
    data = json.loads(output.read_text(encoding="utf-8", errors="replace"))
    return parse_whisper_json(data)
