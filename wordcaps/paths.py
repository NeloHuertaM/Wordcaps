from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
RESOLVE_SCRIPTS_DIR = PROJECT_DIR / "resolve"
WEB_DIR = PACKAGE_DIR / "web"
WINDOWS = "win32"
MACOS = "darwin"


def is_windows() -> bool:
    return sys.platform == WINDOWS


def is_macos() -> bool:
    return sys.platform == MACOS


def data_dir() -> Path:
    override = os.environ.get("WORDCAPS_DATA_DIR")
    if override:
        return Path(override)
    if is_windows():
        return Path(os.environ["LOCALAPPDATA"]) / "WordCaps"
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "WordCaps"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "wordcaps"


def mailbox_dir() -> Path:
    return data_dir() / "bridge"


def models_dir() -> Path:
    return data_dir() / "models"


def bin_dir() -> Path:
    return data_dir() / "bin"


def work_dir() -> Path:
    return data_dir() / "work"


def resolve_support_dir() -> Path:
    override = os.environ.get("WORDCAPS_RESOLVE_SUPPORT_DIR")
    if override:
        return Path(override)
    if is_windows():
        return Path(os.environ["APPDATA"]) / "Blackmagic Design" / "DaVinci Resolve" / "Support"
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve"
    return Path.home() / ".local" / "share" / "DaVinciResolve"


def resolve_utility_scripts_dir() -> Path:
    return resolve_support_dir() / "Fusion" / "Scripts" / "Utility"


def fusion_prefs_path() -> Path | None:
    profiles = resolve_support_dir() / "Fusion" / "Profiles"
    candidates = [p / "Fusion.prefs" for p in profiles.glob("*") if (p / "Fusion.prefs").is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
