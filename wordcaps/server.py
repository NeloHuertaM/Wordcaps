from __future__ import annotations

import json
import secrets
import traceback
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import VERSION, installer, paths, whisper, workflows
from . import bridge as bridge_calls
from .animations import ANIMATIONS
from .bridge import BridgeError, ResolveBridge
from .jobs import JobManager
from .layout import CaptionSettings, Frame, build_clips
from .srt import parse_srt
from .words import Word

STATIC_FILES = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
PREVIEW_TIMELINE = {"fps": 30, "width": 1080, "height": 1920, "startFrame": 0, "endFrame": 10**9}
MAX_BODY_BYTES = 50 * 1024 * 1024
GET = "GET"
POST = "POST"
ERROR_KEY = "error"


class ApiError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, bridge: ResolveBridge | None = None) -> None:
        self.bridge = bridge or ResolveBridge()
        self.jobs = JobManager()
        self.token = secrets.token_urlsafe(24)
        self.routes: dict[tuple[str, str], Callable[[dict], Any]] = {
            (GET, "/api/status"): self.status,
            (POST, "/api/install-script"): self.install_script,
            (POST, "/api/timeline"): lambda _: self.bridge.call(bridge_calls.GET_TIMELINE_INFO),
            (POST, "/api/templates"): lambda _: self.bridge.call(bridge_calls.LIST_TEMPLATES),
            (POST, "/api/create-template"): lambda _: self.bridge.call(bridge_calls.CREATE_TEMPLATE_CLIP),
            (POST, "/api/import-srt"): self.import_srt,
            (POST, "/api/layout"): self.layout,
            (POST, "/api/transcribe"): self.transcribe,
            (POST, "/api/place"): self.place,
            (POST, "/api/run-all"): self.run_all,
            (GET, "/api/defaults"): self.defaults,
        }

    def defaults(self, _: dict) -> dict:
        settings = asdict(CaptionSettings())
        settings.pop("glyph_widths")
        return {"settings": settings, "animations": ANIMATIONS}

    def status(self, _: dict) -> dict:
        try:
            resolve = {"online": True, "info": self.bridge.call(bridge_calls.PING, timeout=5, ack_timeout=2)}
        except BridgeError as error:
            resolve = {"online": False, ERROR_KEY: str(error)}
        cli = whisper.find_whisper_cli()
        return {
            "version": VERSION,
            "resolve": resolve,
            "scriptInstalled": installer.is_installed(),
            "launcherPath": str(installer.installed_launcher()),
            "prefsFound": paths.fusion_prefs_path() is not None,
            "whisper": {
                "cli": str(cli) if cli else None,
                "defaultModel": whisper.DEFAULT_MODEL,
                "models": [
                    {"id": m.id, "label": m.label, "sizeMb": m.size_mb, "installed": whisper.model_path(m.id).is_file()}
                    for m in whisper.MODELS.values()
                ],
            },
        }

    def install_script(self, _: dict) -> dict:
        try:
            return {"path": str(installer.install())}
        except (installer.InstallError, OSError) as error:
            raise ApiError(str(error)) from error

    def import_srt(self, body: dict) -> dict:
        words = parse_srt(str(body.get("content", "")))
        if not words:
            raise ApiError("El archivo no contiene subtítulos SRT válidos.")
        return {"words": [w.to_dict() for w in words]}

    def layout(self, body: dict) -> dict:
        try:
            frame = Frame.from_timeline(body.get("timeline") or PREVIEW_TIMELINE)
        except ValueError as error:
            raise ApiError(str(error)) from error
        return build_clips(_words(body), _settings(body), frame)

    def transcribe(self, body: dict) -> dict:
        model, language = _model(body), _language(body)
        job = self.jobs.start(lambda j: workflows.transcribe_timeline(self.bridge, j, model, language))
        return {"job": job.id}

    def place(self, body: dict) -> dict:
        words, settings, template = _words(body), _settings(body), _template(body)
        job = self.jobs.start(lambda j: workflows.place_captions(self.bridge, j, words, settings, template))
        return {"job": job.id}

    def run_all(self, body: dict) -> dict:
        model, language = _model(body), _language(body)
        settings, template = _settings(body), _template(body)
        job = self.jobs.start(lambda j: workflows.run_all(self.bridge, j, model, language, settings, template))
        return {"job": job.id}

    def job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError("Trabajo no encontrado.", HTTPStatus.NOT_FOUND)
        return job.to_dict()


def _words(body: dict) -> list[Word]:
    try:
        words = [Word.from_dict(w) for w in body.get("words") or []]
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(f"Lista de palabras no válida: {error}") from error
    if not words:
        raise ApiError("No hay palabras. Transcribe el audio o importa un SRT primero.")
    return words


def _settings(body: dict) -> CaptionSettings:
    try:
        return CaptionSettings.from_dict(body.get("settings"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ApiError(f"Ajustes no válidos: {error}") from error


def _template(body: dict) -> dict:
    template = body.get("template") or {}
    if not template.get("id") and not template.get("name"):
        raise ApiError("Elige una plantilla Text+ del Media Pool.")
    return template


def _language(body: dict) -> str:
    return str(body.get("language") or whisper.DEFAULT_LANGUAGE)


def _model(body: dict) -> str:
    model = str(body.get("model") or whisper.DEFAULT_MODEL)
    if model not in whisper.MODELS:
        raise ApiError(f"Modelo desconocido: {model}")
    return model


def make_handler(app: App, port: int) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self._dispatch(GET)

        def do_POST(self) -> None:
            self._dispatch(POST)

        def _dispatch(self, method: str) -> None:
            if self.headers.get("Host") not in allowed_hosts:
                self._send_error("Host no permitido.", HTTPStatus.FORBIDDEN)
                return
            path = self.path.split("?", 1)[0]
            if method == GET and not path.startswith("/api/"):
                self._serve_static(path)
                return
            if self.headers.get("X-WordCaps-Token") != app.token:
                self._send_error("Token no válido. Recarga la página.", HTTPStatus.FORBIDDEN)
                return
            try:
                body = self._read_body() if method == POST else {}
                if method == GET and path.startswith("/api/jobs/"):
                    result = app.job(path.rsplit("/", 1)[1])
                else:
                    route = app.routes.get((method, path))
                    if route is None:
                        raise ApiError("Ruta no encontrada.", HTTPStatus.NOT_FOUND)
                    result = route(body)
                self._send_json({"result": result})
            except ApiError as error:
                self._send_error(str(error), error.status)
            except BridgeError as error:
                self._send_error(str(error), HTTPStatus.BAD_GATEWAY)
            except Exception as error:
                traceback.print_exc()
                self._send_error(f"Error inesperado: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)

        def _read_body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as error:
                raise ApiError("Content-Length no válido.") from error
            if length < 0:
                raise ApiError("Content-Length no válido.")
            if length > MAX_BODY_BYTES:
                raise ApiError("La petición es demasiado grande.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise ApiError("El cuerpo de la petición no es JSON válido.") from error
            if not isinstance(body, dict):
                raise ApiError("El cuerpo de la petición debe ser un objeto JSON.")
            return body

        def _serve_static(self, path: str) -> None:
            if path in ("/", "/index.html"):
                html = (paths.WEB_DIR / "index.html").read_text(encoding="utf-8")
                self._send_bytes(html.replace("__WORDCAPS_TOKEN__", app.token).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path not in STATIC_FILES:
                self._send_error("No encontrado.", HTTPStatus.NOT_FOUND)
                return
            filename, content_type = STATIC_FILES[path]
            self._send_bytes((paths.WEB_DIR / filename).read_bytes(), content_type)

        def _send_error(self, message: str, status: HTTPStatus) -> None:
            self._send_json({ERROR_KEY: message}, status)

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _send_bytes(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve(app: App, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    server.RequestHandlerClass = make_handler(app, server.server_address[1])
    return server
