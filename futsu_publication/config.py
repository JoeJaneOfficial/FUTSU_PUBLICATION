"""The per-game release configuration: ``publication/publication.toml`` in the game repository.

Example (Dirty Peloton)::

    [game]
    name = "DirtyPeloton"            # executable and archive name
    package = "dirty_peloton"        # the importable package, installed into the build venv
    version_file = "dirty_peloton/version.py"   # defines VERSION = "x.y.z"
    python = "3.12"
    launcher = "publication/launcher.py"
    icon = "dirty_peloton/assets/marque/icone_dcm_2030/icone_dcm_2030.ico"
    lock = "publication/verrou.txt"
    collect_package_data = true      # package data declared in pyproject (PyInstaller --collect-data)
    extra_data = []                  # [["assets", "assets"], ...] : folders outside the package
    smoke_args = ["--verifier"]      # the report path is appended

    [qt]                             # optional: PySide6 games only
    prune = ["Qt6Quick.dll", "plugins/tls", ...]
    languages = ["fr", "en", "ja"]

    [steam]
    sdk_dir = "publication/steam"    # steam_api64.dll goes here (never committed)
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path("publication") / "publication.toml"


@dataclass(frozen=True)
class QtConfig:
    prune: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameConfig:
    root: Path
    name: str
    package: str
    version_file: Path
    python: str
    launcher: Path
    lock: Path
    icon: Path | None = None
    collect_package_data: bool = True
    extra_data: tuple[tuple[Path, str], ...] = ()
    smoke_args: tuple[str, ...] = ()
    qt: QtConfig = field(default_factory=QtConfig)
    steam_sdk_dir: Path | None = None

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def venv(self) -> Path:
        return self.build_dir / "venv-pub"

    @property
    def dist(self) -> Path:
        return self.build_dir / "dist" / self.name

    def version(self) -> str:
        namespace: dict[str, object] = {}
        exec(self.version_file.read_text(encoding="utf-8"), namespace)
        return str(namespace["VERSION"])


def load_config(root: Path, path: Path | None = None) -> GameConfig:
    """Reads the game's ``publication.toml`` (paths are relative to the repository root)."""
    root = root.resolve()
    raw = tomllib.loads((root / (path or DEFAULT_CONFIG)).read_text(encoding="utf-8"))
    game = raw["game"]
    qt = raw.get("qt", {})
    steam = raw.get("steam", {})
    return GameConfig(
        root=root,
        name=str(game["name"]),
        package=str(game["package"]),
        version_file=root / game["version_file"],
        python=str(game["python"]),
        launcher=root / game["launcher"],
        lock=root / game["lock"],
        icon=root / game["icon"] if game.get("icon") else None,
        collect_package_data=bool(game.get("collect_package_data", True)),
        extra_data=tuple((root / src, str(dst)) for src, dst in game.get("extra_data", ())),
        smoke_args=tuple(str(a) for a in game.get("smoke_args", ())),
        qt=QtConfig(tuple(qt.get("prune", ())), tuple(qt.get("languages", ()))),
        steam_sdk_dir=root / steam["sdk_dir"] if steam.get("sdk_dir") else None,
    )
