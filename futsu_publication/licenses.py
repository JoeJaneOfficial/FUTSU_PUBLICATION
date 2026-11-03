"""Third-party licence texts shipped next to the executable, in ``<dist>/<folder>/``.

What a game owes the libraries it bundles: their licence texts, readable by the player without
digging into ``_internal``. At every build the kit gathers:

- the licence of Python itself (the interpreter is frozen into the build);
- the licence files of every package installed in the build venv, except the build tools and
  the game itself (``dist-info/licenses``, ``LICENSE``, ``COPYING``, ``NOTICE``, ``AUTHORS``);
- the files the game lists in ``[licenses] files`` (fonts, art, data, and the texts a package
  does not ship: PySide6 only ships Qt's commercial licence, not the LGPL it is used under);
- an index, ``THIRD_PARTY.txt``, starting with the game's own notice (``[licenses] notice``).

The build fails when a runtime package ships no licence file and declares no licence: a
dependency added without its licence never reaches a release unnoticed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from futsu_publication.config import GameConfig

INDEX = "THIRD_PARTY.txt"
BUILD_ONLY = (
    "pip",
    "setuptools",
    "wheel",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "packaging",
    "pefile",
    "pywin32-ctypes",
)
"""Used to build, never bundled: their licences do not apply to the shipped game."""

_PROBE = r"""
import importlib.metadata as m, json, re, sys
from pathlib import Path
names = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)
packages = []
for d in m.distributions():
    meta = d.metadata
    licence = meta.get("License-Expression") or (meta.get("License") or "").strip().splitlines()
    if isinstance(licence, list):
        licence = licence[0] if licence else ""
    if not licence:
        licence = "; ".join(c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::"))
    files = [str(d.locate_file(f)) for f in d.files or [] if names.search(Path(str(f)).name)]
    packages.append({"name": meta["Name"], "version": d.version, "licence": licence[:120], "files": files})
python = Path(sys.base_prefix) / "LICENSE.txt"
print(json.dumps({"python": sys.version.split()[0], "python_licence": str(python), "packages": packages}))
"""


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    licence: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class Inventory:
    python_version: str
    python_licence: Path
    packages: tuple[Package, ...]


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def inventory(config: GameConfig, python: Path) -> Inventory:
    """What the build venv holds (run with the venv's interpreter, after the game is installed)."""
    result = subprocess.run([str(python), "-c", _PROBE], capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout)
    return Inventory(
        python_version=str(raw["python"]),
        python_licence=Path(raw["python_licence"]),
        packages=tuple(
            Package(p["name"], p["version"], p["licence"], tuple(Path(f) for f in p["files"])) for p in raw["packages"]
        ),
    )


def runtime_packages(config: GameConfig, found: Inventory) -> list[Package]:
    """The bundled packages: everything but the build tools, the excluded and the game itself."""
    skipped = {normalized(n) for n in (*BUILD_ONLY, *config.licenses.exclude, config.package)}
    return sorted((p for p in found.packages if normalized(p.name) not in skipped), key=lambda p: normalized(p.name))


def _kept(config: GameConfig, files: tuple[Path, ...]) -> list[Path]:
    return [f for f in files if f.is_file() and not any(fnmatch(f.name, pattern) for pattern in config.licenses.drop)]


def write(config: GameConfig, dist: Path, found: Inventory) -> list[str]:
    """Fills ``<dist>/<folder>/``; returns the problems (empty when everything is there)."""
    target = dist / config.licenses.folder
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    problems: list[str] = []
    lines: list[str] = []
    if config.licenses.notice is not None:
        if config.licenses.notice.is_file():
            lines += [config.licenses.notice.read_text(encoding="utf-8").rstrip(), ""]
        else:
            problems.append(f"notice not found: {config.licenses.notice}")
    lines += ["=" * 72, "Components", "=" * 72, ""]

    if found.python_licence.is_file():
        shutil.copy2(found.python_licence, target / "python-LICENSE.txt")
        lines += [f"Python {found.python_version} (PSF License)", "    python-LICENSE.txt", ""]
    else:
        problems.append(f"Python licence not found: {found.python_licence}")

    for package in runtime_packages(config, found):
        folder = f"{normalized(package.name)}-{package.version}"
        kept = _kept(config, package.files)
        if not kept and not package.licence:
            problems.append(f"{package.name} ships no licence file and declares no licence: add it to [licenses] files")
        lines.append(f"{package.name} {package.version} ({package.licence or 'see files'})")
        for f in kept:
            (target / folder).mkdir(exist_ok=True)
            destination = target / folder / f.name
            if destination.exists():
                destination = target / folder / f"{f.parent.name}-{f.name}"
            shutil.copy2(f, destination)
            lines.append(f"    {folder}/{destination.name}")
        lines.append("")

    lines += ["=" * 72, "Other texts", "=" * 72, ""]
    for source, name in config.licenses.files:
        if not source.is_file():
            problems.append(f"licence file not found: {source}")
            continue
        if (target / name).exists():
            problems.append(f"two licence files named {name}: rename one in [licenses] files")
            continue
        shutil.copy2(source, target / name)
        lines.append(f"    {name}")
    (target / INDEX).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return problems


def check(config: GameConfig, dist: Path | None = None) -> list[str]:
    """The licence folder of a finished build: present, with its index and every listed text."""
    folder = (dist or config.dist) / config.licenses.folder
    if not (folder / INDEX).is_file():
        return [f"no {config.licenses.folder}/{INDEX} in the build (rebuild)"]
    missing = [name for _, name in config.licenses.files if not (folder / name).is_file()]
    return [f"{name} missing from {config.licenses.folder}/" for name in missing]
