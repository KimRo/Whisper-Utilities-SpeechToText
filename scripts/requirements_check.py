#!/usr/bin/env python3
"""
Requirements check — which packages do the tools need, and which are missing?

Used by every tool in this folder: the command-line scripts stop at once with a clear message
instead of a Python traceback, the meeting recorder window greys out what cannot work, and
the installer runs this file at the end to confirm that everything is in place.

Usage:
    python scripts/requirements_check.py        # print what is installed and what is missing

Exit code: 0 when all packages are installed (a missing Hugging Face token is only a note),
1 when a package is missing.

The check only looks whether a package exists (importlib.util.find_spec); it does not import
it, so it is fast and never loads torch. A package that is present but broken is not detected.
"""

from __future__ import annotations

import importlib.util
import os
import sys

# feature -> [(name shown to the user, importable module, pip requirement or None)]
# None = not installed with a plain pip command (PyTorch needs the right CUDA build: install.bat)
FEATURES: dict[str, list[tuple[str, str, str | None]]] = {
    "record": [("PyAudioWPatch", "pyaudiowpatch", "PyAudioWPatch"),
               ("PyAV", "av", "av<19"),
               ("NumPy", "numpy", "numpy")],
    "transcribe": [("faster-whisper", "faster_whisper", "faster-whisper"),
                   ("PyAV", "av", "av<19"),
                   ("NumPy", "numpy", "numpy")],
    "speakers": [("pyannote.audio", "pyannote.audio", "pyannote.audio==4.1.1"),
                 ("PyTorch", "torch", None)],
    "live": [("NumPy", "numpy", "numpy"),
             ("sounddevice", "sounddevice", "sounddevice"),
             ("soundfile", "soundfile", "soundfile"),
             ("pynput", "pynput", "pynput")],
    "tray": [("Pillow", "PIL", "pillow"),
             ("pystray", "pystray", "pystray")],
}
TITLES = {
    "record": "Recording unavailable",
    "transcribe": "Transcription unavailable",
    "speakers": "'With speakers' unavailable",
    "live": "Live push-to-talk unavailable",
    "tray": "Tray icon unavailable",
}
LABELS = {
    "record": "Recording (meeting recorder)",
    "transcribe": "Transcription (transcribe_file.py)",
    "speakers": "With speakers (transcribe_speakers.py)",
    "live": "Live push-to-talk (transcribe_tts.py)",
    "tray": "Tray icon (recorder window)",
}
HF_TOKEN_MISSING = "Hugging Face token (set HF_TOKEN)"
INSTALLER = "scripts\\install.bat"


def module_available(name: str) -> bool:
    """True when the module is installed (looked up without importing it)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def has_hf_token() -> bool:
    """A Hugging Face token in the environment or saved by `huggingface-cli login`."""
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
        return bool(get_token())
    except Exception:  # noqa: BLE001 - huggingface_hub missing or unreadable: no token
        return False


def is_interactive() -> bool:
    """True when a person can answer a prompt: stdin is a real console or terminal.

    sys.stdin.isatty() is not enough on Windows: the NUL device (what a background process
    started by the recorder window gets) also reports True, so a prompt would wait forever.
    """
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return False
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetStdHandle.restype = ctypes.c_void_p
            handle = ctypes.c_void_p(kernel32.GetStdHandle(-10))          # STD_INPUT_HANDLE
            return bool(kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_uint32())))
        return True
    except (OSError, ValueError, AttributeError):
        return False


def check(*features: str, token: bool = False) -> dict[str, list[str]]:
    """Return {feature: [names of the missing packages]} for the requested features.

    token=True also requires a Hugging Face token (needed by the speaker model); it is listed
    under "speakers" when missing.
    """
    missing = {f: [name for name, mod, _ in FEATURES[f] if not module_available(mod)]
               for f in features}
    if token and "speakers" in missing and not has_hf_token():
        missing["speakers"].append(HF_TOKEN_MISSING)
    return missing


def _pip_spec(name: str) -> str | None:
    for items in FEATURES.values():
        for n, _, spec in items:
            if n == name:
                return spec
    return None


def fix_hint(missing: dict[str, list[str]], pip: bool = True) -> list[str]:
    """Lines that say how to install what is missing (pip=False: just point at the installer)."""
    names = [n for items in missing.values() for n in items]
    lines = []
    specs = []
    for n in dict.fromkeys(names):                      # unique, in order
        if n == HF_TOKEN_MISSING:
            continue
        spec = _pip_spec(n)
        if spec is None and n == "PyTorch":
            lines.append(f"PyTorch: use {INSTALLER}, which picks the build for your GPU.")
        elif spec:
            specs.append(f'"{spec}"' if any(c in spec for c in "<>= ") else spec)
    if specs:
        text = f"Run {INSTALLER} to install the missing packages"
        lines.insert(0, f"{text}, or: python -m pip install {' '.join(specs)}" if pip else f"{text}.")
    if HF_TOKEN_MISSING in names:
        lines.append("Hugging Face token: set HF_TOKEN or run `huggingface-cli login` "
                     "(see doc/transcribe_speakers.md).")
    return lines


def missing_report(missing: dict[str, list[str]], pip: bool = True) -> str:
    """Multi-line text for the recorder window's Status box (pip=False: shorter hint)."""
    lines = [f"{TITLES[f]}: missing {', '.join(names)}" for f, names in missing.items() if names]
    if lines:
        lines += fix_hint(missing, pip)
    return "\n".join(lines)


def require(*features: str, token: bool = False, tool: str | None = None) -> None:
    """Command-line tools: exit with a clear message if something they need is missing."""
    missing = check(*features, token=token)
    names = [n for items in missing.values() for n in dict.fromkeys(items)]
    if not names:
        return
    names = list(dict.fromkeys(names))
    who = tool or os.path.basename(sys.argv[0]) or "this tool"
    red, reset = ("\033[91m", "\033[0m") if sys.stderr and sys.stderr.isatty() else ("", "")
    if sys.stderr is not None:
        print(f"{red}Error: {who} cannot run, missing: {', '.join(names)}.{reset}", file=sys.stderr)
        for line in fix_hint(missing):
            print(line, file=sys.stderr)
    sys.exit(1)


def main() -> int:
    print("Checking what is installed ...\n")
    missing = check(*FEATURES, token=True)
    problems = 0
    for feature, names in missing.items():
        packages = [n for n in names if n != HF_TOKEN_MISSING]
        if not names:
            status = "OK"
        else:
            status = "MISSING: " + ", ".join(names)
        problems += bool(packages)
        print(f"  {LABELS[feature]:<42} {status}")
    hints = fix_hint(missing)
    if hints:
        print()
        for line in hints:
            print(line)
    print("\nAll packages are installed." if not problems else
          "\nSome packages are missing (see above).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
