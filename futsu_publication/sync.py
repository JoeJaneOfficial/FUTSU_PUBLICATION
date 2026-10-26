"""Keeping each game's copy of the kit in step with this repository (the single source).

``python -m futsu_publication.sync <game root>`` (from the kit repository) copies the package into
``<game root>/futsu_publication`` with a ``MANIFEST.json`` (kit version, source commit, a SHA-256
per file). ``check`` (from a game, or its tests) verifies that the copy was not edited by hand:
changes belong in the kit repository, then a new sync.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from futsu_publication import __version__

PACKAGE = Path(__file__).resolve().parent
MANIFEST = "MANIFEST.json"


def _files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.rglob("*.py") if "__pycache__" not in f.parts and f.name != MANIFEST)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PACKAGE, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def sync(game_root: Path) -> Path:
    """Replaces the game's copy with this package; returns the copy's folder."""
    target = game_root.resolve() / PACKAGE.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    hashes = {}
    for f in _files(PACKAGE):
        relative = f.relative_to(PACKAGE)
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target / relative)
        hashes[relative.as_posix()] = _digest(f)
    manifest = {"version": __version__, "commit": _commit(), "files": hashes}
    (target / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="
")
    return target


def check(copy: Path = PACKAGE) -> list[str]:
    """Problems with a copy (edited, missing or extra files); empty when it matches its manifest.
    The kit repository itself has no manifest: nothing to check."""
    manifest_path = copy / MANIFEST
    if not manifest_path.exists():
        return []
    expected: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    found = {f.relative_to(copy).as_posix(): _digest(f) for f in _files(copy)}
    problems = [f"edited: {name}" for name, h in expected.items() if name in found and found[name] != h]
    problems += [f"missing: {name}" for name in expected if name not in found]
    problems += [f"extra: {name}" for name in found if name not in expected]
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "check":
        problems = check()
        print("\n".join(problems) or "copy in step with its manifest")
        return 1 if problems else 0
    if len(args) != 1:
        print("usage: python -m futsu_publication.sync <game root> | check")
        return 2
    print(f"synced into {sync(Path(args[0]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
