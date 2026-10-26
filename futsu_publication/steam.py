"""The Steam bridge: a thin ``ctypes`` layer over the official Steamworks C API
(``steam_api64.dll``, header ``steam_api_flat.h``), no third-party library.

It does nothing when Steam is not there: no DLL next to the game (tests, builds outside Steam),
Steam closed, or the game started outside Steam without ``steam_appid.txt``. Games never depend on
it: achievements live in ``achievements.py``, which tells it.

Function names change between SDK versions (the interface version suffix, the ``SteamAPI_InitFlat``
initialisation of recent SDKs): they are looked up by name, several candidates at once; check
them against the downloaded SDK.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

_log = logging.getLogger(__name__)
DLL = "steam_api64.dll"
USERSTATS_VERSIONS = ("v013", "v012", "v011")
"""``SteamAPI_SteamUserStats_<version>`` accessors tried, newest first."""
ERROR_MESSAGE_SIZE = 1024


def game_dir() -> Path:
    """Where the executable is (frozen build) or, in development, the working directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class SteamBridge:
    """Tells Steam about achievements and statistics; inert without Steam."""

    def __init__(self, folder: Path | None = None) -> None:
        self.active = False
        self.reason = ""
        """Why the bridge is inert (for the log)."""
        self._dll: ctypes.CDLL | None = None
        self._stats: int | None = None
        self._open(folder or game_dir())

    def _open(self, folder: Path) -> None:
        path = folder / DLL
        if not path.exists():
            self._inert(f"no {DLL} in {folder}")
            return
        try:
            dll = ctypes.CDLL(str(path))
        except OSError as e:
            self._inert(f"{DLL} unreadable: {e}")
            return
        if not self._initialise(dll):
            return
        stats = self._stats_interface(dll)
        if stats is None:
            self._inert("user stats interface not found in this SDK version")
            return
        self._dll, self._stats, self.active = dll, stats, True
        request = _function(dll, "SteamAPI_ISteamUserStats_RequestCurrentStats")
        if request is not None:  # useless since SDK 1.61, harmless before
            request.argtypes, request.restype = [ctypes.c_void_p], ctypes.c_bool
            request(stats)
        _log.info("Steam connected")

    def _initialise(self, dll: ctypes.CDLL) -> bool:
        init_flat = _function(dll, "SteamAPI_InitFlat")
        if init_flat is not None:
            message = ctypes.create_string_buffer(ERROR_MESSAGE_SIZE)
            init_flat.argtypes, init_flat.restype = [ctypes.c_char_p], ctypes.c_int
            result = init_flat(message)
            if result != 0:
                detail = message.value.decode(errors="replace")
                self._inert(f"Steam unavailable ({result}): {detail}")
                return False
            return True
        init = _function(dll, "SteamAPI_Init")
        if init is None:
            self._inert("no known initialisation function")
            return False
        init.restype = ctypes.c_bool
        if not init():
            self._inert("Steam unavailable (Steam closed, or the game started outside Steam)")
            return False
        return True

    @staticmethod
    def _stats_interface(dll: ctypes.CDLL) -> int | None:
        for version in USERSTATS_VERSIONS:
            accessor = _function(dll, f"SteamAPI_SteamUserStats_{version}")
            if accessor is not None:
                accessor.restype = ctypes.c_void_p
                interface = accessor()
                if interface:
                    return int(interface)
        return None

    def _inert(self, reason: str) -> None:
        self.reason = reason
        _log.info("Steam inert: %s", reason)

    def unlock(self, achievement: str) -> None:
        if self._call("SteamAPI_ISteamUserStats_SetAchievement", achievement.encode()):
            self._store()

    def set_stat(self, stat: str, value: int) -> None:
        if self._call("SteamAPI_ISteamUserStats_SetStatInt32", stat.encode(), ctypes.c_int32(value)):
            self._store()

    def run_callbacks(self) -> None:
        """Call regularly (once a second is enough): Steam handles its callbacks."""
        if self.active and self._dll is not None:
            callbacks = _function(self._dll, "SteamAPI_RunCallbacks")
            if callbacks is not None:
                callbacks()

    def shutdown(self) -> None:
        if self.active and self._dll is not None:
            shutdown = _function(self._dll, "SteamAPI_Shutdown")
            if shutdown is not None:
                shutdown()
        self.active = False

    def _store(self) -> None:
        self._call("SteamAPI_ISteamUserStats_StoreStats")

    def _call(self, name: str, *arguments: object) -> bool:
        if not self.active or self._dll is None or self._stats is None:
            return False
        function = _function(self._dll, name)
        if function is None:
            _log.warning("Steam: %s missing from this SDK", name)
            return False
        function.restype = ctypes.c_bool
        return bool(function(ctypes.c_void_p(self._stats), *arguments))


def _function(dll: ctypes.CDLL, name: str) -> ctypes._CFuncPtr | None:  # type: ignore[name-defined]
    try:
        return getattr(dll, name)
    except AttributeError:
        return None
