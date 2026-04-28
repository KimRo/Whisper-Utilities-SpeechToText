#!/usr/bin/env python3
"""
Whisper Live Transcriber — push-to-talk speech-to-text

Install (run once in PowerShell):
    pip install faster-whisper sounddevice soundfile pynput numpy
    pip install torch --index-url https://download.pytorch.org/whl/cu121

Run:
    python scripts/transcribe_tts.py                      # Dutch, system default mic, small model
    python scripts/transcribe_tts.py -l en                # English
    python scripts/transcribe_tts.py -d 2                 # specific mic by index
    python scripts/transcribe_tts.py -m large-v2          # more accurate model
    python scripts/transcribe_tts.py --list-devices       # list available mics and exit
    python scripts/transcribe_tts.py -l en -d 1 -m medium
"""

import argparse
import os
import sys
import threading
import time
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard as kb
from faster_whisper import WhisperModel

# ── Colours ─────────────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    _k32 = ctypes.windll.kernel32
    _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)

_R   = "\033[0m"   # reset
_DIM = "\033[2m"   # dim
_B   = "\033[1m"   # bold
_CY  = "\033[96m"  # bright cyan   — prompts / headers
_GR  = "\033[92m"  # bright green  — recording / success
_YL  = "\033[93m"  # bright yellow — processing
_OR  = "\033[33m"  # amber         — warnings / CPU
_RD  = "\033[91m"  # bright red    — quit / errors
_WH  = "\033[97m"  # bright white  — transcript text

# ── Constants ──────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000
TRANSCRIPT_DIR = Path(__file__).parent / "transcripts"
LANG_NAMES = {
    "en": "English", "nl": "Dutch",
    "ar": "Arabic",  "zh": "Chinese",  "cs": "Czech",     "da": "Danish",
    "fi": "Finnish", "fr": "French",   "de": "German",    "el": "Greek",
    "he": "Hebrew",  "hi": "Hindi",    "hu": "Hungarian", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean",    "no": "Norwegian",
    "pl": "Polish",  "pt": "Portuguese","ro": "Romanian", "ru": "Russian",
    "es": "Spanish", "sv": "Swedish",  "th": "Thai",      "tr": "Turkish",
    "uk": "Ukrainian","vi": "Vietnamese",
}
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

# ── State ──────────────────────────────────────────────────────────────────────
state = "READY"          # READY | RECORDING | TRANSCRIBING | REVIEWING | QUITTING
space_held = False
audio_frames: list = []
transcript_lines: list[str] = []
pending_text = ""
lang_code = "nl"
model_name = "small"
session_file: Path | None = None
input_device_idx: int | None = None
model: WhisperModel | None = None

review_event = threading.Event()
review_answer: str | None = None
quit_event = threading.Event()
quit_answer: str | None = None
state_lock = threading.Lock()

# ── Display ─────────────────────────────────────────────────────────────────────
def redraw(status: str | None = None) -> None:
    os.system("cls")
    print(f"{_DIM}Session :{_R} {session_file}")
    print(f"{_DIM}Language:{_R} {LANG_NAMES.get(lang_code, lang_code)}  {_DIM}|{_R}  Model: {model_name}")
    print()
    for line in transcript_lines:
        print(f"{_WH}{line}{_R}")
    if transcript_lines:
        print()
    print(status if status else f"{_DIM}[PRESS SPACE TO RECORD  |  Q to quit]{_R}")

# ── Audio ───────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status_flags):
    if state == "RECORDING":
        audio_frames.append(indata.copy())


def transcribe_worker() -> None:
    global state, pending_text, review_answer

    redraw(f"{_B}{_YL}[TRANSCRIBING]{_R}")

    if not audio_frames:
        with state_lock:
            state = "READY"
        redraw()
        return

    audio_data = np.concatenate(audio_frames, axis=0)
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, audio_data, SAMPLE_RATE)
        segments, _ = model.transcribe(tmp_path, language=lang_code)
        text = " ".join(s.text.strip() for s in segments).strip()
    except Exception as exc:
        text = ""
        print(f"\n{_RD}Transcription error: {exc}{_R}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not text:
        redraw(f"{_OR}[No speech detected — press SPACE to try again]{_R}")
        time.sleep(1.5)
        with state_lock:
            state = "READY"
        redraw()
        return

    pending_text = text
    review_answer = None
    review_event.clear()
    redraw(f'{_CY}New: "{_WH}{text}{_CY}"\n\nKeep? (Y/N, Enter = Y):{_R}')

    with state_lock:
        state = "REVIEWING"

# ── Keyboard ────────────────────────────────────────────────────────────────────
def on_press(key) -> None:
    global state, space_held, audio_frames, review_answer, quit_answer

    with state_lock:
        current_state = state

    if current_state == "REVIEWING":
        if key == kb.Key.enter:
            review_answer = "y"
            review_event.set()
        elif hasattr(key, "char") and key.char and key.char.lower() in ("y", "n"):
            review_answer = key.char.lower()
            review_event.set()
        return

    if current_state == "QUITTING":
        if key == kb.Key.enter:
            quit_answer = "y"
            quit_event.set()
        elif hasattr(key, "char") and key.char and key.char.lower() in ("y", "n"):
            quit_answer = key.char.lower()
            quit_event.set()
        return

    if current_state != "READY":
        return

    if key == kb.Key.space and not space_held:
        space_held = True
        audio_frames = []
        with state_lock:
            state = "RECORDING"
        redraw(f"{_B}{_GR}[LISTENING]{_R}")

    elif hasattr(key, "char") and key.char and key.char.lower() == "q":
        quit_answer = None
        quit_event.clear()
        with state_lock:
            state = "QUITTING"
        redraw(f"{_RD}End session? (Y/N, Enter = Y):{_R}")


def on_release(key) -> None:
    global space_held, state

    if key != kb.Key.space or not space_held:
        return

    space_held = False

    with state_lock:
        current_state = state

    if current_state == "RECORDING":
        with state_lock:
            state = "TRANSCRIBING"
        threading.Thread(target=transcribe_worker, daemon=True).start()

# ── Setup ───────────────────────────────────────────────────────────────────────
def list_devices() -> None:
    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    default_in = sd.default.device[0]
    print(f"{_CY}Available input devices:{_R}")
    for idx, d in inputs:
        marker = f"  {_DIM}* (default){_R}" if idx == default_in else ""
        print(f"  {_DIM}[{idx}]{_R} {d['name']}{marker}")


def select_device() -> int:
    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    default_in = sd.default.device[0]
    default_pos = next((pos for pos, (idx, _) in enumerate(inputs) if idx == default_in), 0)

    print(f"{_CY}Available input devices:{_R}")
    for pos, (idx, d) in enumerate(inputs):
        marker = f"  {_DIM}* (default){_R}" if idx == default_in else ""
        print(f"  {_DIM}[{pos}]{_R} {d['name']}{marker}")
    print()

    while True:
        raw = input(f"{_CY}Select device{_R} [0-{len(inputs) - 1}] (Enter = {default_pos}): ").strip()
        if raw == "":
            return inputs[default_pos][0]
        try:
            choice = int(raw)
            if 0 <= choice < len(inputs):
                return inputs[choice][0]
        except ValueError:
            pass
        print(f"{_OR}Enter a number from the list.{_R}")


OTHER_LANGUAGES = [
    ("Arabic",     "ar"),
    ("Chinese",    "zh"),
    ("Czech",      "cs"),
    ("Danish",     "da"),
    ("Finnish",    "fi"),
    ("French",     "fr"),
    ("German",     "de"),
    ("Greek",      "el"),
    ("Hebrew",     "he"),
    ("Hindi",      "hi"),
    ("Hungarian",  "hu"),
    ("Indonesian", "id"),
    ("Italian",    "it"),
    ("Japanese",   "ja"),
    ("Korean",     "ko"),
    ("Norwegian",  "no"),
    ("Polish",     "pl"),
    ("Portuguese", "pt"),
    ("Romanian",   "ro"),
    ("Russian",    "ru"),
    ("Spanish",    "es"),
    ("Swedish",    "sv"),
    ("Thai",       "th"),
    ("Turkish",    "tr"),
    ("Ukrainian",  "uk"),
    ("Vietnamese", "vi"),
]


def select_other_language() -> str:
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


def select_language() -> str:
    while True:
        ch = input(f"{_CY}Language?{_R} [E]nglish / [D]utch / [O]ther (Enter = Dutch): ").strip().lower()
        if ch in ("", "d", "nl", "dutch", "nederlands"):
            return "nl"
        if ch in ("e", "en", "english"):
            return "en"
        if ch in ("o", "other"):
            return select_other_language()
        print(f"{_OR}Enter E, D, or O.{_R}")


MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _fmt(size_bytes: int) -> str:
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    return f"{size_bytes / 1_048_576:.0f} MB"


def _local_model_info() -> dict[str, tuple[Path, int]]:
    """Return {model_name: (cache_folder, size_bytes)} for every locally cached model."""
    try:
        from huggingface_hub import constants
        hub_cache = Path(constants.HF_HUB_CACHE)
    except Exception:
        hub_cache = Path.home() / ".cache" / "huggingface" / "hub"

    info: dict[str, tuple[Path, int]] = {}
    for model in MODELS:
        folder = hub_cache / f"models--Systran--faster-whisper-{model}"
        if folder.exists():
            info[model] = (folder, _dir_size(folder))
    return info


def show_cache_overview() -> None:
    local = _local_model_info()
    not_cached = [m for m in MODELS if m not in local]

    if not local:
        print(f"{_OR}No Whisper models cached locally.{_R}\n")
    else:
        col = max(len(m) for m in local)
        sep = f"{_DIM}{'─' * 60}{_R}"
        print(f"{_CY}Cached Whisper models:{_R}")
        print(f"  {sep}")
        for m in MODELS:
            if m not in local:
                continue
            folder, sz = local[m]
            print(f"  {_WH}{m:<{col}}{_R}   {_YL}{_fmt(sz):>7}{_R}   {_DIM}{folder}{_R}")
        total = sum(sz for _, sz in local.values())
        print(f"  {sep}")
        print(f"  {_WH}{'Total':<{col}}{_R}   {_YL}{_fmt(total):>7}{_R}   {_DIM}({len(local)} model{'s' if len(local) != 1 else ''} cached){_R}")
        if not_cached:
            print(f"\n  {_DIM}Not cached: {', '.join(not_cached)}{_R}")

    print()
    print(f"  {_DIM}Note: Whisper models are multilingual — each model supports all 99 languages.")
    print(f"  Disk usage is per model only; language is a runtime setting, not a separate download.{_R}")
    print()


def select_model() -> str:
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


def resolve_device(device_arg: int) -> int:
    devices = sd.query_devices()
    inputs = {i for i, d in enumerate(devices) if d["max_input_channels"] > 0}
    if device_arg not in inputs:
        print(f"{_RD}Error: device {device_arg} is not a valid input device.{_R}", file=sys.stderr)
        print(f"{_DIM}Run with --list-devices to see available options.{_R}", file=sys.stderr)
        sys.exit(1)
    return device_arg


def load_model(size: str, force_cpu: bool) -> WhisperModel:
    print(f"{_CY}Loading Whisper '{size}' model...{_R}")
    if not force_cpu:
        try:
            m = WhisperModel(size, device="cuda", compute_type="float16")
            print(f"{_GR}Loaded on GPU (CUDA).{_R}\n")
            return m
        except Exception:
            pass
    m = WhisperModel(size, device="cpu", compute_type="int8")
    print(f"{_OR}Loaded on CPU.{_R}\n")
    return m


def create_session() -> None:
    global session_file
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    session_file = TRANSCRIPT_DIR / f"session_{ts}.txt"
    session_file.touch()

# ── Entry ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Push-to-talk live transcriber powered by Whisper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Models (fastest → most accurate):\n"
            "  tiny, base, small, medium, large-v2, large-v3\n\n"
            "Examples:\n"
            "  python transcribe_tts.py\n"
            "  python transcribe_tts.py -l en -m medium\n"
            "  python transcribe_tts.py -d 1 --cpu\n"
        ),
    )
    parser.add_argument("-l", "--language", default=None,
                        metavar="LANG",
                        help="Language code: en or nl (prompted if omitted)")
    parser.add_argument("-d", "--device", type=int, default=None,
                        metavar="INDEX",
                        help="Microphone device index (default: system default). "
                             "Use --list-devices to see options.")
    parser.add_argument("-m", "--model", default=None,
                        metavar="SIZE",
                        help="Whisper model: tiny/base/small/medium/large-v2/large-v3 "
                             "(prompted if omitted)")
    parser.add_argument("--cpu", action="store_true",
                        help="Force CPU inference even if CUDA is available")
    parser.add_argument("--list-devices", action="store_true",
                        help="Print available input devices and exit")
    return parser.parse_args()


def main() -> None:
    global lang_code, model_name, input_device_idx, model, pending_text, state

    args = parse_args()

    if args.list_devices:
        list_devices()
        return

    os.system("cls")
    print(f"{_B}{_CY}=== Whisper Live Transcriber ==={_R}\n")

    if args.device is not None:
        input_device_idx = resolve_device(args.device)
    else:
        input_device_idx = select_device()
    device_name = sd.query_devices(input_device_idx)["name"]
    print(f"Microphone: {_WH}[{input_device_idx}] {device_name}{_R}\n")

    show_cache_overview()

    if args.language is not None:
        lang = LANG_ALIASES.get(args.language.lower())
        if lang is None:
            print(f"{_RD}Error: unknown language '{args.language}'. Use 'en' or 'nl'.{_R}", file=sys.stderr)
            sys.exit(1)
        lang_code = lang
    else:
        lang_code = select_language()

    model_name = args.model if args.model is not None else select_model()

    create_session()
    model = load_model(model_name, args.cpu)

    with sd.InputStream(
        device=input_device_idx,
        channels=1,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=audio_callback,
    ):
        listener = kb.Listener(on_press=on_press, on_release=on_release, suppress=True)
        listener.start()
        redraw()

        try:
            while True:
                with state_lock:
                    current_state = state

                if current_state == "REVIEWING":
                    review_event.wait()
                    review_event.clear()
                    if review_answer == "y":
                        transcript_lines.append(pending_text)
                        with open(session_file, "a", encoding="utf-8") as f:
                            f.write(pending_text + "\n")
                    pending_text = ""
                    with state_lock:
                        state = "READY"
                    redraw()

                elif current_state == "QUITTING":
                    quit_event.wait()
                    quit_event.clear()
                    if quit_answer == "y":
                        break
                    with state_lock:
                        state = "READY"
                    redraw()

                else:
                    time.sleep(0.05)

        finally:
            listener.stop()

    os.system("cls")
    print(f"\n{_GR}Session ended.{_R}")
    print(f"Saved: {_WH}{session_file}{_R}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{_DIM}Interrupted.{_R}")
