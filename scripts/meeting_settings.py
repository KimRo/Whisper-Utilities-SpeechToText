"""
Persistent settings shared by record_meeting_gui.py and record_meeting.py

Stored as JSON in %APPDATA%\\WhisperMeetingRecorder\\settings.json (or the file given with
--settings). Only the choices the user made are stored; a missing key means "use the default".
Command-line options always win over the stored value for that run and are never written back
(see resolve). The GUI saves a setting as soon as it is changed in the window.

Keys (all optional):
    mic, system      "default", "off" or a device name
    duck, separate_channels, transcribe        true / false
    mode             "normal" | "speakers"
    language         e.g. "nl"
    model            Whisper model size
    format           "mp3" | "wav"
    chunk_minutes    0 = off, else 1..60
    output_root      the one output folder (one subfolder per meeting inside it)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def documents_dir() -> Path:
    """The user's Documents folder as Windows knows it (it may be redirected, e.g. to OneDrive);
    falls back to ~/Documents."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                            ("d", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                       (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None,
                                                          ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:  # noqa: BLE001 - any failure: use the fallback
            pass
    return Path.home() / "Documents"


# One output folder; every meeting gets its own subfolder in it (<timestamp>_<name>) that holds
# the recording, the transcript and the log file.
DEFAULT_ROOT = documents_dir() / "Meeting Recorder"

DEFAULT_PATH = (Path(os.environ.get("APPDATA") or Path.home()) /
                "WhisperMeetingRecorder" / "settings.json")

# key -> validator; a stored value that fails it is ignored
_BOOL = lambda v: isinstance(v, bool)                                     # noqa: E731
_STR = lambda v: isinstance(v, str) and v.strip() != ""                   # noqa: E731
KEYS = {
    "mic": _STR, "system": _STR,
    "duck": _BOOL, "separate_channels": _BOOL, "transcribe": _BOOL,
    "mode": lambda v: v in ("normal", "speakers"),
    "language": _STR, "model": _STR,
    "format": lambda v: v in ("mp3", "wav"),
    "chunk_minutes": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 60,
    "output_root": _STR,
}


def load(path: Path | None = None) -> dict:
    """The stored settings; unknown keys and invalid values are dropped. A missing or
    unreadable file gives {} (settings must never stop the program from starting)."""
    try:
        data = json.loads((path or DEFAULT_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in KEYS and KEYS[k](v)}


def save_key(key: str, value, path: Path | None = None) -> bool:
    """Store one setting (value None removes it). Re-reads the file first so that other keys,
    possibly changed by another running program, are kept. Returns False when it could not be
    written."""
    if key not in KEYS or (value is not None and not KEYS[key](value)):
        return False
    path = path or DEFAULT_PATH
    data = load(path)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)               # atomic: never a half-written file
        return True
    except OSError:
        return False


def output_root(settings_path: Path | None = None) -> Path:
    """The output folder: the saved one, else the default (Documents\\Meeting Recorder)."""
    return Path(load(settings_path).get("output_root") or DEFAULT_ROOT)


def resolve(key: str, cli_value, stored: dict, default):
    """Priority: command line, then stored setting, then built-in default."""
    if cli_value is not None:
        return cli_value
    return stored.get(key, default)


def match_name(spec: str, names: list[str]) -> str | None:
    """The device name that spec refers to: an exact match (any case), else the only name that
    contains spec. None when nothing, or more than one name, matches."""
    low = spec.strip().lower()
    for n in names:
        if n.lower() == low:
            return n
    hits = [n for n in names if low in n.lower()]
    return hits[0] if len(hits) == 1 else None
