#!/usr/bin/env python3
"""
Meeting Recorder GUI — small window (and system-tray icon) around record_meeting.py

Usage:
    python scripts/record_meeting_gui.py              # open the window
    python scripts/record_meeting_gui.py --autostart  # open and start recording at once
    python scripts/record_meeting_gui.py --autostart --tray   # ... and start minimized to tray

Records microphone + system audio with the default devices to recordings/<timestamp>_meeting.mp3.
The window can be minimized to the system tray (the window's minimize button, the
"Minimize to tray" button, or closing the window while recording).
Tray icon: red = recording, grey = idle. Right-click for Show / Start / Stop / Quit.
After stopping, the recording can be transcribed automatically (runs in the background;
progress and the result appear in the Status box and the window comes to the front when it
is done): "Normal" runs transcribe_file.py, "With speakers" runs transcribe_speakers.py, which
labels who says what (needs the one-time Hugging Face token, see doc/transcribe_speakers.md).
"Transcribe a recording..." does the same for any existing audio file you pick (the dialog
opens in the recordings folder), using the mode, language and model selected in the window.
"Open last transcription" opens the newest transcript in the transcripts folder; it is greyed
out while a transcription is running in the background (or when there is no transcript yet).

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
from tkinter import filedialog, ttk

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None  # only the tray icon needs Pillow; reported at start-up

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record_meeting as rm  # importable even when its recording packages are missing
import requirements_check as rc

try:
    import pystray
except ImportError:
    pystray = None  # tray is optional; window still works

LANGUAGES = ["nl", "en", "fr", "de", "es", "it", "pt", "pl", "sv", "da", "no", "fi"]
MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
DEFAULT_MODEL = "medium"
OFF = "Off (don't record this source)"
ANSI = re.compile(r"\x1b\[[0-9;]*m")                     # colour codes in the scripts' output
STAGES = ("Loading", "Transcribing", "Identifying", "Language")   # progress lines worth showing
TRANSCRIPT_DIR = rm.RECORDINGS_DIR.parent / "transcripts"   # where the transcribe scripts save
TX_COLORS = {"busy": "#555555", "ok": "#1a7f37", "fail": "#c62828"}

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


def single_instance() -> bool:
    """True if this is the only running instance (named Windows mutex)."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "WhisperMeetingRecorderGUI")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


class App:
    def __init__(self, root: tk.Tk, autostart: bool, start_in_tray: bool):
        self.root = root
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

        btns = ttk.Frame(frm)
        btns.grid(row=13, column=0, columnspan=3, pady=(12, 0), sticky="ew")
        self.pick_btn = ttk.Button(frm, text="Transcribe a recording…", command=self.pick_recording)
        self.pick_btn.grid(row=14, column=0, columnspan=3, pady=(6, 0), sticky="ew")
        self.open_btn = ttk.Button(frm, text="Open last transcription", command=self.open_last)
        self.open_btn.grid(row=15, column=0, columnspan=3, pady=(6, 0), sticky="ew")

        # Feedback ("Saved ...", errors, warnings) always at the very bottom, clearly headed
        style = ttk.Style(root)
        style.configure("Status.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        status_frm = ttk.LabelFrame(frm, text="Status", style="Status.TLabelframe", padding=(8, 4))
        status_frm.grid(row=16, column=0, columnspan=3, pady=(14, 0), sticky="ew")
        ttk.Label(status_frm, textvariable=self.status, wraplength=345).pack(anchor="w", fill="x")
        # Transcription progress/result: its own line so it never overwrites the recording status
        self.tx_events: "queue.Queue[tuple]" = queue.Queue()   # from the transcription threads
        self.jobs: dict[int, dict] = {}
        self.job_seq = 0
        self.tx_status = tk.StringVar(value="")
        self.tx_label = ttk.Label(status_frm, textvariable=self.tx_status, wraplength=345)
        self.btn = ttk.Button(btns, text="● Start recording", command=self.toggle)
        self.btn.pack(side="left", expand=True, fill="x")
        self.tray_btn = ttk.Button(btns, text="Minimize to tray", command=self.to_tray)
        self.tray_btn.pack(side="left", padx=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self.on_unmap)
        self.pa = None
        self.missing, self.can = check_requirements()
        self.apply_requirements()
        self.update_open_btn()
        if self.can["record"]:
            self.refresh_devices()
        self.poll()

        if autostart:
            self.start()
        if start_in_tray and pystray is not None:
            self.to_tray()

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

        for box, var, mapping in ((self.mic_box, self.mic_var, self.mic_map),
                                  (self.sys_box, self.sys_var, self.sys_map)):
            box["values"] = list(mapping)
            if var.get() not in mapping:
                var.set(next(iter(mapping)))   # first entry = default

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
            for box in (self.mic_box, self.sys_box):
                box.config(state="disabled")
            for cb in (self.duck_cb, self.stereo_cb):
                cb.state(["disabled"])
        if not can["transcribe"]:
            self.transcribe.set(False)
            for w in (self.transcribe_cb, self.radio_normal, self.radio_speakers, self.pick_btn):
                w.state(["disabled"])
            for box in (self.lang_box, self.model_box):
                box.config(state="disabled")
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
        self.mp3_path = rm.build_name(None)
        self.duck_enabled = self.duck.get()   # read here: Tk variables belong to the UI thread
        self.stereo_enabled = self.stereo.get()
        self.stop_evt.clear()
        self.result = None
        self.recording = True
        self.elapsed = 0.0
        self.btn.config(text="■ Stop recording")
        self.set_controls(False)
        self.status.set(f"Recording to {self.mp3_path.name}")
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
                      duck=self.duck_enabled, stereo=self.stereo_enabled)
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
        path = self.mp3_path
        if res["error"]:
            self.status.set(f"Error: {res['error']}")
        elif not path.exists() or path.stat().st_size == 0:
            self.status.set("No audio was saved.")
        else:
            msg = f"Saved {path.name} ({path.stat().st_size / 1048576:.1f} MB)"
            if res["silent"]:
                msg += f" — warning: silent source(s): {', '.join(res['silent'])}"
            self.status.set(msg)
            if self.transcribe.get():
                self.launch_transcription(path)
        self.refresh_icon()
        if self.quit_after_stop:
            self.quit()

    def pick_recording(self):
        """Choose an existing audio file (default: the recordings folder) and transcribe it
        with the mode, language and model currently selected in the window."""
        start = rm.RECORDINGS_DIR if rm.RECORDINGS_DIR.is_dir() else rm.RECORDINGS_DIR.parent
        chosen = filedialog.askopenfilename(parent=self.root, title="Choose a recording to transcribe",
                                            initialdir=str(start), filetypes=AUDIO_TYPES)
        if not chosen:
            return  # cancelled
        path = Path(chosen)
        self.status.set(f"Selected {path.name}")
        self.launch_transcription(path, name=path.stem)

    @staticmethod
    def last_transcript() -> Path | None:
        """The newest transcript in the transcripts folder, or None."""
        files = [f for f in TRANSCRIPT_DIR.glob("*.txt") if f.is_file()] if TRANSCRIPT_DIR.is_dir() else []
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

    def launch_transcription(self, path, name="meeting"):
        """Transcribe in a hidden background process; progress and result show in the Status box."""
        with_speakers = self.mode.get() == "speakers"
        cmd = rm.transcribe_command(path, name, self.lang.get() or None,
                                    self.model.get() or None, speakers=with_speakers)
        # Use python.exe (not pythonw.exe): the scripts print their progress to stderr
        cmd[0] = str(Path(sys.executable).with_name("python.exe"))
        self.job_seq += 1
        jid = self.job_seq
        self.jobs[jid] = {"file": path.name, "start": time.monotonic(), "stage": "Starting",
                          "kind": "with speakers" if with_speakers else "normal"}
        threading.Thread(target=self.run_transcription, args=(jid, cmd), daemon=True).start()
        self.update_tx_progress()
        self.update_open_btn()

    def run_transcription(self, jid: int, cmd: list):
        """Worker thread: run the script without a console window and report back via tx_events."""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            self.tx_events.put(("done", jid, False, f"could not start the transcription: {e}"))
            return
        # The transcript itself goes to stdout and to the file; drain it so the pipe never fills.
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
        saved, tail = None, []
        for raw in proc.stderr:
            line = ANSI.sub("", raw).strip()
            if not line:
                continue
            if line.startswith(STAGES):
                self.tx_events.put(("stage", jid, line))
            m = re.match(r"Saved\s*:\s*(.+)$", line)
            if m:
                saved = m.group(1).strip()
            tail.append(line)
            tail = tail[-12:]
        code = proc.wait()
        if code == 0 and saved:
            self.tx_events.put(("done", jid, True, Path(saved).name))
        elif code == 0 and any("No speech detected" in l for l in tail):
            self.tx_events.put(("done", jid, True, "no speech was detected"))
        elif code == 0:
            self.tx_events.put(("done", jid, False, "the script finished without saving a transcript"))
        else:
            errors = [l for l in tail if l.startswith("Error") or "Error:" in l]
            self.tx_events.put(("done", jid, False, (errors or tail or [f"exit code {code}"])[-1]))

    def set_tx(self, text: str, kind: str = "busy"):
        """Show (or hide, when empty) the transcription line in the Status box."""
        if text and not self.tx_label.winfo_ismapped():
            self.tx_label.pack(anchor="w", fill="x", pady=(6, 0))
        elif not text and self.tx_label.winfo_ismapped():
            self.tx_label.pack_forget()
        self.tx_label.config(foreground=TX_COLORS[kind])
        if self.tx_status.get() != text:
            self.tx_status.set(text)

    def update_tx_progress(self):
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
            job = self.jobs.get(jid)
            if kind == "stage" and job is not None:
                job["stage"] = rest[0]
            elif kind == "done" and job is not None:
                ok, detail = rest
                del self.jobs[jid]
                finished = True
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
    args = ap.parse_args()

    if not single_instance():
        ctypes.windll.user32.MessageBoxW(0, "Meeting Recorder is already running "
                                            "(check the system tray).", "Meeting Recorder", 0x40)
        return
    root = tk.Tk()
    App(root, args.autostart, args.tray)
    root.mainloop()


if __name__ == "__main__":
    main()
