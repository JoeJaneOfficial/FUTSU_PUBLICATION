"""Game logs in the player's data folder: what you need to read a player's bug report.

``<data dir>/logs`` (``journaux`` for French games, see ``install``) holds ``game.log`` (rotating),
``errors.log`` (every error, dated, with the version and the system) and ``crashes.log`` (hard
crashes Python cannot catch, such as a Qt or OpenGL fault, through ``faulthandler``).
"""

from __future__ import annotations

import datetime
import faulthandler
import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

MAX_BYTES = 1_000_000
BACKUPS = 3
_crash_files: list[TextIO] = []
"""The crash file stays open: faulthandler writes into it at the moment of the crash."""


def data_dir(app: str, override_env: str | None = None) -> Path:
    """``%APPDATA%/<app>`` (``$XDG_DATA_HOME`` or ``~/.local/share`` elsewhere); an environment
    variable can replace it (tests)."""
    if override_env and os.environ.get(override_env):
        return Path(os.environ[override_env])
    root = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    base = Path(root) if root else Path.home() / ".local" / "share"
    return base / app


def install(
    folder: Path, version: str, names: tuple[str, str, str] = ("game.log", "errors.log", "crashes.log")
) -> Path:
    """Wires the logs at game start-up; returns their folder. ``names``: the three file names
    (a French game passes its own)."""
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / names[0], maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    if not _crash_files:
        crash = (folder / names[2]).open("a", encoding="utf-8")
        crash.write(f"\n--- start {timestamp()} · version {version}\n")
        crash.flush()
        _crash_files.append(crash)
        faulthandler.enable(crash)
    logging.getLogger("futsu_publication").info(
        "Start, version %s, Python %s, %s", version, platform.python_version(), system()
    )
    return folder


def record_error(folder: Path, text: str, version: str, name: str = "errors.log") -> Path:
    """Appends an error (its traceback) to the errors file; returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {timestamp()} · version {version} · {system()}\n{text}")
    logging.getLogger("futsu_publication").error("Error recorded in %s", path)
    return path


def timestamp() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def system() -> str:
    frozen = " (executable)" if getattr(sys, "frozen", False) else ""
    return f"{platform.system()} {platform.release()}{frozen}"
