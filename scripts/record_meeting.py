#!/usr/bin/env python3
"""
Meeting Recorder — record microphone + system audio (Windows) to an MP3

Records your microphone and everything playing through your speakers/headset
(the other participants in Teams/Zoom/Meet), mixes both into one mono 16 kHz MP3 (or a stereo one, see --separate-channels),
and afterwards offers to transcribe it with transcribe_file.py.
Nothing is transcribed while recording.

Usage:
    python scripts/record_meeting.py
    python scripts/record_meeting.py -o weekly-sync
    python scripts/record_meeting.py -o weekly-sync -l en --model medium --transcribe yes
    python scripts/record_meeting.py --list-devices
    python scripts/record_meeting.py --mic 5 --loopback 12

Stop recording with Enter or Ctrl+C.

Options:
    -o, --output      Name part of the file (default: meeting). Saved to the
                      recordings folder as <YYYY-MM-DD_HH-MM-SS>_<name>.mp3
    --mic ID          Microphone device id (default: Windows default input)
    --loopback ID     Loopback (system audio) device id (default: default output)
    --no-mic          Do not record the microphone
    --no-system       Do not record system audio
    --duck            Hybrid meeting: lower the microphone while system audio plays, so
                      remote voices coming out of the room speaker are not recorded twice
    --separate-channels
                      Stereo MP3: microphone on the left channel, system audio on the right
                      (instead of mixing both to mono). Lets transcribe_speakers.py label
                      your own voice as "You". Needs both a microphone and system audio.
    --list-devices    Show available devices and exit
    --transcribe      ask | yes | no (default: ask) — run transcribe_file.py afterwards
    -l, --language    Passed to transcribe_file.py
    --model           Passed to transcribe_file.py (default: medium)
    --cpu             Passed to transcribe_file.py

Note: only record meetings when all participants know about and agree with it.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requirements_check

try:
    import av
except ImportError:      # the GUI checks for this at start-up and disables recording
    av = None
try:
    import numpy as np
except ImportError:
    np = None

# Repo-root "recordings" folder (same level as "transcripts")
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
SCRIPT_DIR = Path(__file__).resolve().parent

SAMPLE_RATE = 16000        # Whisper's native rate; plenty for speech
MP3_BITRATE = 64000        # 64 kbps mono is small and clear for speech
STEREO_BITRATE = 96000     # for --separate-channels (two independent channels)
LATENCY = 0.5              # seconds the mixer stays behind real time
TICK = 0.1                 # mixer interval in seconds

# Hybrid-meeting ducking (see Ducker)
DUCK_GAIN = 0.15           # mic level while remote audio plays (1.0 = unchanged)
DUCK_THRESHOLD = 0.01      # system-audio RMS (0..1, about -40 dBFS) that counts as "playing"
DUCK_HOLD = 0.4            # seconds to keep ducking after the system audio goes quiet

# ── Colours ─────────────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    _k32 = ctypes.windll.kernel32
    _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)
    if sys.stderr is not None:  # None under pythonw (the GUI)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_R  = "\033[0m"
_DIM = "\033[2m"
_B   = "\033[1m"
_CY  = "\033[96m"  # bright cyan
_GR  = "\033[92m"  # bright green
_OR  = "\033[33m"  # amber
_RD  = "\033[91m"  # bright red
_WH  = "\033[97m"  # bright white


def info(msg: str) -> None:
    if sys.stderr is not None:
        print(msg, file=sys.stderr)


def fail(msg: str) -> None:
    info(f"{_RD}{msg}{_R}")
    sys.exit(1)


# ── PyAudioWPatch (WASAPI loopback) ─────────────────────────────────────────────
try:
    import pyaudiowpatch as pyaudio
except ImportError:      # the GUI checks for this at start-up and disables recording
    pyaudio = None


def require_recording_packages() -> None:
    """Command line: stop with a clear message when a recording package is missing."""
    requirements_check.require("record", tool="record_meeting.py")
    # Installed but not importable (a broken install): the modules above are then None.
    missing = [name for name, mod in (("PyAudioWPatch", pyaudio), ("PyAV", av),
                                      ("NumPy", np)) if mod is None]
    if missing:
        fail(f"Cannot record: {', '.join(missing)} could not be imported. "
             f"Try reinstalling with scripts\\install.bat")


# ── Devices ─────────────────────────────────────────────────────────────────────
def wasapi_index(pa) -> int:
    return pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]


def list_sources(pa) -> tuple[list[dict], list[dict]]:
    """Return (microphones, loopbacks) for the WASAPI host API."""
    host = wasapi_index(pa)
    mics, loops = [], []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["hostApi"] != host or d["maxInputChannels"] < 1:
            continue
        (loops if d.get("isLoopbackDevice") else mics).append(d)
    return mics, loops


def print_devices(pa) -> None:
    mics, loops = list_sources(pa)
    info(f"\n{_B}{_CY}Microphones{_R}")
    for d in mics:
        info(f"  [{d['index']}] {d['name']}")
    info(f"\n{_B}{_CY}System audio (loopback){_R}")
    for d in loops:
        info(f"  [{d['index']}] {d['name']}")
    info("")


def default_mic(pa) -> dict:
    return pa.get_default_input_device_info()


def default_loopback(pa) -> dict:
    return pa.get_default_wasapi_loopback()


# ── Capture ─────────────────────────────────────────────────────────────────────
class Source:
    """One capture stream (mic or loopback), resampled to 16 kHz mono int16."""

    def __init__(self, pa, label: str, dev: dict):
        self.label = label
        self.dev = dev
        self.channels = int(dev["maxInputChannels"])
        self.rate = int(dev["defaultSampleRate"])
        self.raw: "queue.Queue[bytes]" = queue.Queue()
        self.buf = np.zeros(0, dtype=np.int16)
        self.peak = 0.0         # recent peak (0..1) for the meter
        self.max_peak = 0.0     # peak over the whole recording
        self._rs = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        self.stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=int(dev["index"]),
            frames_per_buffer=int(self.rate * 0.05),
            stream_callback=self._callback,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        self.raw.put(in_data)
        return (None, pyaudio.paContinue)

    def drain(self) -> None:
        """Move queued raw audio into the 16 kHz mono buffer."""
        chunks = []
        while True:
            try:
                data = self.raw.get_nowait()
            except queue.Empty:
                break
            x = np.frombuffer(data, dtype=np.int16).reshape(-1, self.channels)
            mono = x.astype(np.int32).mean(axis=1).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(mono.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = self.rate
            for out in self._rs.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        if chunks:
            self.buf = np.concatenate([self.buf, *chunks])

    def take(self, n: int) -> np.ndarray:
        """Take n samples; missing samples are silence (loopback sends nothing while silent)."""
        got = self.buf[:n]
        self.buf = self.buf[n:]
        if len(got) < n:
            got = np.concatenate([got, np.zeros(n - len(got), dtype=np.int16)])
        # Device clock faster than wall clock: don't let the buffer grow without bound.
        if len(self.buf) > SAMPLE_RATE:
            self.buf = self.buf[-SAMPLE_RATE // 2:]
        p = float(np.abs(got).max()) / 32768.0 if n else 0.0
        self.peak = p
        self.max_peak = max(self.max_peak, p)
        return got

    def close(self) -> None:
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass


# ── Recorder ────────────────────────────────────────────────────────────────────
def meter(p: float) -> str:
    level = min(10, int(p ** 0.5 * 10 + 0.5)) if p > 0.001 else 0
    return "█" * level + "·" * (10 - level)


class Ducker:
    """Hybrid-meeting helper: lower the microphone while remote audio is playing.

    In a hybrid meeting the colleagues' voices come out of the room speaker and the room
    microphone hears them again (slightly delayed), so they would be recorded twice.
    While the system-audio source is active the microphone gain is reduced to DUCK_GAIN,
    and it returns to 1.0 DUCK_HOLD seconds after the system audio goes quiet.
    Trade-off: people in the room talking over a remote colleague are recorded quieter.
    """

    def __init__(self, gain: float = DUCK_GAIN, threshold: float = DUCK_THRESHOLD,
                 hold: float = DUCK_HOLD):
        self.low, self.threshold, self.hold = gain, threshold, hold
        self.gain = 1.0          # gain at the end of the previous chunk
        self.hold_left = 0.0     # seconds the ducking stays active after the last loud chunk
        self.active = False      # for display

    def process(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        n = len(mic)
        if n == 0:
            return mic
        rms = float(np.sqrt(np.mean((system.astype(np.float32) / 32768.0) ** 2)))
        if rms > self.threshold:
            self.hold_left = self.hold
        else:
            self.hold_left = max(0.0, self.hold_left - n / SAMPLE_RATE)
        target = self.low if self.hold_left > 0 else 1.0
        # Ramp across the chunk to avoid clicks.
        ramp = np.linspace(self.gain, target, n, endpoint=False, dtype=np.float32)
        self.gain = target
        self.active = target < 1.0
        return (mic.astype(np.float32) * ramp).astype(np.int16)


def open_sources(pa, mic: int | None = None, loopback: int | None = None,
                 no_mic: bool = False, no_system: bool = False) -> list[Source]:
    """Open the requested capture sources (defaults: default mic + default output loopback)."""
    sources: list[Source] = []
    try:
        if not no_mic:
            dev = pa.get_device_info_by_index(mic) if mic is not None else default_mic(pa)
            sources.append(Source(pa, "mic", dev))
        if not no_system:
            dev = (pa.get_device_info_by_index(loopback) if loopback is not None
                   else default_loopback(pa))
            sources.append(Source(pa, "sys", dev))
    except Exception:
        for s in sources:
            s.close()
        raise
    return sources


def transcribe_command(mp3_path: Path, name: str | None, language: str | None = None,
                       model: str | None = None, cpu: bool = False,
                       speakers: bool = False) -> list[str]:
    """Command that transcribes the recording; speakers=True labels who says what."""
    script = "transcribe_speakers.py" if speakers else "transcribe_file.py"
    cmd = [sys.executable, str(SCRIPT_DIR / script), str(mp3_path),
           "-o", Path(name).stem if name else "meeting"]
    if language:
        cmd += ["-l", language]
    if model:
        cmd += ["--model", model]
    if cpu:
        cmd += ["--cpu"]
    return cmd


def record(sources: list[Source], mp3_path: Path, stop: threading.Event,
           on_tick=None, duck: bool = False, stereo: bool = False) -> float:
    """Mix all sources and stream them into an MP3 until stop is set. Returns seconds.

    on_tick(elapsed_seconds, sources) is called ~10x/s; without it a console line is printed.
    duck: lower the microphone while system audio plays (hybrid meetings, see Ducker);
          only has an effect when both a "mic" and a "sys" source are recording.
    stereo: keep the sources apart (microphone left, system audio right) instead of mixing
          them to mono; only has an effect when both a "mic" and a "sys" source are recording.
    """
    labels = {s.label for s in sources}
    ducker = Ducker() if duck and labels >= {"mic", "sys"} else None
    dual = stereo and labels >= {"mic", "sys"}
    out = av.open(str(mp3_path), "w")
    stream = out.add_stream("libmp3lame", rate=SAMPLE_RATE)
    stream.layout = "stereo" if dual else "mono"
    stream.bit_rate = STEREO_BITRATE if dual else MP3_BITRATE

    def write(samples: np.ndarray) -> None:
        # mono: shape (n,); stereo: shape (n, 2), written interleaved as L R L R ...
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16",
                                           layout="stereo" if dual else "mono")
        frame.sample_rate = SAMPLE_RATE
        for pkt in stream.encode(frame):
            out.mux(pkt)

    start = time.monotonic()
    emitted = 0
    try:
        while True:
            stopping = stop.is_set()
            elapsed = time.monotonic() - start
            # While running stay LATENCY behind real time; on stop flush everything.
            target = int((elapsed if stopping else elapsed - LATENCY) * SAMPLE_RATE)
            for s in sources:
                s.drain()
            n = target - emitted
            if n > 0:
                parts = {s.label: s.take(n) for s in sources}
                if ducker is not None:
                    parts["mic"] = ducker.process(parts["mic"], parts["sys"])
                if dual:
                    write(np.column_stack((parts["mic"], parts["sys"])))
                else:
                    mix = np.zeros(n, dtype=np.int32)
                    for a in parts.values():
                        mix += a
                    write(np.clip(mix, -32768, 32767).astype(np.int16))
                emitted = target
                if on_tick is not None:
                    on_tick(elapsed, sources)
                elif sys.stderr is not None:
                    line = "  ".join(f"{s.label} {meter(s.peak)}" for s in sources)
                    mm, ss = divmod(int(elapsed), 60)
                    hh, mm = divmod(mm, 60)
                    print(f"\r  {_RD}●{_R} {hh:02d}:{mm:02d}:{ss:02d}   {_DIM}{line}{_R}   ",
                          end="", file=sys.stderr, flush=True)
            if stopping:
                break
            time.sleep(TICK)
    finally:
        for pkt in stream.encode(None):
            out.mux(pkt)
        out.close()
    info("")
    return emitted / SAMPLE_RATE


# ── Main ────────────────────────────────────────────────────────────────────────
def build_name(requested: str | None) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(requested).stem if requested else "meeting"
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return RECORDINGS_DIR / f"{ts}_{name}.mp3"


def ask_yes(prompt: str) -> bool:
    ans = input(f"{_CY}{prompt} [Y/n]: {_R}").strip().lower()
    return ans in ("", "y", "yes", "j", "ja")


def main() -> None:
    require_recording_packages()
    ap = argparse.ArgumentParser(description="Record microphone + system audio to MP3")
    ap.add_argument("-o", "--output")
    ap.add_argument("--mic", type=int)
    ap.add_argument("--loopback", type=int)
    ap.add_argument("--no-mic", action="store_true")
    ap.add_argument("--no-system", action="store_true")
    ap.add_argument("--duck", action="store_true")
    ap.add_argument("--separate-channels", action="store_true")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--transcribe", choices=["ask", "yes", "no"], default="ask")
    ap.add_argument("-l", "--language")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()

    if args.no_mic and args.no_system:
        fail("Nothing to record: --no-mic and --no-system were both given.")
    if args.separate_channels and (args.no_mic or args.no_system):
        info(f"{_OR}--separate-channels needs both a microphone and system audio; "
             f"recording mono.{_R}")
        args.separate_channels = False
    tx_missing = requirements_check.check("transcribe")["transcribe"]
    if tx_missing and args.transcribe != "no":
        if args.transcribe == "yes":
            requirements_check.require("transcribe", tool="record_meeting.py --transcribe yes")
        info(f"{_OR}Note: transcription is unavailable (missing {', '.join(tx_missing)}), so this "
             f"only records. Run scripts\\install.bat to install it.{_R}")
        args.transcribe = "no"

    pa = pyaudio.PyAudio()
    if args.list_devices:
        print_devices(pa)
        pa.terminate()
        return

    try:
        sources = open_sources(pa, args.mic, args.loopback, args.no_mic, args.no_system)
    except Exception as e:
        pa.terminate()
        fail(f"Could not open audio device: {e}\nUse --list-devices to see device ids.")
    for s in sources:
        info(f"{_DIM}{'Microphone' if s.label == 'mic' else 'System    '} : {s.dev['name']}{_R}")

    mp3_path = build_name(args.output)
    info(f"\n{_B}{_WH}Recording to{_R} {mp3_path}")
    info(f"{_DIM}Press Enter (or Ctrl+C) to stop.{_R}\n")

    stop = threading.Event()

    def wait_enter() -> None:
        try:
            input()
        except EOFError:
            pass
        stop.set()

    threading.Thread(target=wait_enter, daemon=True).start()

    seconds = 0.0
    try:
        seconds = record(sources, mp3_path, stop, duck=args.duck,
                         stereo=args.separate_channels)
    except KeyboardInterrupt:
        # record() closes and finalises the MP3 in its own finally block.
        print("", file=sys.stderr)
    finally:
        for s in sources:
            s.close()
        pa.terminate()

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        fail("No audio was saved.")

    size_mb = mp3_path.stat().st_size / (1024 * 1024)
    info(f"{_GR}Saved{_R} {mp3_path}  ({size_mb:.1f} MB)")
    for s in sources:
        if s.max_peak < 0.001:
            info(f"{_OR}Warning: the '{s.label}' source was silent for the whole recording "
                 f"({s.dev['name']}).{_R}")

    do_transcribe = args.transcribe == "yes" or (
        args.transcribe == "ask" and ask_yes("Transcribe now?"))
    if do_transcribe:
        sys.exit(subprocess.call(
            transcribe_command(mp3_path, args.output, args.language, args.model, args.cpu)))


if __name__ == "__main__":
    main()
