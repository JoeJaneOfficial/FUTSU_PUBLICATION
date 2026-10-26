"""The kit on its own: config, pruning, achievements, the inert Steam bridge, logs, sync."""

from pathlib import Path

import pytest

from futsu_publication import sync as sync_module
from futsu_publication.achievements import Achievements, load_definitions
from futsu_publication.build import add_steam, prune_qt
from futsu_publication.config import load_config
from futsu_publication.logs import data_dir, record_error
from futsu_publication.steam import SteamBridge

CONFIG = """
[game]
name = "Demo"
package = "demo"
version_file = "demo/version.py"
python = "3.12"
launcher = "publication/launcher.py"
lock = "publication/lock.txt"
extra_data = [["assets", "assets"]]
smoke_args = ["--verify"]

[qt]
prune = ["Qt6Quick.dll", "plugins/tls"]
languages = ["fr", "en"]

[steam]
sdk_dir = "publication/steam"
"""


def _game(tmp_path: Path) -> Path:
    (tmp_path / "publication").mkdir()
    (tmp_path / "publication" / "publication.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "version.py").write_text('VERSION = "1.2.3"\n', encoding="utf-8")
    return tmp_path


def test_config(tmp_path: Path) -> None:
    config = load_config(_game(tmp_path))
    assert config.name == "Demo" and config.version() == "1.2.3"
    assert config.extra_data == ((tmp_path.resolve() / "assets", "assets"),)
    assert config.qt.languages == ("fr", "en") and config.smoke_args == ("--verify",)
    assert config.dist == tmp_path.resolve() / "build" / "dist" / "Demo"


def test_qt_pruning_and_steam_dll(tmp_path: Path) -> None:
    config = load_config(_game(tmp_path))
    qt = config.dist / "_internal" / "PySide6"
    for name in ("Qt6Quick.dll", "Qt6Core.dll", "plugins/tls/a.dll", "translations/qt_fr.qm", "translations/qt_de.qm"):
        (qt / name).parent.mkdir(parents=True, exist_ok=True)
        (qt / name).write_bytes(b"x" * 8)
    assert prune_qt(config) > 0
    assert (qt / "Qt6Core.dll").exists() and not (qt / "Qt6Quick.dll").exists()
    assert not (qt / "plugins" / "tls").exists()
    assert sorted(f.name for f in (qt / "translations").iterdir()) == ["qt_fr.qm"]
    assert not add_steam(config), "no SDK copy, no DLL"
    sdk = tmp_path / "publication" / "steam"
    sdk.mkdir()
    (sdk / "steam_api64.dll").write_bytes(b"dll")
    assert add_steam(config) and (config.dist / "steam_api64.dll").exists()


def test_achievements(tmp_path: Path) -> None:
    definitions_path = tmp_path / "a.yaml"
    definitions_path.write_text(
        "achievements:\n  - {id: FIRST}\n  - {id: THREE, stat: COUNT, goal: 3}\n  - {id: SECRET, hidden: true}\n",
        encoding="utf-8",
    )
    definitions = load_definitions(definitions_path)
    assert definitions["SECRET"].hidden
    state = tmp_path / "state.json"
    a = Achievements(definitions, state)
    heard: list[str] = []
    a.on_unlock.append(heard.append)
    assert a.unlock("FIRST") and not a.unlock("FIRST") and not a.unlock("NOPE")
    a.set_stat("COUNT", 2)
    a.set_stat("COUNT", 1)
    assert a.stats["COUNT"] == 2 and "THREE" not in a.unlocked
    a.set_stat("COUNT", 3)
    assert heard == ["FIRST", "THREE"]
    assert Achievements(definitions, state).unlocked == {"FIRST", "THREE"}
    state.write_text("{ broken", encoding="utf-8")
    assert Achievements(definitions, state).unlocked == set()


def test_french_definitions_and_state(tmp_path: Path) -> None:
    """A French game keeps its keys (succes, cache, statistique, objectif; debloques)."""
    path = tmp_path / "succes.yaml"
    path.write_text("succes:\n  - {id: A, cache: true}\n  - {id: B, statistique: S, objectif: 2}\n", encoding="utf-8")
    definitions = load_definitions(path)
    assert definitions["A"].hidden and definitions["B"].goal == 2
    state = tmp_path / "succes.json"
    state.write_text('{"debloques": ["A"], "statistiques": {"S": 1}}', encoding="utf-8")
    a = Achievements(definitions, state)
    assert a.unlocked == {"A"} and a.stats == {"S": 1}


def test_inert_steam_bridge(tmp_path: Path) -> None:
    bridge = SteamBridge(tmp_path)
    assert not bridge.active and "steam_api64.dll" in bridge.reason
    bridge.unlock("FIRST")
    bridge.set_stat("COUNT", 1)
    bridge.run_callbacks()
    bridge.shutdown()


def test_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_DATA", str(tmp_path))
    assert data_dir("Demo", "DEMO_DATA") == tmp_path
    path = record_error(tmp_path / "logs", "Traceback\n", "1.2.3")
    record_error(tmp_path / "logs", "Traceback\n", "1.2.3")
    assert path.read_text(encoding="utf-8").count("version 1.2.3") == 2


def test_sync_and_check(tmp_path: Path) -> None:
    copy = sync_module.sync(tmp_path)
    assert (copy / "MANIFEST.json").exists() and (copy / "build.py").exists()
    assert sync_module.check(copy) == []
    (copy / "build.py").write_text("# edited by hand\n", encoding="utf-8")
    (copy / "extra.py").write_text("", encoding="utf-8")
    assert sorted(sync_module.check(copy)) == ["edited: build.py", "extra: extra.py"]
