"""Reproducible build of a standalone game executable (PyInstaller, one-folder mode).

Steps: a clean build venv from the game's lock file (rebuilt only when the lock changes), the
game installed into it as a package (so the bundle holds exactly the data the package declares),
PyInstaller run from ``build/`` (run from the repository root it would read the source tree
instead of the installed package), optional Qt pruning, the Steamworks DLL if present, then a
smoke test of the frozen executable.

One-folder rather than one-file: fast start-up, light Steam patches (only changed files are
downloaded), and Qt's DLLs stay replaceable as the LGPL requires.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from futsu_publication.config import GameConfig

STEAM_DLL = "steam_api64.dll"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(str(c) for c in command), flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def base_python(version: str) -> list[str]:
    """The interpreter that creates the build venv: the running one if it has the right version
    (GitHub runners have no ``py`` launcher), otherwise the Windows ``py`` launcher."""
    if f"{sys.version_info.major}.{sys.version_info.minor}" == version:
        return [sys.executable]
    return ["py", f"-{version}"]


def venv_python(config: GameConfig) -> Path:
    return config.venv / "Scripts" / "python.exe"


def prepare_venv(config: GameConfig) -> None:
    """A fresh venv when the lock changes; the game is reinstalled at every build."""
    digest = hashlib.sha256(config.lock.read_bytes()).hexdigest()
    marker = config.venv / "lock.sha256"
    if not marker.exists() or marker.read_text() != digest:
        print("Fresh build venv (the lock file changed).")
        if config.venv.exists():
            shutil.rmtree(config.venv)
        run([*base_python(config.python), "-m", "venv", str(config.venv)])
        run([str(venv_python(config)), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        run([str(venv_python(config)), "-m", "pip", "install", "-q", "-r", str(config.lock)])
        marker.write_text(digest)
    run(
        [str(venv_python(config)), "-m", "pip", "install", "-q", "--no-deps", "--force-reinstall", "."],
        cwd=config.root,
    )


def freeze(config: GameConfig) -> Path:
    """PyInstaller, one-folder, windowed."""
    if config.dist.exists():
        shutil.rmtree(config.dist)
    command = [
        str(venv_python(config)),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        config.name,
        "--collect-submodules",
        config.package,
        "--distpath",
        str(config.dist.parent),
        "--workpath",
        str(config.build_dir / "work"),
        "--specpath",
        str(config.build_dir / "spec"),
    ]
    if config.icon is not None:
        command += ["--icon", str(config.icon)]
    if config.collect_package_data:
        command += ["--collect-data", config.package]
    for package in config.collect_data:
        command += ["--collect-data", package]
    for source, destination in config.extra_data:
        command += ["--add-data", f"{source}{';' if sys.platform == 'win32' else ':'}{destination}"]
    command.append(str(config.launcher))
    run(command, cwd=config.build_dir)
    return config.dist


def prune_qt(config: GameConfig, dist: Path | None = None) -> int:
    """Removes the Qt parts the game does not use (``[qt]`` in the config); returns bytes saved."""
    dist = dist or config.dist
    qt = dist / "_internal" / "PySide6"
    if not qt.is_dir() or not (config.qt.prune or config.qt.languages):
        return 0
    before = folder_size(dist)
    for relative in config.qt.prune:
        target = qt / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    translations = qt / "translations"
    if config.qt.languages and translations.is_dir():
        for f in translations.glob("*.qm"):
            if f.stem.rsplit("_", 1)[-1] not in config.qt.languages:
                f.unlink()
    return before - folder_size(dist)


def add_steam(config: GameConfig, dist: Path | None = None) -> bool:
    """The Steamworks DLL next to the executable, if the SDK copy is there. Never
    ``steam_appid.txt`` (development only)."""
    dist = dist or config.dist
    if config.steam_sdk_dir is None:
        return False
    dll = config.steam_sdk_dir / STEAM_DLL
    if not dll.exists():
        return False
    shutil.copy2(dll, dist / STEAM_DLL)
    return True


def smoke_test(config: GameConfig) -> bool:
    """Runs the frozen executable with its smoke arguments plus a report path; prints the report.
    A game without smoke arguments only checks that the executable exists."""
    exe = config.dist / f"{config.name}.exe"
    if not config.smoke_args:
        return exe.exists()
    report = config.build_dir / "smoke_report.txt"
    report.unlink(missing_ok=True)
    result = subprocess.run([str(exe), *config.smoke_args, str(report)], check=False)
    print(report.read_text(encoding="utf-8") if report.exists() else "(no report)")
    return result.returncode == 0 and report.exists()


def archive(config: GameConfig) -> Path:
    target = config.build_dir / f"{config.name}-{config.version()}-windows.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(config.dist.rglob("*")):
            if f.is_file():
                z.write(f, Path(config.name) / f.relative_to(config.dist))
    return target


def folder_size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def build(config: GameConfig) -> bool:
    """The whole chain; True when the smoke test passes."""
    config.build_dir.mkdir(exist_ok=True)
    print(f"{config.name} {config.version()}")
    prepare_venv(config)
    dist = freeze(config)
    saved = prune_qt(config, dist)
    if saved:
        print(f"Qt pruning: {saved / 1e6:.0f} MB removed")
    print("Steam:", "DLL added" if add_steam(config, dist) else "no DLL (bridge stays inert)")
    print(f"Build: {folder_size(dist) / 1e6:.0f} MB")
    return smoke_test(config)
