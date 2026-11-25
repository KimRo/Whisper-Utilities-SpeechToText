#!/usr/bin/env python3
"""
Whisper Speaker Transcriber — transcribe an audio file and label who says what

Uses faster-whisper for the text and pyannote.audio (speaker diarization) for the
speakers. Output looks like:

    [00:00:03] Speaker 1: Goedemorgen allemaal.
    [00:00:07] Speaker 2: Goedemorgen, zullen we beginnen?

Speakers are anonymous (Speaker 1, Speaker 2, ...) in order of first appearance.
Use --names to replace the labels with real names.

One-time setup (the pyannote models are gated on Hugging Face):
    1. Create a free account at https://huggingface.co
    2. Accept the terms on both model pages:
         https://huggingface.co/pyannote/speaker-diarization-3.1
         https://huggingface.co/pyannote/segmentation-3.0
    3. Create a read token (Settings > Access Tokens) and set it:
         setx HF_TOKEN hf_xxxxxxxx        (then open a new terminal)
       or run `huggingface-cli login`, or just paste it when the script asks
       (a pasted token is used for this run only and is not saved).
    After the first download the models are cached and work offline.

Usage (command-line):
    python scripts/transcribe_speakers.py meeting.mp3
    python scripts/transcribe_speakers.py meeting.mp3 -l en --speakers 3
    python scripts/transcribe_speakers.py meeting.mp3 --names "Kim,Jan"

Usage (interactive — omit the audio file to be prompted for all options):
    python scripts/transcribe_speakers.py

Options:
    -l, --language   Language code (default: nl)
    -o, --output     Output base name (default: input stem). Always saved to the
                     transcripts folder as <YYYY-MM-DD_HH-MM-SS>_<name>.txt
    --model          Whisper model size (default: medium)
    --cpu            Force CPU even if CUDA is available
    --speakers N     Exact number of speakers, if you know it (improves accuracy)
    --min-speakers N / --max-speakers N   Bounds on the number of speakers
    --names A,B,C    Names for the speakers, in order of first appearance

Note: overlapping speech is assigned to a single speaker per word, so crosstalk
is not separated perfectly.
"""

import argparse
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

# Repo-root "transcripts" folder (same location for all scripts)
TRANSCRIPT_DIR = Path(__file__).resolve().parent.parent / "transcripts"

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
SAMPLE_RATE = 16000

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
DEFAULT_MODEL = "medium"

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


def fail(msg: str) -> None:
    print(f"{_RD}Error: {msg}{_R}", file=sys.stderr)
    sys.exit(1)


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
        marker = f"  {_DIM}* (default){_R}" if m == DEFAULT_MODEL else ""
        print(f"  {_DIM}[{i}]{_R} {m}{marker}")
    print()
    while True:
        raw = input(f"{_CY}Select model{_R} [0-{len(MODELS) - 1}] (Enter = {DEFAULT_MODEL}): ").strip()
        if raw == "":
            return DEFAULT_MODEL
        try:
            choice = int(raw)
            if 0 <= choice < len(MODELS):
                return MODELS[choice]
        except ValueError:
            pass
        print(f"{_OR}Enter a number from the list.{_R}")


def prompt_speakers() -> int | None:
    while True:
        raw = input(f"{_CY}Number of speakers{_R} (Enter = detect automatically): ").strip()
        if raw == "":
            return None
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print(f"{_OR}Enter a number, or press Enter.{_R}")


def prompt_names() -> list[str] | None:
    raw = input(f"{_CY}Speaker names{_R} (comma separated, Enter = Speaker 1, Speaker 2...): ").strip()
    return parse_names(raw)


def prompt_output(audio_path: Path) -> Path:
    default = build_output_path(audio_path, None)
    raw = input(f"{_CY}Output name{_R} (Enter = {_DIM}{default.name}{_R}): ").strip().strip('"')
    return build_output_path(audio_path, Path(raw) if raw else None)


def parse_names(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return names or None


def build_output_path(audio_path: Path, requested: Path | None) -> Path:
    """Always write into the transcripts folder as '<timestamp>_<original name>.txt'."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    stem = requested.stem if requested else audio_path.stem
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return TRANSCRIPT_DIR / f"{ts}_{stem}.txt"


# ── Whisper ──────────────────────────────────────────────────────────────────────
def load_whisper(model_size: str, force_cpu: bool):
    from faster_whisper import WhisperModel

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


def transcribe_words(audio_path: Path, model, lang: str) -> list[tuple[float, float, str]]:
    """Return [(start, end, word), ...] for the whole file."""
    print(f"{_CY}Transcribing {_WH}{audio_path.name}{_CY} ...{_R}", file=sys.stderr)
    segments, info = model.transcribe(str(audio_path), language=lang, word_timestamps=True)
    print(f"{_DIM}Language : {lang}  |  Duration: {info.duration:.1f}s{_R}", file=sys.stderr)
    words = []
    for seg in segments:
        for w in seg.words or []:
            if w.word.strip():
                words.append((w.start, w.end, w.word))
    return words


# ── Diarization ──────────────────────────────────────────────────────────────────
def load_audio_waveform(audio_path: Path):
    """Decode any audio file to a 16 kHz mono float tensor (1, n) using PyAV.

    Passing a waveform avoids pyannote/torchaudio needing its own audio backend.
    """
    import av
    import numpy as np
    import torch

    resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(audio_path)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray())
    if not chunks:
        fail(f"no audio could be decoded from {audio_path}")
    wave = np.concatenate(chunks, axis=1).astype("float32")
    return torch.from_numpy(wave)


def find_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token
    try:  # token saved by `huggingface-cli login`
        from huggingface_hub import get_token
        return get_token()
    except Exception:
        return None


def allow_pyannote_checkpoints() -> None:
    """PyTorch >= 2.6 only unpickles allow-listed classes by default (weights_only=True).

    pyannote 3.x checkpoints contain these four classes. Allow-listing exactly them keeps
    the safety check on, unlike forcing weights_only=False for everything.
    """
    import importlib
    import torch

    if not hasattr(torch.serialization, "add_safe_globals"):
        return  # older torch: no weights_only restriction to work around
    classes = []
    for path in ("torch.torch_version.TorchVersion",
                 "pyannote.audio.core.task.Specifications",
                 "pyannote.audio.core.task.Problem",
                 "pyannote.audio.core.task.Resolution"):
        mod, _, attr = path.rpartition(".")
        try:
            classes.append(getattr(importlib.import_module(mod), attr))
        except (ImportError, AttributeError):
            pass
    torch.serialization.add_safe_globals(classes)


def load_diarizer(force_cpu: bool):
    try:
        from pyannote.audio import Pipeline
        import torch
    except ImportError:
        fail("pyannote.audio is not installed. Run:  pip install \"pyannote.audio==3.4.0\"")

    allow_pyannote_checkpoints()
    token = find_hf_token()
    print(f"{_CY}Loading speaker model '{DIARIZATION_MODEL}'...{_R}", file=sys.stderr)

    def _load(tok):
        return Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=tok)

    pipeline = None
    error = None
    try:
        pipeline = _load(token)
    except Exception as exc:
        error = exc
        print(f"{_OR}Could not load the speaker model: {type(exc).__name__}: {exc}{_R}",
              file=sys.stderr)

    # Only ask for a token when none was found at all; any other failure (version
    # mismatch, network, terms not accepted) is reported as-is instead of prompting.
    if pipeline is None and token is None and sys.stdin.isatty():
        print(f"{_OR}No Hugging Face token found (see the setup steps at the top of this "
              f"script).{_R}", file=sys.stderr)
        token = getpass.getpass("Paste Hugging Face token (not saved, Enter to abort): ").strip()
        if token:
            try:
                pipeline = _load(token)
            except Exception as exc:
                error = exc

    if pipeline is None:
        hint = ("No token was found: set HF_TOKEN or run `huggingface-cli login`."
                if token is None else
                f"Check that you accepted the terms for {DIARIZATION_MODEL} and "
                "pyannote/segmentation-3.0 on huggingface.co, and that the token is valid.")
        if error is None and token is not None:
            hint = ("pyannote returned no model, which usually means access to a gated model "
                    "was denied. Open https://huggingface.co/pyannote/speaker-diarization-3.1 and "
                    "https://huggingface.co/pyannote/segmentation-3.0 while logged in as the "
                    "owner of this token and accept the terms on each. " + hint)
        fail(f"speaker model unavailable"
             f"{' (' + type(error).__name__ + ')' if error else ''}. {hint}")

    if not force_cpu and torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        print(f"{_GR}Speaker model on GPU (CUDA).{_R}", file=sys.stderr)
    else:
        print(f"{_OR}Speaker model on CPU (slow for long recordings).{_R}", file=sys.stderr)
    return pipeline


def diarize(audio_path: Path, pipeline, num_speakers, min_speakers, max_speakers):
    """Return [(start, end, speaker_label), ...] sorted by start time."""
    print(f"{_CY}Identifying speakers ...{_R}", file=sys.stderr)
    waveform = load_audio_waveform(audio_path)
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    if min_speakers:
        kwargs["min_speakers"] = min_speakers
    if max_speakers:
        kwargs["max_speakers"] = max_speakers
    annotation = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **kwargs)
    turns = [(t.start, t.end, spk) for t, _, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda x: x[0])
    return turns


# ── Merge ────────────────────────────────────────────────────────────────────────
def speaker_for_word(start: float, end: float, turns, fallback: str | None) -> str | None:
    """Speaker whose turns overlap the word most; nearest turn if none overlap."""
    overlap: dict[str, float] = {}
    for t_start, t_end, spk in turns:
        if t_start >= end:
            break
        o = min(end, t_end) - max(start, t_start)
        if o > 0:
            overlap[spk] = overlap.get(spk, 0.0) + o
    if overlap:
        return max(overlap, key=overlap.get)
    if not turns:
        return fallback
    mid = (start + end) / 2
    nearest = min(turns, key=lambda t: 0 if t[0] <= mid <= t[1] else min(abs(mid - t[0]), abs(mid - t[1])))
    return nearest[2]


def build_paragraphs(words, turns) -> list[tuple[float, str, str]]:
    """Group consecutive words of the same speaker -> [(start, raw_label, text), ...]."""
    paragraphs: list[tuple[float, str, list[str]]] = []
    current = None
    for start, end, word in words:
        spk = speaker_for_word(start, end, turns, current)
        if spk is None:
            spk = "SPEAKER_00"
        if paragraphs and paragraphs[-1][1] == spk:
            paragraphs[-1][2].append(word)
        else:
            paragraphs.append((start, spk, [word]))
        current = spk
    return [(s, spk, "".join(ws).strip()) for s, spk, ws in paragraphs]


def label_speakers(paragraphs, names: list[str] | None) -> dict[str, str]:
    """Raw pyannote labels -> 'Speaker N' (or given names) by order of first appearance."""
    order: list[str] = []
    for _, spk, _ in paragraphs:
        if spk not in order:
            order.append(spk)
    labels = {}
    for i, spk in enumerate(order):
        labels[spk] = names[i] if names and i < len(names) else f"Speaker {i + 1}"
    if names and len(names) < len(order):
        print(f"{_OR}Note: {len(order)} speakers found but only {len(names)} names given; "
              f"the rest are numbered.{_R}", file=sys.stderr)
    elif names and len(names) > len(order):
        print(f"{_OR}Note: {len(order)} speakers found but {len(names)} names given; "
              f"extra names ignored.{_R}", file=sys.stderr)
    return labels


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render(paragraphs, labels: dict[str, str]) -> str:
    return "\n".join(f"[{fmt_time(start)}] {labels[spk]}: {text}" for start, spk, text in paragraphs)


# ── Entry ────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe an audio file and label the speakers.")
    parser.add_argument("audio", type=Path, nargs="?", default=None,
                        help="Audio file to transcribe (omit to be prompted interactively)")
    parser.add_argument("-l", "--language", default=None,
                        help="Language code, e.g. en or nl (default: nl)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output base name (default: audio stem). The file is always saved in "
                             "the transcripts folder as <timestamp>_<name>.txt")
    parser.add_argument("--model", default=None, help=f"Whisper model size (default: {DEFAULT_MODEL})")
    parser.add_argument("--cpu", action="store_true", help="Force CPU inference")
    parser.add_argument("--speakers", type=int, default=None, help="Exact number of speakers")
    parser.add_argument("--min-speakers", type=int, default=None, help="Minimum number of speakers")
    parser.add_argument("--max-speakers", type=int, default=None, help="Maximum number of speakers")
    parser.add_argument("--names", default=None,
                        help="Comma-separated names, in order of first appearance")
    args = parser.parse_args()

    # Redirected stdout on Windows may use a legacy codepage; never crash on printing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.audio is None:
        # ── Interactive mode ──────────────────────────────────────────────────
        print(f"\n{_B}{_CY}=== Whisper Speaker Transcriber ==={_R}\n")
        audio_path = prompt_audio()
        print()
        lang_code = prompt_language()
        print()
        model_name = prompt_model()
        print()
        num_speakers = prompt_speakers()
        min_speakers = max_speakers = None
        names = prompt_names()
        print()
        output_path = prompt_output(audio_path)
        print()
        force_cpu = False
    else:
        # ── Command-line mode ─────────────────────────────────────────────────
        audio_path = args.audio.resolve()
        if not audio_path.exists():
            fail(f"file not found: {audio_path}")
        lang_input = args.language or "nl"
        lang_code = LANG_ALIASES.get(lang_input.lower())
        if lang_code is None:
            fail(f"unknown language '{lang_input}'.")
        model_name = args.model or DEFAULT_MODEL
        output_path = build_output_path(audio_path, args.output)
        force_cpu = args.cpu
        num_speakers, min_speakers, max_speakers = args.speakers, args.min_speakers, args.max_speakers
        names = parse_names(args.names)

    # Load the diarizer first so a missing token fails fast, before the slow transcription.
    pipeline = load_diarizer(force_cpu)
    whisper = load_whisper(model_name, force_cpu)

    words = transcribe_words(audio_path, whisper, lang_code)
    if not words:
        print(f"{_OR}No speech detected.{_R}", file=sys.stderr)
        sys.exit(0)

    turns = diarize(audio_path, pipeline, num_speakers, min_speakers, max_speakers)
    paragraphs = build_paragraphs(words, turns)
    text = render(paragraphs, label_speakers(paragraphs, names))

    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"{_GR}Saved : {_WH}{output_path}{_R}", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
