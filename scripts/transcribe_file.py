#!/usr/bin/env python3
"""
Whisper File Transcriber — transcribe an audio file from the command line

Usage (command-line):
    python scripts/transcribe_file.py audio.mp3
    python scripts/transcribe_file.py audio.mp3 -l en
    python scripts/transcribe_file.py audio.mp3 -o transcript.txt
    python scripts/transcribe_file.py audio.mp3 --model large-v2

Usage (interactive — omit the audio file to be prompted for all options):
    python scripts/transcribe_file.py

Options:
    -l, --language   Language code: en or nl (default: nl)
    -o, --output     Output file path (default: <input stem>.txt next to input file)
    --model          Whisper model size: tiny/base/small/medium/large-v2 (default: small)
    --cpu            Force CPU even if CUDA is available
"""

import argparse
import sys
from pathlib import Path

from faster_whisper import WhisperModel

# ── Colours ─────────────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    _k32 = ctypes.windll.kernel32
    _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)

_R   = "\033[0m"
_DIM = "\033[2m"
_B   = "\033[1m"
_CY  = "\033[96m"  # bright cyan
_GR  = "\033[92m"  # bright green
_OR  = "\033[33m"  # amber
_RD  = "\033[91m"  # bright red
_WH  = "\033[97m"  # bright white

# ── Data ────────────────────────────────────────────────────────────────────────
MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]

LANG_ALIASES = {
    "en": "en", "english": "en",
    "nl": "nl", "du": "nl", "dutch": "nl", "nederlands": "nl",
    "ar": "ar", "zh": "zh", "cs": "cs", "da": "da", "fi": "fi",
    "fr": "fr", "de": "de", "el": "el", "he": "he", "hi": "hi",
    "hu": "hu", "id": "id", "it": "it", "ja": "ja", "ko": "ko",
    "no": "no", "pl": "pl", "pt": "pt", "ro": "ro", "ru": "ru",
    "es": "es", "sv": "sv", "th": "th", "tr": "tr", "uk": "uk",
    "vi": "vi",
}

OTHER_LANGUAGES = [
    ("Arabic",     "ar"), ("Chinese",    "zh"), ("Czech",      "cs"),
    ("Danish",     "da"), ("Finnish",    "fi"), ("French",     "fr"),
    ("German",     "de"), ("Greek",      "el"), ("Hebrew",     "he"),
    ("Hindi",      "hi"), ("Hungarian",  "hu"), ("Indonesian", "id"),
    ("Italian",    "it"), ("Japanese",   "ja"), ("Korean",     "ko"),
    ("Norwegian",  "no"), ("Polish",     "pl"), ("Portuguese", "pt"),
    ("Romanian",   "ro"), ("Russian",    "ru"), ("Spanish",    "es"),
    ("Swedish",    "sv"), ("Thai",       "th"), ("Turkish",    "tr"),
    ("Ukrainian",  "uk"), ("Vietnamese", "vi"),
]

# ── Interactive prompts ──────────────────────────────────────────────────────────
def prompt_audio() -> Path:
    while True:
        raw = input(f"{_CY}Audio file:{_R} ").strip().strip('"')
        if not raw:
            print(f"{_OR}Enter a file path.{_R}")
            continue
        path = Path(raw).resolve()
        if path.exists():
            return path
        print(f"{_OR}File not found: {path}{_R}")


def _select_other_language() -> str:
    print(f"\n{_CY}Available languages:{_R}")
    for i, (name, code) in enumerate(OTHER_LANGUAGES):
        print(f"  {_DIM}[{i:2}]{_R} {name} {_DIM}({code}){_R}")
    print()
    while True:
        raw = input(f"{_CY}Select language{_R} [0-{len(OTHER_LANGUAGES) - 1}]: ").strip()
        try:
            choice = int(raw)
            if 0 <= choice < len(OTHER_LANGUAGES):
                return OTHER_LANGUAGES[choice][1]
        except ValueError:
            pass
        print(f"{_OR}Enter a number from the list.{_R}")


def prompt_language() -> str:
    while True:
        ch = input(f"{_CY}Language?{_R} [E]nglish / [D]utch / [O]ther (Enter = Dutch): ").strip().lower()
        if ch in ("", "d", "nl", "dutch", "nederlands"):
            return "nl"
        if ch in ("e", "en", "english"):
            return "en"
        if ch in ("o", "other"):
            return _select_other_language()
        print(f"{_OR}Enter E, D, or O.{_R}")


def prompt_model() -> str:
    print(f"{_CY}Whisper model{_R} (fastest → most accurate):")
    for i, m in enumerate(MODELS):
        marker = f"  {_DIM}* (default){_R}" if m == "small" else ""
        print(f"  {_DIM}[{i}]{_R} {m}{marker}")
    print()
    while True:
        raw = input(f"{_CY}Select model{_R} [0-{len(MODELS) - 1}] (Enter = small): ").strip()
        if raw == "":
            return "small"
        try:
            choice = int(raw)
            if 0 <= choice < len(MODELS):
                return MODELS[choice]
        except ValueError:
            pass
        print(f"{_OR}Enter a number from the list.{_R}")


def prompt_output(audio_path: Path) -> Path:
    default = audio_path.with_suffix(".txt")
    raw = input(f"{_CY}Output file{_R} (Enter = {_DIM}{default.name}{_R}): ").strip().strip('"')
    if not raw:
        return default
    p = Path(raw)
    return p.resolve() if p.is_absolute() else (audio_path.parent / p).resolve()


# ── Core ────────────────────────────────────────────────────────────────────────
def load_model(model_size: str, force_cpu: bool) -> WhisperModel:
    print(f"{_CY}Loading Whisper '{model_size}' model...{_R}", file=sys.stderr)
    if not force_cpu:
        try:
            model = WhisperModel(model_size, device="cuda", compute_type="float16")
            print(f"{_GR}Loaded on GPU (CUDA).{_R}", file=sys.stderr)
            return model
        except Exception:
            pass
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print(f"{_OR}Loaded on CPU.{_R}", file=sys.stderr)
    return model


def transcribe(audio_path: Path, model: WhisperModel, lang: str) -> str:
    print(f"{_CY}Transcribing {_WH}{audio_path.name}{_CY} ...{_R}", file=sys.stderr)
    segments, info = model.transcribe(str(audio_path), language=lang)
    detected = info.language if lang is None else lang
    print(f"{_DIM}Language : {detected}  |  Duration: {info.duration:.1f}s{_R}", file=sys.stderr)
    return " ".join(s.text.strip() for s in segments).strip()


# ── Entry ────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe an audio file with Whisper.")
    parser.add_argument("audio", type=Path, nargs="?", default=None,
                        help="Audio file to transcribe (omit to be prompted interactively)")
    parser.add_argument("-l", "--language", default=None,
                        help="Language code, e.g. en or nl (default: nl)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .txt file (default: <audio stem>.txt beside input)")
    parser.add_argument("--model", default=None,
                        help="Whisper model size (default: small)")
    parser.add_argument("--cpu", action="store_true",
                        help="Force CPU inference")
    args = parser.parse_args()

    if args.audio is None:
        # ── Interactive mode ──────────────────────────────────────────────────
        print(f"\n{_B}{_CY}=== Whisper File Transcriber ==={_R}\n")
        audio_path = prompt_audio()
        print()
        lang_code  = prompt_language()
        print()
        model_name = prompt_model()
        print()
        output_path = prompt_output(audio_path)
        print()
        force_cpu = False
    else:
        # ── Command-line mode ─────────────────────────────────────────────────
        audio_path = args.audio.resolve()
        if not audio_path.exists():
            print(f"{_RD}Error: file not found: {audio_path}{_R}", file=sys.stderr)
            sys.exit(1)

        lang_input = args.language or "nl"
        lang_code = LANG_ALIASES.get(lang_input.lower())
        if lang_code is None:
            print(f"{_RD}Error: unknown language '{lang_input}'.{_R}", file=sys.stderr)
            sys.exit(1)

        model_name  = args.model or "small"
        output_path = args.output.resolve() if args.output else audio_path.with_suffix(".txt")
        force_cpu   = args.cpu

    model = load_model(model_name, force_cpu)
    text  = transcribe(audio_path, model, lang_code)

    if not text:
        print(f"{_OR}No speech detected.{_R}", file=sys.stderr)
        sys.exit(0)

    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"{_GR}Saved : {_WH}{output_path}{_R}", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
