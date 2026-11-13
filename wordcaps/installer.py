from __future__ import annotations

from pathlib import Path

from . import paths

LAUNCHER_NAME = "WordCaps.lua"
CORE_PATH = paths.RESOLVE_SCRIPTS_DIR / "wordcaps_core.lua"


class InstallError(Exception):
    pass


def _lua_path(path: Path) -> str:
    text = path.resolve().as_posix()
    if not text.isascii():
        raise InstallError(
            f"La ruta {text} contiene caracteres no ASCII y Resolve no puede abrirla desde un script. "
            "Mueve WordCaps a una carpeta con nombre sencillo o define WORDCAPS_DATA_DIR."
        )
    return text


def render_launcher(core_path: Path, mailbox: Path) -> str:
    template = (paths.RESOLVE_SCRIPTS_DIR / LAUNCHER_NAME).read_text(encoding="utf-8")
    return (
        template.replace("__WORDCAPS_CORE_PATH__", _lua_path(core_path))
        .replace("__WORDCAPS_MAILBOX_DIR__", _lua_path(mailbox))
    )


def installed_launcher() -> Path:
    return paths.resolve_utility_scripts_dir() / LAUNCHER_NAME


def is_installed() -> bool:
    launcher = installed_launcher()
    if not launcher.is_file():
        return False
    expected = render_launcher(CORE_PATH, paths.mailbox_dir())
    return launcher.read_text(encoding="utf-8") == expected


def install() -> Path:
    if not paths.resolve_support_dir().is_dir():
        raise InstallError(
            f"No encuentro la carpeta de DaVinci Resolve en {paths.resolve_support_dir()}. "
            "¿Está Resolve instalado y lo has abierto al menos una vez?"
        )
    mailbox = paths.mailbox_dir()
    mailbox.mkdir(parents=True, exist_ok=True)
    content = render_launcher(CORE_PATH, mailbox)
    target = installed_launcher()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
