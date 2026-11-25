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
    2. Accept the terms on the model page:
         https://huggingface.co/pyannote/speaker-diarization-community-1
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
    --dual-channel   auto | on | off (default: auto). A stereo file is treated as a
                     "--separate-channels" recording from record_meeting.py: left = your
                     microphone, right = system audio (the remote participants). Words where
                     the microphone dominates are labelled "You"; only the right channel is
                     split into Speaker 1, 2, ... auto = on for 2-channel files.
    --me NAME        Label for the microphone channel (default: You). Everyone talking into
                     that microphone, e.g. all people in your room, gets this label.

Note: overlapping speech is assigned to a single speaker per word, so crosstalk
is not separated perfectly. Speaker changes are snapped to sentence boundaries
(see PAUSE_SPLIT and MIN_RUN) so sentences are not cut in half.
"""

import argparse
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

import logging
import warnings

import requirements_check

# Known harmless messages from torch/pyannote that only bury the useful output. Each filter
# matches one specific message; every other warning is still shown.
logging.getLogger("torch.utils.flop_counter").setLevel(logging.ERROR)   # "triton not found" (no Triton on Windows)
for _msg in (r"TensorFloat-32 \(TF32\) has been disabled",    # pyannote turns TF32 off on purpose
             r"std\(\): degrees of freedom is <= 0"):          # pyannote pooling on very short/silent chunks
    warnings.filterwarnings("ignore", message=_msg)

# Repo-root "transcripts" folder (same location for all scripts)
TRANSCRIPT_DIR = Path(__file__).resolve().parent.parent / "transcripts"

DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
SAMPLE_RATE = 16000

# Speaker changes are snapped to sentence boundaries. A sentence ends at terminal
# punctuation or after a pause of PAUSE_SPLIT seconds. Within a sentence, a run by another
# speaker shorter than MIN_RUN seconds is absorbed; a longer one is a real change.
PAUSE_SPLIT = 0.8
MIN_RUN = 2.0
SENTENCE_END = (".", "?", "!", "…")

# Dual-channel recordings (record_meeting.py --separate-channels): left = microphone, right =
# system audio. A word is "You" when the microphone is clearly the louder channel. Without
# headphones the speakers leak remote voices into the microphone; a higher YOU_RATIO helps.
YOU_RATIO = 2.0          # microphone RMS must be at least this many times the system RMS
YOU_MIN_RMS = 0.005      # ...and above this floor (about -46 dBFS), so silence never counts
ME_LABEL = "You"
YOU = "__YOU__"          # internal speaker label for the microphone channel

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
def load_audio_channels(audio_path: Path):
    """Decode any audio file to 16 kHz float32 with shape (channels, n) using PyAV.

    channels is 1 for mono files and 2 for stereo (or more) files. Passing a waveform to
    pyannote avoids it needing its own audio backend.
    """
    import av
    import numpy as np

    chunks = []
    with av.open(str(audio_path)) as container:
        layout = "stereo" if container.streams.audio[0].channels >= 2 else "mono"
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray())
    if not chunks:
        fail(f"no audio could be decoded from {audio_path}")
    return np.concatenate(chunks, axis=1).astype("float32")


def _rms(x) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def detect_you(words, mic, system) -> list[bool]:
    """Per word: True when the microphone channel clearly dominates (see YOU_RATIO)."""
    flags = []
    for start, end, _ in words:
        a = int(start * SAMPLE_RATE)
        b = max(int(end * SAMPLE_RATE), a + 1)
        m, s = _rms(mic[a:b]), _rms(system[a:b])
        flags.append(m >= YOU_MIN_RMS and m >= YOU_RATIO * s)
    return flags


def find_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token
    try:  # token saved by `huggingface-cli login`
        from huggingface_hub import get_token
        return get_token()
    except Exception:
        return None


def load_diarizer(force_cpu: bool):
    try:
        from pyannote.audio import Pipeline
        import torch
    except ImportError as exc:
        fail(f"Could not load pyannote.audio or PyTorch ({exc}). Run scripts\\install.bat")

    token = find_hf_token()
    print(f"{_CY}Loading speaker model '{DIARIZATION_MODEL}'...{_R}", file=sys.stderr)

    def _load(tok):
        return Pipeline.from_pretrained(DIARIZATION_MODEL, token=tok)

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
    if pipeline is None and token is None and requirements_check.is_interactive():
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
                f"Check that you accepted the terms for {DIARIZATION_MODEL} "
                "on huggingface.co, and that the token is valid.")
        if error is None and token is not None:
            hint = ("pyannote returned no model, which usually means access to a gated model "
                    "was denied. Open https://huggingface.co/pyannote/speaker-diarization-community-1 "
                    "while logged in as the owner of this token and accept the terms. " + hint)
        fail(f"speaker model unavailable"
             f"{' (' + type(error).__name__ + ')' if error else ''}. {hint}")

    if not force_cpu and torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        print(f"{_GR}Speaker model on GPU (CUDA).{_R}", file=sys.stderr)
    else:
        print(f"{_OR}Speaker model on CPU (slow for long recordings).{_R}", file=sys.stderr)
    return pipeline


def diarize(samples, pipeline, num_speakers, min_speakers, max_speakers):
    """Return [(start, end, speaker_label), ...] sorted by start time.

    samples: 16 kHz mono float32 numpy array, shape (n,).
    """
    import torch

    print(f"{_CY}Identifying speakers ...{_R}", file=sys.stderr)
    waveform = torch.from_numpy(samples.reshape(1, -1))
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    if min_speakers:
        kwargs["min_speakers"] = min_speakers
    if max_speakers:
        kwargs["max_speakers"] = max_speakers
    output = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **kwargs)
    # "Exclusive" diarization has no overlapping turns, which suits matching words to speakers.
    annotation = output.exclusive_speaker_diarization
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


def split_sentences(words) -> list[list[int]]:
    """Indices of words grouped into sentences (terminal punctuation or a long pause)."""
    sentences: list[list[int]] = []
    current: list[int] = []
    for i, (start, end, word) in enumerate(words):
        current.append(i)
        text = word.strip()
        next_gap = words[i + 1][0] - end if i + 1 < len(words) else None
        if text.endswith(SENTENCE_END) or next_gap is None or next_gap >= PAUSE_SPLIT:
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences


def snap_to_sentences(words, speakers: list[str]) -> list[str]:
    """Move speaker changes to sentence boundaries.

    Per sentence, the speaker who talks most gets any short (< MIN_RUN) run by another
    speaker. Runs of MIN_RUN seconds or more are kept, so genuine interruptions and long
    unpunctuated stretches still switch speaker.
    """
    result = list(speakers)
    for idx in split_sentences(words):
        # contiguous runs of the same speaker: [speaker, first_pos, last_pos, seconds]
        runs: list[list] = []
        for i in idx:
            dur = max(words[i][1] - words[i][0], 0.0)
            if runs and runs[-1][0] == speakers[i]:
                runs[-1][2] = i
                runs[-1][3] += dur
            else:
                runs.append([speakers[i], i, i, dur])
        if len(runs) < 2:
            continue
        total: dict[str, float] = {}
        for spk, _, _, dur in runs:
            total[spk] = total.get(spk, 0.0) + dur
        majority = max(total, key=total.get)
        for spk, first, last, dur in runs:
            if dur < MIN_RUN:
                for i in range(first, last + 1):
                    result[i] = majority
    return result


def build_paragraphs(words, turns, you=None) -> list[tuple[float, str, str]]:
    """Group consecutive words of the same speaker -> [(start, raw_label, text), ...].

    you: optional per-word flags (see detect_you); flagged words are the microphone speaker
    and bypass the diarization turns, which only describe the remote participants.
    """
    speakers: list[str] = []
    remote = None
    for i, (start, end, _) in enumerate(words):
        if you is not None and you[i]:
            speakers.append(YOU)
            continue
        spk = speaker_for_word(start, end, turns, remote) or "SPEAKER_00"
        speakers.append(spk)
        remote = spk
    speakers = snap_to_sentences(words, speakers)

    paragraphs: list[tuple[float, str, list[str]]] = []
    for (start, _, word), spk in zip(words, speakers):
        if paragraphs and paragraphs[-1][1] == spk:
            paragraphs[-1][2].append(word)
        else:
            paragraphs.append((start, spk, [word]))
    return [(st, spk, "".join(ws).strip()) for st, spk, ws in paragraphs]


def label_speakers(paragraphs, names: list[str] | None, me: str = ME_LABEL) -> dict[str, str]:
    """Raw labels -> 'Speaker N' (or given names) by order of first appearance.

    The microphone speaker (YOU) is labelled `me` and is not part of the numbering/names.
    """
    order: list[str] = []
    for _, spk, _ in paragraphs:
        if spk != YOU and spk not in order:
            order.append(spk)
    labels = {YOU: me}
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
                        help="Comma-separated names for the remote speakers, in order of "
                             "first appearance")
    parser.add_argument("--dual-channel", choices=["auto", "on", "off"], default="auto",
                        help="Treat a stereo file as microphone (left) + system audio (right); "
                             "auto = on for 2-channel files")
    parser.add_argument("--me", default=ME_LABEL,
                        help=f"Label for the microphone channel (default: {ME_LABEL})")
    args = parser.parse_args()

    # Redirected stdout on Windows may use a legacy codepage; never crash on printing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    # Fail fast with a clear message, before any model is loaded. The Hugging Face token is only
    # required up front when nobody can be asked for it (no terminal).
    requirements_check.require("transcribe", "speakers", token=not requirements_check.is_interactive(),
                               tool="transcribe_speakers.py")

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
        dual_mode, me_label = "auto", ME_LABEL
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
        dual_mode, me_label = args.dual_channel, args.me

    # Load the diarizer first so a missing token fails fast, before the slow transcription.
    pipeline = load_diarizer(force_cpu)
    whisper = load_whisper(model_name, force_cpu)

    words = transcribe_words(audio_path, whisper, lang_code)
    if not words:
        print(f"{_OR}No speech detected.{_R}", file=sys.stderr)
        sys.exit(0)

    channels = load_audio_channels(audio_path)
    if dual_mode == "on" and channels.shape[0] != 2:
        fail("--dual-channel on needs a stereo file (left = microphone, right = system audio).")
    dual = channels.shape[0] == 2 and dual_mode != "off"

    you = None
    if dual:
        print(f"{_DIM}Stereo file: left channel = microphone ('{me_label}'), right channel = "
              f"system audio (remote speakers). Use --dual-channel off to ignore this.{_R}",
              file=sys.stderr)
        mic, remote = channels[0], channels[1]
        you = detect_you(words, mic, remote)
    else:
        remote = channels.mean(axis=0)

    if dual and float(abs(mic).max()) < 0.001:
        print(f"{_DIM}Note: the microphone channel (left) is silent in this recording (nobody "
              f"spoke on it, or it was muted), so nothing is labelled '{me_label}'. Everything "
              f"on the system-audio channel is numbered as Speaker N.{_R}", file=sys.stderr)

    if dual and float(abs(remote).max()) < 0.001:
        print(f"{_OR}The system-audio channel is silent: no remote speakers to identify.{_R}",
              file=sys.stderr)
        turns = []
    else:
        turns = diarize(remote, pipeline, num_speakers, min_speakers, max_speakers)
    paragraphs = build_paragraphs(words, turns, you)
    text = render(paragraphs, label_speakers(paragraphs, names, me_label))

    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"{_GR}Saved : {_WH}{output_path}{_R}", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
