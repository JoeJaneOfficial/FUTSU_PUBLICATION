"""The kit on its own: config, pruning, achievements, the inert Steam bridge, logs, sync,
SteamPipe, licences."""

import sys
from pathlib import Path

import pytest

from futsu_publication import licenses, steampipe
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
    (tmp_path / "publication").mkdir(parents=True)
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


STEAM = """
app_id = 480
depot_id = 481
steamcmd = "tools/steamcmd.exe"
account = "builder"
"""


def _steam_game(tmp_path: Path, extra: str = STEAM) -> Path:
    root = _game(tmp_path)
    toml = root / "publication" / "publication.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return root


def test_steam_config_defaults(tmp_path: Path) -> None:
    config = load_config(_game(tmp_path))
    assert config.steam.app_id == 0 and config.steam.branch == "beta" and config.steam.steamcmd is None


def test_steampipe_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(steampipe.ACCOUNT_ENV, raising=False)
    monkeypatch.setattr("futsu_publication.steampipe.shutil.which", lambda _: None)
    config = load_config(_game(tmp_path))
    assert any("no build" in p for p in steampipe.problems(config, dry_run=True))
    config.dist.mkdir(parents=True)
    (config.dist / "steam_appid.txt").write_text("480")
    found = steampipe.problems(config)
    assert any("steam_api64.dll" in p for p in found) and any("steam_appid" in p for p in found)
    assert any("app_id" in p for p in found) and any("account" in p for p in found)
    assert any("steamcmd" in p for p in found)


def test_steampipe_scripts_and_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(steampipe.ACCOUNT_ENV, "from_env")
    config = load_config(_steam_game(tmp_path))
    config.dist.mkdir(parents=True)
    (config.dist / "steam_api64.dll").write_bytes(b"dll")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "steamcmd.exe").write_bytes(b"")
    assert steampipe.problems(config) == []
    called: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> _Done:
        called.append(args)
        return _Done()

    monkeypatch.setattr("futsu_publication.steampipe.subprocess.run", fake_run)
    assert steampipe.upload(config, dry_run=True)
    assert called == [] or all("git" in str(c) for c in called), "a dry run never calls steamcmd"
    plan = steampipe.prepare(config)
    app = plan.app_script.read_text(encoding="utf-8")
    depot = plan.depot_script.read_text(encoding="utf-8")
    assert '"AppID"\t"480"' in app and '"SetLive"\t"beta"' in app and '"481"\t"depot_build_481.vdf"' in app
    assert '"DepotID"\t"481"' in depot and '"FileExclusion"\t"steam_appid.txt"' in depot
    assert str(config.dist).replace("\\", "\\\\") in depot
    assert plan.command[1:3] == ["+login", "from_env"] and plan.command[-1] == "+quit"


def test_steampipe_refuses_the_default_branch(tmp_path: Path) -> None:
    config = load_config(_steam_game(tmp_path, STEAM + 'branch = "default"\n'))
    assert any("beta branch" in p for p in steampipe.problems(config, dry_run=True))


class _Done:
    returncode = 0
    stdout = "abc123\n"


LICENSES = """
[licenses]
folder = "licences"
notice = "publication/NOTICE.txt"
files = ["publication/LGPL-3.0.txt", ["data/flags/LICENSE", "MIT-flags.txt"]]
exclude = ["devtool"]
drop = ["LicenseRef-Qt-*.txt"]
"""


def _licensed_game(tmp_path: Path) -> Path:
    root = _game(tmp_path)
    toml = root / "publication" / "publication.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + LICENSES, encoding="utf-8")
    (root / "publication" / "NOTICE.txt").write_text("Demo uses Qt under the LGPL.\n", encoding="utf-8")
    (root / "publication" / "LGPL-3.0.txt").write_text("GNU LESSER GENERAL PUBLIC LICENSE\n", encoding="utf-8")
    (root / "data" / "flags").mkdir(parents=True)
    (root / "data" / "flags" / "LICENSE").write_text("The MIT License\n", encoding="utf-8")
    return root


def _package(tmp_path: Path, name: str, licence: str, *files: str) -> licenses.Package:
    folder = tmp_path / "site" / f"{name}.dist-info"
    folder.mkdir(parents=True)
    for f in files:
        (folder / f).write_text(f"{name} {f}\n", encoding="utf-8")
    return licenses.Package(name, "1.0", licence, tuple(folder / f for f in files))


def _inventory(tmp_path: Path, *packages: licenses.Package) -> licenses.Inventory:
    python = tmp_path / "python-LICENSE.txt"
    python.write_text("PSF\n", encoding="utf-8")
    return licenses.Inventory("3.12.10", python, packages)


def test_licenses_config(tmp_path: Path) -> None:
    assert not load_config(_game(tmp_path / "plain")).licenses.enabled
    config = load_config(_licensed_game(tmp_path / "licensed"))
    assert config.licenses.enabled and config.licenses.folder == "licences"
    assert [name for _, name in config.licenses.files] == ["LGPL-3.0.txt", "MIT-flags.txt"]
    assert config.licenses.files[1][0] == config.root / "data" / "flags" / "LICENSE"


def test_licenses_written_with_their_index(tmp_path: Path) -> None:
    config = load_config(_licensed_game(tmp_path))
    found = _inventory(
        tmp_path,
        _package(tmp_path, "PySide6", "LGPL-3.0-only OR GPL-3.0-only", "LicenseRef-Qt-Commercial.txt"),
        _package(tmp_path, "PyYAML", "MIT", "LICENSE"),
        _package(tmp_path, "pyinstaller", "GPL", "COPYING.txt"),
        _package(tmp_path, "devtool", "", "LICENSE"),
        _package(tmp_path, "Demo", "", "LICENSE"),
    )
    dist = tmp_path / "dist"
    assert licenses.write(config, dist, found) == []
    folder = dist / "licences"
    assert (folder / "pyyaml-1.0" / "LICENSE").is_file() and (folder / "python-LICENSE.txt").is_file()
    assert not (folder / "pyside6-1.0").exists(), "the dropped Qt commercial licence is not copied"
    assert not (folder / "pyinstaller-1.0").exists() and not (folder / "devtool-1.0").exists()
    assert not (folder / "demo-1.0").exists(), "the game is not a third party"
    index = (folder / licenses.INDEX).read_text(encoding="utf-8")
    assert index.startswith("Demo uses Qt under the LGPL.")
    assert "PySide6 1.0 (LGPL-3.0-only OR GPL-3.0-only)" in index and "Python 3.12.10" in index
    assert "MIT-flags.txt" in index and (folder / "MIT-flags.txt").is_file()
    assert licenses.check(config, dist) == []
    (folder / "LGPL-3.0.txt").unlink()
    assert licenses.check(config, dist) == ["LGPL-3.0.txt missing from licences/"]


def test_licenses_refuse_an_unlicensed_package(tmp_path: Path) -> None:
    config = load_config(_licensed_game(tmp_path))
    (config.root / "data" / "flags" / "LICENSE").unlink()
    problems = licenses.write(config, tmp_path / "dist", _inventory(tmp_path, _package(tmp_path, "mystery", "")))
    assert any("mystery ships no licence" in p for p in problems)
    assert any("licence file not found" in p and "LICENSE" in p for p in problems)


def test_licenses_inventory_of_a_real_interpreter(tmp_path: Path) -> None:
    found = licenses.inventory(load_config(_game(tmp_path)), Path(sys.executable))
    assert found.python_version.startswith(f"{sys.version_info.major}.{sys.version_info.minor}")
    assert any(licenses.normalized(p.name) == "pytest" for p in found.packages)


def test_steampipe_requires_the_licences(tmp_path: Path) -> None:
    config = load_config(_licensed_game(tmp_path))
    config.dist.mkdir(parents=True)
    assert any("THIRD_PARTY.txt" in p for p in steampipe.problems(config, dry_run=True))
