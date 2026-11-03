"""``python -m futsu_publication <command>`` from a game repository root.

build    clean venv, PyInstaller, pruning, Steam DLL, smoke test
smoke    re-run the smoke test of the last build
archive  zip the last build (testers outside Steam)
steam    build, then upload to Steam with SteamPipe (--no-build: the last build; --dry-run: scripts only)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from futsu_publication import build as b
from futsu_publication import steampipe
from futsu_publication.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="futsu_publication", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("build", "smoke", "archive", "steam"))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="game repository root")
    parser.add_argument("--config", type=Path, default=None, help="publication.toml path")
    parser.add_argument("--no-build", action="store_true", help="steam: upload the last build as is")
    parser.add_argument("--dry-run", action="store_true", help="steam: write the scripts, send nothing")
    args = parser.parse_args(argv)
    config = load_config(args.root, args.config)
    if args.command == "build":
        return 0 if b.build(config) else 1
    if args.command == "smoke":
        return 0 if b.smoke_test(config) else 1
    if args.command == "steam":
        if not args.no_build and not b.build(config):
            print("Build or smoke test failed: nothing sent.")
            return 1
        return 0 if steampipe.upload(config, args.dry_run) else 1
    print(b.archive(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
