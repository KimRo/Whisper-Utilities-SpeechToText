#!/usr/bin/env python3
"""
Meeting Recorder GUI — small window (and system-tray icon) around record_meeting.py

Usage:
    python scripts/record_meeting_gui.py              # open the window
    python scripts/record_meeting_gui.py --autostart  # open and start recording at once
    python scripts/record_meeting_gui.py --autostart --tray   # ... and start minimized to tray

Records microphone + system audio with the default devices to <Output folder>/<timestamp>_meeting/<timestamp>_meeting.mp3 (default output folder: Documents/Meeting Recorder);
the transcript and the log file are saved in that same folder.
The optional "Name" field replaces "meeting" in the file names (e.g. <timestamp>_Budget_review.mp3).
The window can be minimized to the system tray (the window's minimize button, the
"Minimize to tray" button, or closing the window while recording).
Tray icon: red = recording, grey = idle. Right-click for Show / Start / Stop / Quit.
After stopping, the recording can be transcribed automatically (runs in the background;
progress and the result appear in the Status box and the window comes to the front when it
is done): "Normal" runs transcribe_file.py, "With speakers" runs transcribe_speakers.py, which
labels who says what (needs the one-time Hugging Face token, see doc/transcribe_speakers.md).
"Transcribe a recording..." does the same for any existing audio file you pick (the dialog
opens in the recordings folder), using the mode, language and model selected in the window.
The recording format (MP3 or WAV, both 16 kHz mono and sized for voice) is chosen below "Model".
Everything shown in the Status box is also logged, with timestamps, to <recording folder>/<recording name>.log.txt
(next to the recording; transcribing an existing file appends to <that file's name>.log.txt).
"Open log" (below the Status box) opens the log of the running transcription, else the newest log.
The "Also transcribe while recording, every N min" field (0 = off) splits a long recording into part files
that are transcribed in the background (queued when slower than real time) into one combined transcript,
and merges the parts into one recording afterwards (see doc/record_meeting.md).
"Open last transcription" opens the newest transcript in the transcripts folder; it is greyed
out while a transcription is running in the background (or when there is no transcript yet).

Every setting changed in the window is saved (%APPDATA%\\WhisperMeetingRecorder\\settings.json) and
restored next time. Command-line options (--mic, --system, --model, -l, --format, --mode, --duck/--no-duck,
--chunk-minutes, --output-dir, ... see --help) override the saved values for that run only, without saving
them. See doc/record_meeting.md.

At start-up the window checks which packages are installed. Options that cannot work are
greyed out and the Status box lists what is missing (scripts\\install.bat installs it).

Only record meetings when all participants know about and agree with it.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None  # only the tray icon needs Pillow; reported at start-up

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meeting_settings as ms
import record_meeting as rm  # importable even when its recording packages are missing
import requirements_check as rc

try:
    import pystray
except ImportError:
    pystray = None  # tray is optional; window still works

LANGUAGES = ["nl", "en", "fr", "de", "es", "it", "pt", "pl", "sv", "da", "no", "fi"]
FORMATS = {"MP3 (small, 64 kbps voice)": "mp3", "WAV (16 kHz 16-bit, uncompressed)": "wav"}
MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
DEFAULT_MODEL = "medium"
OFF = "Off (don't record this source)"
ANSI = re.compile(r"\x1b\[[0-9;]*m")                     # colour codes in the scripts' output
STAGES = ("Loading", "Transcribing", "Identifying", "Language")   # progress lines worth showing
TX_COLORS = {"busy": "#555555", "ok": "#1a7f37", "fail": "#c62828"}
STAMP = re.compile(r"^\[(\d+):(\d\d):(\d\d)\]", re.M)             # "[HH:MM:SS]" at a line start
MIN_PART = 1.0                                                   # shorter parts are not transcribed

def check_requirements() -> tuple[dict, dict]:
    """Return (missing, available) for the features this window uses (see requirements_check)."""
    missing = rc.check("record", "transcribe", "speakers", "tray", token=True)
    if pystray is None and not missing["tray"]:
        missing["tray"].append("pystray (failed to load)")
    available = {
        "record": not missing["record"],
        "transcribe": not missing["transcribe"],
        "speakers": not missing["transcribe"] and not missing["speakers"],
        "tray": not missing["tray"],
    }
    return missing, available


def missing_report(missing: dict) -> str:
    return rc.missing_report(missing, pip=False)   # the window only points at the installer


AUDIO_TYPES = [
    ("Audio and video files", "*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.aac *.wma *.mp4 *.webm *.mkv"),
    ("All files", "*.*"),
]


def tray_image(recording: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(220, 40, 40, 255) if recording else (130, 130, 130, 255))
    d.ellipse((24, 14, 40, 38), fill=(255, 255, 255, 255))       # mic head
    d.rectangle((30, 38, 34, 46), fill=(255, 255, 255, 255))     # stand
    d.rectangle((22, 46, 42, 49), fill=(255, 255, 255, 255))     # base
    return img


def clean_name(text: str) -> str | None:
    """Make free text safe for a file name: spaces -> '_', no characters Windows rejects, no dots
    (record_meeting.build_name would treat them as an extension). None when nothing is left."""
    text = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', "", text.strip())
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:80] or None


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def shift_stamps(text: str, offset: float) -> str:
    """Add offset seconds to every leading [HH:MM:SS] stamp (speaker transcripts of a later part)."""
    def one(m):
        t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(offset)
        return f"[{hms(t)}]"
    return STAMP.sub(one, text)


def single_instance() -> bool:
    """True if this is the only running instance (named Windows mutex)."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "WhisperMeetingRecorderGUI")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


class App:
    def __init__(self, root: tk.Tk, autostart: bool, start_in_tray: bool,
                 cli: dict | None = None, settings_path: Path | None = None):
        self.root = root
        self.settings_path = settings_path             # None = the default settings file
        self.loading = True                            # True: changes are not saved as settings
        self.cmds: "queue.Queue[str]" = queue.Queue()   # commands from the tray thread
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.recording = False
        self.elapsed = 0.0
        self.peaks = {"mic": 0.0, "sys": 0.0}
        self.result: dict | None = None                 # filled by the worker when finished
        self.quit_after_stop = False
        self.closing = False
        self.icon = None
        # Split recording (see start): a session while parts are being recorded/transcribed/merged
        self.session: dict | None = None
        self.part_q: "queue.Queue" = queue.Queue()      # parts waiting for transcription
        self.part_pending = 0                            # parts queued or being transcribed
        self.part_cur: dict | None = None                # the part being transcribed right now
        self.chunk_seconds = 0
        self.root_dir = ms.DEFAULT_ROOT                 # the output folder
        self.meeting_dirs: dict[Path, Path] = {}        # audio file -> its meeting folder

        root.title("Meeting Recorder")
        root.resizable(False, False)
        frm = ttk.Frame(root, padding=12)
        frm.grid()

        self.time_var = tk.StringVar(value="00:00:00")
        ttk.Label(frm, textvariable=self.time_var, font=("Segoe UI", 28)).grid(
            row=0, column=0, columnspan=3, pady=(0, 6))

        self.bars = {}
        for r, (key, label) in enumerate((("mic", "Microphone"), ("sys", "System audio")), 1):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w")
            bar = ttk.Progressbar(frm, length=220, maximum=100)
            bar.grid(row=r, column=1, columnspan=2, padx=(8, 0), pady=2)
            self.bars[key] = bar

        # Input device pickers (filled by refresh_devices)
        self.mic_var = tk.StringVar()
        self.sys_var = tk.StringVar()
        self.mic_map: dict[str, tuple] = {}
        self.sys_map: dict[str, tuple] = {}
        ttk.Label(frm, text="Mic device").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.mic_box = ttk.Combobox(frm, textvariable=self.mic_var, state="readonly", width=38)
        self.mic_box.grid(row=3, column=1, columnspan=2, padx=(8, 0), pady=(8, 0), sticky="ew")
        ttk.Label(frm, text="System audio").grid(row=4, column=0, sticky="w", pady=(2, 0))
        self.sys_box = ttk.Combobox(frm, textvariable=self.sys_var, state="readonly", width=38)
        self.sys_box.grid(row=4, column=1, columnspan=2, padx=(8, 0), pady=(2, 0), sticky="ew")
        self.refresh_btn = ttk.Button(frm, text="Refresh devices", command=self.refresh_devices)
        self.refresh_btn.grid(row=5, column=1, columnspan=2, sticky="e", pady=(2, 0))

        self.duck = tk.BooleanVar(value=False)
        self.duck_cb = ttk.Checkbutton(
            frm, text="Hybrid meeting: lower mic while remote audio plays", variable=self.duck)
        self.duck_cb.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Separate channels need both a microphone and system audio: the checkbox is unchecked
        # and disabled while either source is Off (see update_channel_option). stereo_pref is
        # the user's own choice, restored when both sources are on again.
        self.stereo_pref = True
        self.stereo = tk.BooleanVar(value=True)
        self.stereo_cb = ttk.Checkbutton(
            frm, text="Keep mic and system audio on separate channels (to label 'You')",
            variable=self.stereo, command=self.on_stereo_toggle)
        self.stereo_cb.grid(row=7, column=0, columnspan=3, sticky="w")
        self.mic_var.trace_add("write", self.update_channel_option)
        self.sys_var.trace_add("write", self.update_channel_option)

        self.status = tk.StringVar(value="Ready")

        # Optional descriptive name, used in the file name: <timestamp>_<name>.mp3
        self.rec_name = tk.StringVar()
        name_frm = ttk.Frame(frm)
        name_frm.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(name_frm, text="Name (optional)").pack(side="left")
        self.name_entry = ttk.Entry(name_frm, textvariable=self.rec_name)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.transcribe = tk.BooleanVar(value=True)
        self.transcribe_cb = ttk.Checkbutton(frm, text="Transcribe after stopping",
                                             variable=self.transcribe)
        self.transcribe_cb.grid(row=9, column=0, columnspan=3, sticky="w", pady=(10, 0))
        # Which transcription to run after stopping: plain text, or text labelled per speaker
        self.mode = tk.StringVar(value="normal")
        mode_frm = ttk.Frame(frm)
        mode_frm.grid(row=10, column=0, columnspan=3, sticky="w", padx=(18, 0))
        self.radio_normal = ttk.Radiobutton(mode_frm, text="Normal", value="normal",
                                            variable=self.mode)
        self.radio_normal.pack(side="left")
        self.radio_speakers = ttk.Radiobutton(mode_frm, text="With speakers", value="speakers",
                                              variable=self.mode)
        self.radio_speakers.pack(side="left", padx=(12, 0))
        self.lang = tk.StringVar(value="nl")
        self.model = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Label(frm, text="Language").grid(row=11, column=0, sticky="w", pady=(4, 0))
        self.lang_box = ttk.Combobox(frm, textvariable=self.lang, values=LANGUAGES, width=8)
        self.lang_box.grid(row=11, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Label(frm, text="Model").grid(row=12, column=0, sticky="w")
        self.model_box = ttk.Combobox(frm, textvariable=self.model, values=MODELS, width=8,
                                      state="readonly")
        self.model_box.grid(row=12, column=1, sticky="w", padx=(8, 0))
        self.format = tk.StringVar(value=next(iter(FORMATS)))
        ttk.Label(frm, text="Recording").grid(row=13, column=0, sticky="w")
        self.format_box = ttk.Combobox(frm, textvariable=self.format, values=list(FORMATS),
                                       width=34, state="readonly")
        self.format_box.grid(row=13, column=1, columnspan=2, sticky="w", padx=(8, 0))
        # Split recording: every N minutes a new part file starts and the finished part is
        # transcribed in the background (queued when the transcription is slower than that)
        self.chunk_var = tk.StringVar(value="5")
        chunk_frm = ttk.Frame(frm)
        chunk_frm.grid(row=14, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(chunk_frm, text="Also transcribe while recording, every").pack(side="left")
        self.chunk_spin = ttk.Spinbox(chunk_frm, from_=0, to=60, width=4, textvariable=self.chunk_var)
        self.chunk_spin.pack(side="left", padx=(6, 0))
        ttk.Label(chunk_frm, text="min (0 = off)").pack(side="left", padx=(4, 0))

        # One output folder; Recordings, Transcripts and Logs are subfolders of it
        self.root_dir_var = tk.StringVar(value=str(self.root_dir))
        ttk.Label(frm, text="Output folder").grid(row=15, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(frm, textvariable=self.root_dir_var, state="readonly", width=34).grid(
            row=15, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))
        self.dir_btn = ttk.Button(frm, text="…", width=3, command=self.pick_dir)
        self.dir_btn.grid(row=15, column=2, padx=(4, 0), pady=(4, 0))
        self.dir_btns = [self.dir_btn]
        ttk.Label(frm, text="Every recording gets its own subfolder (audio, transcript, log).",
                  foreground="#666666").grid(row=16, column=0, columnspan=3, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=17, column=0, columnspan=3, pady=(12, 0), sticky="ew")
        self.pick_btn = ttk.Button(frm, text="Transcribe a recording…", command=self.pick_recording)
        self.pick_btn.grid(row=18, column=0, columnspan=3, pady=(6, 0), sticky="ew")
        self.open_btn = ttk.Button(frm, text="Open last transcription", command=self.open_last)
        self.open_btn.grid(row=19, column=0, columnspan=3, pady=(6, 0), sticky="ew")

        # Feedback ("Saved ...", errors, warnings) always at the very bottom, clearly headed
        style = ttk.Style(root)
        style.configure("Status.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        status_frm = ttk.LabelFrame(frm, text="Status", style="Status.TLabelframe", padding=(8, 4))
        status_frm.grid(row=20, column=0, columnspan=3, pady=(14, 0), sticky="ew")
        ttk.Label(status_frm, textvariable=self.status, wraplength=345).pack(anchor="w", fill="x")
        # Transcription progress/result: its own line so it never overwrites the recording status
        self.tx_events: "queue.Queue[tuple]" = queue.Queue()   # from the transcription threads
        self.jobs: dict[int, dict] = {}
        self.job_seq = 0
        self.tx_status = tk.StringVar(value="")
        self.tx_label = ttk.Label(status_frm, textvariable=self.tx_status, wraplength=345)
        self.log_btn = ttk.Button(frm, text="Open log", command=self.open_log)
        self.log_btn.grid(row=21, column=0, columnspan=3, pady=(6, 0), sticky="ew")
        self.btn = ttk.Button(btns, text="● Start recording", command=self.toggle)
        self.btn.pack(side="left", expand=True, fill="x")
        self.tray_btn = ttk.Button(btns, text="Minimize to tray", command=self.to_tray)
        self.tray_btn.pack(side="left", padx=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self.on_unmap)
        self.pa = None
        self.missing, self.can = check_requirements()
        self.apply_settings(cli or {})
        self.apply_requirements()
        self.update_open_btn()
        self.cur_log: Path | None = None               # log of the activity the Status box shows
        self.update_log_btn()
        self.status.trace_add("write", lambda *_: self.log(self.cur_log, self.status.get()))
        if self.can["record"]:
            self.refresh_devices()
        self.attach_persistence()
        self.loading = False
        self.poll()

        if autostart:
            self.start()
        if start_in_tray and pystray is not None:
            self.to_tray()

    # ── Saved settings ──────────────────────────────────────────────────────────
    def apply_settings(self, cli: dict):
        """Fill the window from the saved settings; values given on the command line (cli) win.
        Only changes made in the window afterwards are saved, so a command-line value is used
        for this run without replacing the saved one."""
        saved = ms.load(self.settings_path)
        get = lambda key, default: ms.resolve(key, cli.get(key), saved, default)   # noqa: E731
        self.pref_mic = get("mic", "default")
        self.pref_sys = get("system", "default")
        self.duck.set(get("duck", False))
        self.stereo_pref = get("separate_channels", True)
        self.stereo.set(self.stereo_pref)
        self.transcribe.set(get("transcribe", True))
        self.mode.set(get("mode", "normal"))
        self.lang.set(get("language", "nl"))
        self.model.set(get("model", DEFAULT_MODEL))
        fmt = get("format", "mp3")
        self.format.set(next((k for k, v in FORMATS.items() if v == fmt), next(iter(FORMATS))))
        self.chunk_var.set(str(get("chunk_minutes", 5)))
        self.set_root(Path(get("output_root", str(ms.DEFAULT_ROOT))))
        if cli.get("name"):
            self.rec_name.set(cli["name"])

    def set_root(self, root: Path):
        """Set the output folder (every meeting gets a subfolder in it)."""
        self.root_dir = root
        if hasattr(self, "root_dir_var"):
            self.root_dir_var.set(str(root))

    def meeting_dir(self, audio: Path) -> Path:
        """The folder that holds the transcript and log of an audio file: its own folder when it
        is a recording inside the output folder; otherwise a new <timestamp>_<name> folder there."""
        if audio not in self.meeting_dirs:
            if audio.parent.parent == self.root_dir:
                folder = audio.parent
            else:
                folder = self.root_dir / f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{audio.stem}"
            self.meeting_dirs[audio] = folder
        return self.meeting_dirs[audio]

    def save_setting(self, key: str, value):
        if not self.loading:
            ms.save_key(key, value, self.settings_path)

    def device_setting(self, var, mapping) -> str:
        """What to store for a device box: "default", "off" or the device name."""
        kind, _ = mapping.get(var.get(), ("default", None))
        return var.get() if kind == "dev" else kind

    def display_for(self, pref: str, mapping: dict) -> str:
        """The entry of a device box that a stored setting refers to (else the default entry)."""
        if pref == "off":
            return OFF
        names = [k for k, (kind, _) in mapping.items() if kind == "dev"]
        found = ms.match_name(pref, names) if pref != "default" else None
        return found or next(iter(mapping))

    def attach_persistence(self):
        """Save a setting as soon as the user changes it in the window."""
        def on_device(var, mapping_name, pref_name, key):
            def cb(*_):
                if self.loading:
                    return
                value = self.device_setting(var, getattr(self, mapping_name))
                setattr(self, pref_name, value)
                self.save_setting(key, value)
            var.trace_add("write", cb)
        on_device(self.mic_var, "mic_map", "pref_mic", "mic")
        on_device(self.sys_var, "sys_map", "pref_sys", "system")

        def simple(var, key, conv):
            def cb(*_):
                try:
                    value = conv(var.get())
                except (ValueError, tk.TclError):
                    return                          # half-typed value: not saved
                self.save_setting(key, value)
            var.trace_add("write", cb)
        simple(self.duck, "duck", bool)
        simple(self.transcribe, "transcribe", bool)
        simple(self.mode, "mode", str)
        simple(self.lang, "language", lambda v: v.strip() or None)
        simple(self.model, "model", lambda v: v.strip() or None)
        simple(self.format, "format", lambda v: FORMATS[v])
        simple(self.chunk_var, "chunk_minutes", lambda v: max(0, min(60, int(v))))

    # ── Tray ────────────────────────────────────────────────────────────────────
    def ensure_icon(self):
        if self.icon is not None or pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show window", lambda i, m: self.cmds.put("show"), default=True),
            pystray.MenuItem(
                lambda item: "Stop recording" if self.recording else "Start recording",
                lambda i, m: self.cmds.put("toggle")),
            pystray.MenuItem("Quit", lambda i, m: self.cmds.put("quit")),
        )
        self.icon = pystray.Icon("meeting-recorder", tray_image(self.recording),
                                 "Meeting Recorder", menu)
        self.icon.run_detached()

    def refresh_icon(self):
        if self.icon is not None:
            self.icon.icon = tray_image(self.recording)
            m, s = divmod(int(self.elapsed), 60)
            h, m = divmod(m, 60)
            self.icon.title = (f"Recording {h:02d}:{m:02d}:{s:02d}" if self.recording
                               else "Meeting Recorder (idle)")
            self.icon.update_menu()

    def to_tray(self):
        self.ensure_icon()
        if self.icon is not None:
            self.root.withdraw()
            self.refresh_icon()

    def on_unmap(self, event):
        """The window's own minimize button sends the window to the tray, not the taskbar."""
        if (event.widget is self.root and not self.closing and pystray is not None
                and self.root.state() == "iconic"):
            self.to_tray()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── Devices ─────────────────────────────────────────────────────────────────
    def refresh_devices(self):
        """(Re)read the input devices; keep the previous choice if it still exists."""
        if self.recording:
            return
        pa = rm.pyaudio.PyAudio()
        try:
            mics, loops = rm.list_sources(pa)
            try:
                def_mic = rm.default_mic(pa)["name"]
            except Exception:
                def_mic = "none found"
            try:
                def_sys = rm.default_loopback(pa)["name"]
            except Exception:
                def_sys = "none found"
        finally:
            pa.terminate()

        self.mic_map = {f"Default ({def_mic})": ("default", None)}
        self.mic_map.update({f"{d['name']}": ("dev", int(d["index"])) for d in mics})
        self.mic_map[OFF] = ("off", None)
        self.sys_map = {f"Default ({def_sys})": ("default", None)}
        self.sys_map.update({f"{d['name']}": ("dev", int(d["index"])) for d in loops})
        self.sys_map[OFF] = ("off", None)

        was_loading, self.loading = self.loading, True      # fallbacks are not user choices
        try:
            for box, var, mapping, pref in ((self.mic_box, self.mic_var, self.mic_map, self.pref_mic),
                                            (self.sys_box, self.sys_var, self.sys_map, self.pref_sys)):
                box["values"] = list(mapping)
                if var.get() not in mapping:
                    var.set(self.display_for(pref, mapping))   # saved choice, else the default
        finally:
            self.loading = was_loading

    def selected_devices(self) -> dict:
        mic_kind, mic_idx = self.mic_map.get(self.mic_var.get(), ("default", None))
        sys_kind, sys_idx = self.sys_map.get(self.sys_var.get(), ("default", None))
        return {"mic": mic_idx, "loopback": sys_idx,
                "no_mic": mic_kind == "off", "no_system": sys_kind == "off"}

    def apply_requirements(self):
        """Grey out what cannot work and list in the Status box what is missing."""
        can = self.can
        if not can["record"]:
            self.btn.state(["disabled"])
            self.refresh_btn.state(["disabled"])
            for box in (self.mic_box, self.sys_box, self.format_box):
                box.config(state="disabled")
            for cb in (self.duck_cb, self.stereo_cb):
                cb.state(["disabled"])
        if not can["transcribe"]:
            self.transcribe.set(False)
            for w in (self.transcribe_cb, self.radio_normal, self.radio_speakers, self.pick_btn):
                w.state(["disabled"])
            for box in (self.lang_box, self.model_box):
                box.config(state="disabled")
            self.chunk_spin.config(state="disabled")
        elif not can["speakers"]:
            self.mode.set("normal")
            self.radio_speakers.state(["disabled"])
        if not can["tray"] or pystray is None:
            self.tray_btn.state(["disabled"])
        report = missing_report(self.missing)
        if report:
            self.status.set(report)

    def on_stereo_toggle(self):
        self.stereo_pref = self.stereo.get()
        self.save_setting("separate_channels", self.stereo_pref)

    def update_channel_option(self, *_):
        """Keep the 'separate channels' checkbox consistent with the selected sources.

        Needs both a microphone and system audio. While either is set to Off the box is
        unchecked and disabled (the recording is mono); once both are on again it returns to
        the user's last choice.
        """
        mic_off = self.mic_map.get(self.mic_var.get(), ("", None))[0] == "off"
        sys_off = self.sys_map.get(self.sys_var.get(), ("", None))[0] == "off"
        if mic_off or sys_off:
            self.stereo.set(False)
            self.stereo_cb.state(["disabled"])
        else:
            self.stereo.set(self.stereo_pref)
            if not self.recording:
                self.stereo_cb.state(["!disabled"])

    def set_controls(self, enabled: bool):
        state = "readonly" if enabled else "disabled"
        self.mic_box.config(state=state)
        self.sys_box.config(state=state)
        self.refresh_btn.state(["!disabled"] if enabled else ["disabled"])
        self.format_box.config(state="readonly" if enabled and self.can["record"] else "disabled")
        self.chunk_spin.config(state="normal" if enabled and self.can["transcribe"] else "disabled")
        for b in self.dir_btns:
            b.state(["!disabled"] if enabled else ["disabled"])
        self.duck_cb.state(["!disabled"] if enabled else ["disabled"])
        if enabled:
            self.update_channel_option()   # enabled only when both sources are on
        else:
            self.stereo_cb.state(["disabled"])

    # ── Recording ───────────────────────────────────────────────────────────────
    def toggle(self):
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.recording or (self.thread and self.thread.is_alive()):
            return
        self.cur_log = None                # failures before a file exists are not logged
        if not self.can["record"]:
            self.status.set(missing_report(self.missing))
            self.show()
            return
        choice = self.selected_devices()
        if choice["no_mic"] and choice["no_system"]:
            self.status.set("Nothing to record: both sources are set to Off.")
            self.show()
            return
        self.pa = rm.pyaudio.PyAudio()
        try:
            sources = rm.open_sources(self.pa, **choice)
        except Exception as e:
            self.pa.terminate()
            self.status.set(f"Could not open audio device: {e}")
            self.show()
            return
        self.name = clean_name(self.rec_name.get())
        self.mp3_path = rm.build_name(self.name, FORMATS[self.format.get()], self.root_dir)
        self.cur_log = self.log_path_for(self.mp3_path)
        self.duck_enabled = self.duck.get()   # read here: Tk variables belong to the UI thread
        self.stereo_enabled = self.stereo.get()
        self.start_session()
        self.stop_evt.clear()
        self.result = None
        self.recording = True
        self.elapsed = 0.0
        self.btn.config(text="■ Stop recording")
        self.set_controls(False)
        self.name_entry.state(["disabled"])
        self.status.set(f"Recording to {self.mp3_path.name}" if not self.session else
                        f"Recording to {self.mp3_path.stem} in parts of {self.chunk_seconds // 60} min "
                        f"(part files are transcribed in the background)")
        self.thread = threading.Thread(target=self.worker, args=(sources,), daemon=True)
        self.thread.start()
        self.refresh_icon()

    def worker(self, sources):
        err = None
        silent = []
        try:
            def on_tick(elapsed, srcs):
                self.elapsed = elapsed
                for s in srcs:
                    self.peaks[s.label] = s.peak

            rm.record(sources, self.mp3_path, self.stop_evt, on_tick=on_tick,
                      duck=self.duck_enabled, stereo=self.stereo_enabled,
                      chunk_seconds=self.chunk_seconds,
                      on_chunk=self.on_chunk if self.chunk_seconds else None)
            silent = [s.label for s in sources if s.max_peak < 0.001]
        except Exception as e:  # noqa: BLE001 - report anything to the UI
            err = str(e)
        finally:
            for s in sources:
                s.close()
            self.pa.terminate()
        self.result = {"error": err, "silent": silent}

    def stop(self):
        if self.recording:
            self.status.set("Saving ...")
            self.stop_evt.set()

    def finish(self):
        """Called from the UI thread once the worker has finished."""
        res, self.result = self.result, None
        self.recording = False
        self.peaks = {"mic": 0.0, "sys": 0.0}
        self.btn.config(text="● Start recording")
        self.set_controls(True)
        self.name_entry.state(["!disabled"])
        path = self.mp3_path
        sess = self.session
        if sess is not None:
            sess["recording_done"] = True
            if res["error"]:
                self.status.set(f"Error: {res['error']}")
            elif not sess["parts"]:
                self.status.set("No audio was saved.")
            else:
                msg = f"Recording stopped: {len(sess['parts'])} part(s) of {path.stem}"
                if res["silent"]:
                    msg += f" — warning: silent source(s): {', '.join(res['silent'])}"
                self.status.set(msg)
            self.maybe_finalize()
        elif res["error"]:
            self.status.set(f"Error: {res['error']}")
        elif not path.exists() or path.stat().st_size == 0:
            self.status.set("No audio was saved.")
        else:
            msg = f"Saved {path.name} ({path.stat().st_size / 1048576:.1f} MB)"
            if res["silent"]:
                msg += f" — warning: silent source(s): {', '.join(res['silent'])}"
            self.status.set(msg)
            if self.transcribe.get():
                self.launch_transcription(path, name=self.name or "meeting")
        self.refresh_icon()
        if self.quit_after_stop:
            self.quit()

    def pick_recording(self):
        """Choose an existing audio file (default: the output folder) and transcribe it
        with the mode, language and model currently selected in the window."""
        start = self.root_dir if self.root_dir.is_dir() else self.root_dir.parent
        chosen = filedialog.askopenfilename(parent=self.root, title="Choose a recording to transcribe",
                                            initialdir=str(start), filetypes=AUDIO_TYPES)
        if not chosen:
            return  # cancelled
        path = Path(chosen)
        self.cur_log = self.log_path_for(path)
        self.status.set(f"Selected {path.name}")
        self.launch_transcription(path, name=path.stem)

    def pick_dir(self):
        """Choose the output folder (every recording gets its own subfolder in it)."""
        cur = self.root_dir
        chosen = filedialog.askdirectory(
            parent=self.root, mustexist=False,
            title="Choose the output folder (one subfolder per recording is created in it)",
            initialdir=str(cur if cur.is_dir() else cur.parent))
        if not chosen:
            return
        self.set_root(Path(chosen))
        self.save_setting("output_root", str(self.root_dir))
        self.update_open_btn()
        self.update_log_btn()

    def last_transcript(self) -> Path | None:
        """The newest transcript in the meeting folders of the output folder, or None."""
        files = [f for f in self.root_dir.glob("*/*.txt")
                 if f.is_file() and not f.name.endswith(".log.txt")]
        return max(files, key=lambda f: f.stat().st_mtime, default=None)

    def update_open_btn(self):
        """'Open last transcription' is greyed out while a transcription runs or none exists."""
        ok = not self.jobs and self.last_transcript() is not None
        self.open_btn.state(["!disabled"] if ok else ["disabled"])

    def open_last(self):
        path = self.last_transcript()
        if path is None:
            self.status.set("No transcription found yet.")
            return
        try:
            os.startfile(path)
        except OSError as e:
            self.status.set(f"Could not open {path.name}: {e}")

    # ── Log file ────────────────────────────────────────────────────────────────
    def log_path_for(self, audio: Path) -> Path:
        """<meeting folder>/<audio name without extension>.log.txt"""
        return self.meeting_dir(audio) / f"{audio.stem}.log.txt"

    def log(self, path: Path | None, text: str):
        """Append a timestamped entry (multi-line text is indented) to a log file."""
        if path is None or not text:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        body = text.replace("\n", "\n" + " " * 21)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{stamp}  {body}\n")
        except OSError:
            return                                     # logging must never break the window
        self.log_btn.state(["!disabled"])

    def newest_log(self) -> Path | None:
        files = list(self.root_dir.glob("*/*.log.txt")) if self.root_dir.is_dir() else []
        return max(files, key=lambda f: f.stat().st_mtime, default=None)

    def update_log_btn(self):
        self.log_btn.state(["!disabled"] if self.newest_log() else ["disabled"])

    def open_log(self):
        running = [j["log"] for j in self.jobs.values() if j["log"].exists()]
        path = running[-1] if running else self.newest_log()
        if path is None:
            self.status.set("No log found yet.")
            return
        try:
            os.startfile(path)
        except OSError as e:
            self.status.set(f"Could not open {path.name}: {e}")

    def launch_transcription(self, path, name="meeting"):
        """Transcribe in a hidden background process; progress and result show in the Status box."""
        with_speakers = self.mode.get() == "speakers"
        cmd = rm.transcribe_command(path, name, self.lang.get() or None,
                                    self.model.get() or None, speakers=with_speakers,
                                    output_dir=self.meeting_dir(path))
        # Use python.exe (not pythonw.exe): the scripts print their progress to stderr
        cmd[0] = str(Path(sys.executable).with_name("python.exe"))
        self.job_seq += 1
        jid = self.job_seq
        log = self.log_path_for(path)
        self.jobs[jid] = {"file": path.name, "start": time.monotonic(), "stage": "Starting",
                          "kind": "with speakers" if with_speakers else "normal", "log": log}
        self.log(log, f"Transcribing {path.name} ({self.jobs[jid]['kind']}, language "
                      f"{self.lang.get() or 'auto'}, model {self.model.get() or 'default'})")
        threading.Thread(target=self.run_transcription, args=(jid, cmd), daemon=True).start()
        self.update_tx_progress()
        self.update_open_btn()

    def run_transcription(self, jid: int, cmd: list):
        """Worker thread: run the script without a console window and report back via tx_events."""
        ok, detail = self.run_script(cmd, lambda line: self.tx_events.put(("stage", jid, line)))
        self.tx_events.put(("done", jid, ok, detail))

    def run_script(self, cmd: list, on_stage) -> tuple[bool, str]:
        """Run a transcribe script (no console window), call on_stage(line) for its progress lines
        and return (ok, detail): detail is the saved transcript's file name, a short message such
        as "no speech was detected", or the error."""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            return False, f"could not start the transcription: {e}"
        # The transcript itself goes to stdout and to the file; drain it so the pipe never fills.
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
        saved, tail = None, []
        for raw in proc.stderr:
            line = ANSI.sub("", raw).strip()
            if not line:
                continue
            if line.startswith(STAGES):
                on_stage(line)
            m = re.match(r"Saved\s*:\s*(.+)$", line)
            if m:
                saved = m.group(1).strip()
            tail.append(line)
            tail = tail[-12:]
        code = proc.wait()
        if code == 0 and saved:
            return True, Path(saved).name
        if code == 0 and any("No speech detected" in l for l in tail):
            return True, "no speech was detected"
        if code == 0:
            return False, "the script finished without saving a transcript"
        errors = [l for l in tail if l.startswith("Error") or "Error:" in l]
        return False, (errors or tail or [f"exit code {code}"])[-1]

    # ── Split recording: parts, queue, combined transcript, merge ───────────────
    def start_session(self):
        """Prepare split recording (called from start() on the UI thread; Tk variables are read
        here). Active only when the split time is > 0 and transcription is available."""
        self.session = None
        self.chunk_seconds = 0
        try:
            minutes = int(self.chunk_var.get())
        except ValueError:
            minutes = 0
        if minutes <= 0 or not self.can["transcribe"]:
            return
        self.chunk_seconds = min(minutes, 60) * 60
        speakers = self.mode.get() == "speakers"
        self.session = {
            "name": self.name or "meeting", "final": self.mp3_path,
            "tx_dir": self.mp3_path.parent, "combined": self.mp3_path.parent / f"{self.mp3_path.stem}.txt",
            "parts": [], "failed": False, "recording_done": False, "merging": False,
            "speakers": speakers, "lang": self.lang.get() or None, "model": self.model.get() or None,
            "log": self.log_path_for(self.mp3_path),
        }
        self.part_q = queue.Queue()
        self.part_pending = 0
        self.part_cur = None
        self.log(self.session["log"],
                 f"Split recording every {minutes} min; transcribing each part in the background "
                 f"({'with speakers' if speakers else 'normal'}, language "
                 f"{self.session['lang'] or 'auto'}, model {self.session['model'] or 'default'}); "
                 f"combined transcript: {self.session['combined'].name}")
        threading.Thread(target=self.part_runner, args=(self.session, self.part_q),
                         daemon=True).start()

    def on_chunk(self, path: Path, index: int, offset: float, duration: float):
        """Recorder thread: a part file is finished."""
        self.tx_events.put(("part", path, index, offset, duration))

    def part_runner(self, sess: dict, jobs: "queue.Queue"):
        """Worker thread: transcribe the queued parts one after the other and append each
        result to the combined transcript."""
        while True:
            job = jobs.get()
            if job is None:
                return
            path, index, offset, duration = job
            self.tx_events.put(("part_start", index))
            name = f"{sess['name']}_part{index:02d}"
            cmd = rm.transcribe_command(path, name, sess["lang"], sess["model"],
                                        speakers=sess["speakers"], output_dir=sess["tx_dir"])
            cmd[0] = str(Path(sys.executable).with_name("python.exe"))
            ok, detail = self.run_script(
                cmd, lambda line, i=index: self.tx_events.put(("part_stage", i, line)))
            text = None
            if ok and detail.endswith(".txt"):
                tfile = sess["tx_dir"] / detail
                try:
                    text = tfile.read_text(encoding="utf-8").strip()
                    tfile.unlink()                  # its text now lives in the combined file
                except OSError as e:
                    ok, detail = False, f"could not read {detail}: {e}"
            if ok and text and sess["speakers"]:
                text = shift_stamps(text, offset)
            header = f"--- Part {index} ({hms(offset)} - {hms(offset + duration)}) ---"
            body = text if text else ("(no speech)" if ok else f"(transcription failed: {detail})")
            try:
                sess["combined"].parent.mkdir(parents=True, exist_ok=True)
                with open(sess["combined"], "a", encoding="utf-8") as f:
                    f.write(f"{header}\n{body}\n\n")
            except OSError as e:
                ok, detail = False, f"could not write {sess['combined'].name}: {e}"
            self.tx_events.put(("part_done", index, ok, detail))

    def handle_part_event(self, kind: str, rest: tuple):
        sess = self.session
        if sess is None:
            return
        log = sess["log"]
        if kind == "part":
            path, index, offset, duration = rest
            sess["parts"].append((path, duration))
            if duration < MIN_PART:
                self.log(log, f"Part {index} ({duration:.1f} s) is too short to transcribe; "
                              f"it is only added to the merged recording")
                return
            self.part_pending += 1
            self.log(log, f"Part {index} saved ({hms(offset)} - {hms(offset + duration)}); "
                          f"{self.part_pending - 1} part(s) ahead in the queue")
            self.part_q.put((path, index, offset, duration))
        elif kind == "part_start":
            self.part_cur = {"index": rest[0], "stage": "Starting", "start": time.monotonic()}
            self.log(log, f"Transcribing part {rest[0]}")
        elif kind == "part_stage":
            if self.part_cur is not None:
                self.part_cur["stage"] = rest[1]
            self.log(log, f"Part {rest[0]}: {rest[1]}")
        elif kind == "part_done":
            index, ok, detail = rest
            self.part_pending -= 1
            self.part_cur = None
            if not ok:
                sess["failed"] = True
            self.log(log, f"Part {index} " + ("done" if ok else f"FAILED: {detail[:300]}"))
            self.update_open_btn()
        elif kind == "merged":
            self.log(log, rest[0])
            self.session = None
            ok = not sess["failed"]
            self.set_tx(f"Transcription finished: {sess['combined'].name}\n{rest[0]}" if ok else
                        f"Some parts failed, see {sess['combined'].name}.\n{rest[0]}",
                        "ok" if ok else "fail")
            self.update_open_btn()
            self.update_log_btn()
            self.show()
            return
        self.maybe_finalize()

    def maybe_finalize(self):
        """Once recording has stopped and every part is transcribed: merge the parts."""
        sess = self.session
        if sess is None or not sess["recording_done"] or self.part_pending or sess["merging"]:
            return
        sess["merging"] = True
        self.part_q.put(None)                       # ends the runner thread
        if not sess["parts"]:
            self.session = None
            return
        self.set_tx(f"Merging {len(sess['parts'])} part(s) into {sess['final'].name} ...")
        threading.Thread(target=self.merge_worker, args=(sess,), daemon=True).start()

    def merge_worker(self, sess: dict):
        """Worker thread: join the part files into the final recording; remove the parts only
        when that worked and every part was transcribed."""
        parts = [p for p, _ in sess["parts"]]
        final = sess["final"]
        try:
            if len(parts) == 1:
                parts[0].replace(final)             # nothing to join: just give it the final name
                parts = []
                detail = f"Recording saved as {final.name}"
            else:
                seconds = rm.merge_audio(parts, final)
                expected = sum(d for _, d in sess["parts"])
                if abs(seconds - expected) > 2.0 or final.stat().st_size == 0:
                    raise RuntimeError(f"merged recording is {seconds:.1f} s, expected {expected:.1f} s")
                detail = f"Recording merged into {final.name}"
            if parts and not sess["failed"]:
                for p in parts:
                    p.unlink(missing_ok=True)
                detail += " (part files removed)"
            elif parts:
                detail += " (part files kept because a part failed)"
        except Exception as e:  # noqa: BLE001 - report anything to the UI
            if len(parts) > 1 and final.exists():
                final.unlink(missing_ok=True)       # the incomplete merge result
            detail = f"Could not merge the parts ({e}); the part files are kept"
        self.tx_events.put(("merged", detail))

    def set_tx(self, text: str, kind: str = "busy"):
        """Show (or hide, when empty) the transcription line in the Status box."""
        if text and not self.tx_label.winfo_ismapped():
            self.tx_label.pack(anchor="w", fill="x", pady=(6, 0))
        elif not text and self.tx_label.winfo_ismapped():
            self.tx_label.pack_forget()
        self.tx_label.config(foreground=TX_COLORS[kind])
        if self.tx_status.get() != text:
            self.tx_status.set(text)

    def update_part_progress(self):
        cur = self.part_cur
        m, s = divmod(int(time.monotonic() - cur["start"]), 60)
        text = f"Transcribing part {cur['index']}: {cur['stage']} [{m:02d}:{s:02d}]"
        waiting = self.part_pending - 1
        if waiting > 0:
            text += f"\n{waiting} more part(s) waiting in the queue"
        self.set_tx(text)

    def update_tx_progress(self):
        if self.session is not None and self.part_cur is not None:
            self.update_part_progress()
            return
        if not self.jobs:
            return
        if len(self.jobs) == 1:
            job = next(iter(self.jobs.values()))
            m, s = divmod(int(time.monotonic() - job["start"]), 60)
            self.set_tx(f"Transcribing {job['file']} ({job['kind']}): {job['stage']} [{m:02d}:{s:02d}]")
        else:
            self.set_tx(f"{len(self.jobs)} transcriptions running ...")

    def handle_tx_events(self):
        finished = False
        while True:
            try:
                kind, jid, *rest = self.tx_events.get_nowait()
            except queue.Empty:
                break
            if kind.startswith("part") or kind == "merged":
                self.handle_part_event(kind, (jid, *rest))
                continue
            job = self.jobs.get(jid)
            if kind == "stage" and job is not None:
                job["stage"] = rest[0]
                self.log(job["log"], rest[0])
            elif kind == "done" and job is not None:
                ok, detail = rest
                del self.jobs[jid]
                finished = True
                self.log(job["log"], (f"Transcription finished: {detail}" if ok
                                      else f"Transcription failed: {detail[:300]}"))
                if ok:
                    self.set_tx(f"Transcription finished: {job['file']}\nSaved as {detail}"
                                if detail.endswith(".txt") else
                                f"Transcription finished: {job['file']} ({detail})", "ok")
                else:
                    self.set_tx(f"Transcription failed: {job['file']}\n{detail[:300]}", "fail")
        if finished:
            self.update_open_btn()
            if self.jobs:
                self.update_tx_progress()      # others are still running: keep showing them
            self.show()                        # back to the window (also out of the tray)
        else:
            self.update_tx_progress()

    # ── Event loop ──────────────────────────────────────────────────────────────
    def poll(self):
        while True:
            try:
                cmd = self.cmds.get_nowait()
            except queue.Empty:
                break
            if cmd == "show":
                self.show()
            elif cmd == "toggle":
                self.toggle()
            elif cmd == "quit":
                self.request_quit()
        self.handle_tx_events()
        if self.recording:
            m, s = divmod(int(self.elapsed), 60)
            h, m = divmod(m, 60)
            self.time_var.set(f"{h:02d}:{m:02d}:{s:02d}")
            if self.icon is not None and int(self.elapsed * 10) % 50 == 0:
                self.refresh_icon()
            if self.result is not None:
                self.finish()
        if self.closing:
            return
        for key, bar in self.bars.items():
            bar["value"] = min(100.0, self.peaks[key] ** 0.5 * 100.0)
        self.root.after(100, self.poll)

    def on_close(self):
        if self.recording and pystray is not None:
            self.to_tray()          # keep recording in the background
        else:
            self.request_quit()

    def request_quit(self):
        sess = self.session
        if sess is not None and (self.recording or self.part_pending or sess["merging"]) \
                and not messagebox.askyesno(
                    "Meeting Recorder",
                    "Parts of this recording are still being recorded, transcribed or merged.\n"
                    "If you quit now the rest is not transcribed (the part files stay in the "
                    "recordings folder).\n\nQuit anyway?", parent=self.root):
            return
        if self.recording:
            self.quit_after_stop = True
            self.stop()
        else:
            self.quit()

    def quit(self):
        self.closing = True
        if self.icon is not None:
            self.icon.stop()
        self.root.destroy()


def main() -> None:
    ap = argparse.ArgumentParser(description="Meeting Recorder GUI")
    ap.add_argument("--autostart", action="store_true", help="start recording immediately")
    ap.add_argument("--tray", action="store_true", help="start minimized to the system tray")
    ap.add_argument("--settings", type=Path,
                    help="settings file to use (default: %%APPDATA%%\\WhisperMeetingRecorder\\settings.json)")
    ap.add_argument("--name", help="name for this recording (not saved)")
    ap.add_argument("--mic", help='microphone: "default", "off" or (part of) a device name')
    ap.add_argument("--system", help='system audio: "default", "off" or (part of) a device name')
    ap.add_argument("--duck", action=argparse.BooleanOptionalAction,
                    help="hybrid meeting: lower the microphone while remote audio plays")
    ap.add_argument("--separate-channels", action=argparse.BooleanOptionalAction,
                    help="keep microphone and system audio on separate channels")
    ap.add_argument("--transcribe", action=argparse.BooleanOptionalAction,
                    help="transcribe after stopping")
    ap.add_argument("--mode", choices=["normal", "speakers"], help="transcription mode")
    ap.add_argument("-l", "--language", help="transcription language, e.g. nl or en")
    ap.add_argument("--model", choices=MODELS, help="Whisper model size")
    ap.add_argument("--format", choices=["mp3", "wav"], help="recording format")
    ap.add_argument("--chunk-minutes", type=int, choices=range(0, 61), metavar="0-60",
                    help="transcribe while recording, every N minutes (0 = off)")
    ap.add_argument("--output-dir", type=Path,
                    help="the output folder; every recording gets its own subfolder in it")
    args = ap.parse_args()
    # Command-line values win over the saved settings for this run and are not saved.
    cli = {"name": args.name, "mic": args.mic, "system": args.system, "duck": args.duck,
           "separate_channels": args.separate_channels, "transcribe": args.transcribe,
           "mode": args.mode, "language": args.language, "model": args.model,
           "format": args.format, "chunk_minutes": args.chunk_minutes,
           "output_root": str(args.output_dir) if args.output_dir else None}

    if not single_instance():
        ctypes.windll.user32.MessageBoxW(0, "Meeting Recorder is already running "
                                            "(check the system tray).", "Meeting Recorder", 0x40)
        return
    root = tk.Tk()
    App(root, args.autostart, args.tray, cli, args.settings)
    root.mainloop()


if __name__ == "__main__":
    main()
