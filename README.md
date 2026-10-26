# Futsu publication kit

Reproducible standalone builds, logs, achievements and the Steam bridge, shared by the Futsu games
(Dirty Peloton, The Greater Evil). This repository is the single source; each game keeps a synced
copy (`futsu_publication/` at its root, with a `MANIFEST.json`).

| Module | Role |
|---|---|
| `config.py` | the game's `publication/publication.toml` |
| `build.py` / `__main__.py` | clean venv from a lock file, PyInstaller (one folder), Qt pruning, Steam DLL, smoke test, zip |
| `logs.py` | `game.log` (rotating), `errors.log`, `crashes.log` in the player's data folder |
| `achievements.py` | definitions (YAML), unlocks, progress stats, atomic state, outputs |
| `steam.py` | `ctypes` bridge over `steam_api64.dll`; inert without Steam |
| `sync.py` | copy the kit into a game (`python -m futsu_publication.sync <game root>`), check a copy (`check`) |

From a game root: `python -m futsu_publication build | smoke | archive`.

Change the kit here, run its tests (`python -m pytest`), bump `__version__`, then sync each game.
