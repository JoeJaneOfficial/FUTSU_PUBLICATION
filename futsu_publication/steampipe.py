"""Uploading a build to Steam with SteamPipe (``steamcmd`` and two VDF build scripts).

The flow: the usual build (``build.py``, smoke test included), checks that the folder is fit for
Steam, two scripts written into ``build/steam/`` (the app build and its Windows depot), then
``steamcmd +login <account> +run_app_build <script> +quit``. The build goes live on a **beta
branch** only; making it public stays a manual click in Steamworks (Steam refuses ``default``
from a script anyway).

The password is never stored: ``steamcmd`` asks for it (and the Steam Guard code) the first time,
then keeps its own login token. Run the upload from a terminal where you can type.

``--dry-run`` writes the scripts and prints the command without running ``steamcmd``: it works
before the Steamworks account exists, with placeholder IDs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from futsu_publication import licenses
from futsu_publication.build import STEAM_DLL
from futsu_publication.config import GameConfig

ACCOUNT_ENV = "FUTSU_STEAM_ACCOUNT"
"""Overrides ``[steam] account`` (keeps a personal login out of the repository)."""
EXCLUDED = ("steam_appid.txt", "*.pdb")
"""Never uploaded: ``steam_appid.txt`` is for development only."""
FORBIDDEN_BRANCHES = ("", "default", "public")


@dataclass(frozen=True)
class UploadPlan:
    app_script: Path
    depot_script: Path
    command: list[str]


def problems(config: GameConfig, dry_run: bool = False) -> list[str]:
    """Why the upload cannot go ahead; empty when it can. A dry run only needs the build."""
    steam = config.steam
    found: list[str] = []
    if not config.dist.is_dir():
        found.append(f"no build in {config.dist} (run the build first)")
    else:
        if not (config.dist / STEAM_DLL).exists():
            found.append(f"no {STEAM_DLL} in the build: put it in {config.steam_sdk_dir} and rebuild")
        if (config.dist / "steam_appid.txt").exists():
            found.append("steam_appid.txt is in the build (development only)")
        if config.licenses.enabled:
            found += licenses.check(config)
    if steam.branch in FORBIDDEN_BRANCHES:
        found.append(f"branch {steam.branch!r}: upload to a beta branch, go public by hand in Steamworks")
    if dry_run:
        return found
    if steam.app_id <= 0 or steam.depot_id <= 0:
        found.append("[steam] app_id and depot_id are not set (Steamworks, App Admin)")
    if not account(config):
        found.append(f"no build account: [steam] account, or the {ACCOUNT_ENV} variable")
    if steamcmd(config) is None:
        found.append(f"steamcmd not found ({config.steam.steamcmd or 'not configured'}, nor on PATH)")
    return found


def account(config: GameConfig) -> str:
    return os.environ.get(ACCOUNT_ENV, "").strip() or config.steam.account


def steamcmd(config: GameConfig) -> Path | None:
    configured = config.steam.steamcmd
    if configured is not None and configured.exists():
        return configured
    on_path = shutil.which("steamcmd")
    return Path(on_path) if on_path else None


def _quote(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _block(name: str, entries: list[tuple[str, object]], indent: int = 0) -> str:
    pad = "\t" * indent
    lines = [f"{pad}{_quote(name)}", f"{pad}{{"]
    for key, value in entries:
        if isinstance(value, list):
            lines.append(_block(key, value, indent + 1))
        else:
            lines.append(f"{pad}\t{_quote(key)}\t{_quote(value)}")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def depot_script(config: GameConfig) -> str:
    entries: list[tuple[str, object]] = [
        ("DepotID", config.steam.depot_id),
        ("ContentRoot", config.dist),
        ("FileMapping", [("LocalPath", "*"), ("DepotPath", "."), ("recursive", 1)]),
    ]
    entries += [("FileExclusion", pattern) for pattern in EXCLUDED]
    return _block("DepotBuild", entries) + "\n"


def app_script(config: GameConfig, description: str) -> str:
    out = config.build_dir / "steam" / "output"
    return (
        _block(
            "AppBuild",
            [
                ("AppID", config.steam.app_id),
                ("Desc", description),
                ("BuildOutput", out),
                ("SetLive", config.steam.branch),
                ("Depots", [(str(config.steam.depot_id), _depot_name(config))]),
            ],
        )
        + "\n"
    )


def _depot_name(config: GameConfig) -> str:
    return f"depot_build_{config.steam.depot_id}.vdf"


def description(config: GameConfig) -> str:
    """``<name> <version> (<commit>)``: what Steamworks shows in the build list."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=config.root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return f"{config.name} {config.version()} ({commit})"


def prepare(config: GameConfig) -> UploadPlan:
    """Writes both scripts into ``build/steam/`` and returns the steamcmd command."""
    folder = config.build_dir / "steam"
    (folder / "output").mkdir(parents=True, exist_ok=True)
    depot = folder / _depot_name(config)
    app = folder / f"app_build_{config.steam.app_id}.vdf"
    depot.write_text(depot_script(config), encoding="utf-8", newline="\n")
    app.write_text(app_script(config, description(config)), encoding="utf-8", newline="\n")
    exe = steamcmd(config)
    command = [
        str(exe) if exe else "steamcmd",
        "+login",
        account(config) or "<account>",
        "+run_app_build",
        str(app),
        "+quit",
    ]
    return UploadPlan(app, depot, command)


def upload(config: GameConfig, dry_run: bool = False) -> bool:
    """Checks, writes the scripts, then runs steamcmd (attached to the terminal for the password
    and Steam Guard). True when everything went through (or, dry, when the scripts are ready)."""
    found = problems(config, dry_run)
    for problem in found:
        print("  !", problem)
    if found:
        return False
    plan = prepare(config)
    print(f"Scripts: {plan.app_script}")
    print("  $", " ".join(plan.command))
    if dry_run:
        print(f"Dry run: nothing sent (branch {config.steam.branch!r} once real).")
        return True
    result = subprocess.run(plan.command, check=False)
    if result.returncode == 0:
        print(f"Uploaded; live on the {config.steam.branch!r} branch. Go public by hand in Steamworks.")
    return result.returncode == 0
