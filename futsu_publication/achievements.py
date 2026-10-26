"""Achievements: the game alone knows what is unlocked; Steam is only an output.

Definitions come from a YAML file (``achievements:`` or a French game's ``succes:`` list of
``{id, cache|hidden, statistique|stat, objectif|goal}``); the state (unlocked achievements,
progress statistics) lives in the player's data folder, outside any save (an achievement belongs
to the player, not to one playthrough). Outputs (the Steam bridge) are told about every unlock and
can catch up at start-up with what was unlocked offline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AchievementDefinition:
    id: str
    """Same as the Steamworks « API Name »."""
    hidden: bool = False
    stat: str | None = None
    """The statistic that makes it progress (« 3 grand tours out of 6 »)."""
    goal: int = 0
    """The statistic value that unlocks it."""


def load_definitions(path: Path) -> dict[str, AchievementDefinition]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("achievements") or raw.get("succes") or ()
    definitions: dict[str, AchievementDefinition] = {}
    for e in entries:
        d = AchievementDefinition(
            str(e["id"]),
            bool(e.get("hidden", e.get("cache", False))),
            e.get("stat", e.get("statistique")),
            int(e.get("goal", e.get("objectif", 0))),
        )
        if d.id in definitions:
            raise ValueError(f"{path.name}: {d.id} defined twice")
        if (d.stat is None) != (d.goal == 0):
            raise ValueError(f"{path.name}: {d.id}, stat and goal go together")
        definitions[d.id] = d
    return definitions


class Achievements:
    """Unlock, progress, tell the outputs."""

    def __init__(self, definitions: Mapping[str, AchievementDefinition], state_path: Path) -> None:
        self.definitions = dict(definitions)
        self._path = state_path
        self.unlocked: set[str] = set()
        self.stats: dict[str, int] = {}
        self.on_unlock: list[Callable[[str], None]] = []
        self.on_stat: list[Callable[[str, int], None]] = []
        self._read()

    def unlock(self, achievement: str) -> bool:
        """True when newly unlocked. An unknown id is a programming error: logged, never fatal."""
        if achievement not in self.definitions:
            _log.error("Unknown achievement: %s", achievement)
            return False
        if achievement in self.unlocked:
            return False
        self.unlocked.add(achievement)
        self._write()
        _log.info("Achievement unlocked: %s", achievement)
        for listener in list(self.on_unlock):
            listener(achievement)
        return True

    def set_stat(self, stat: str, value: int) -> None:
        """The statistic reaches ``value`` (never goes down); unlocks what it completes."""
        if value <= self.stats.get(stat, 0):
            return
        self.stats[stat] = value
        self._write()
        for listener in list(self.on_stat):
            listener(stat, value)
        for d in self.definitions.values():
            if d.stat == stat and value >= d.goal:
                self.unlock(d.id)

    def catch_up(self) -> None:
        """At start-up: give the outputs everything already earned (offline, or before Steam)."""
        for stat, value in sorted(self.stats.items()):
            for on_stat in list(self.on_stat):
                on_stat(stat, value)
        for achievement in sorted(self.unlocked):
            for on_unlock in list(self.on_unlock):
                on_unlock(achievement)

    def _read(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _log.exception("Unreadable achievements state: %s (starting over)", self._path)
            return
        unlocked = raw.get("unlocked", raw.get("debloques", ()))
        stats = raw.get("stats", raw.get("statistiques")) or {}
        self.unlocked = {x for x in unlocked if x in self.definitions}
        self.stats = {str(k): int(v) for k, v in stats.items()}

    def _write(self) -> None:
        """Atomic write: a temporary file, then a replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        data = {"unlocked": sorted(self.unlocked), "stats": self.stats}
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self._path)
