#!/usr/bin/env python3
"""
Meeting Recorder GUI — small window (and system-tray icon) around record_meeting.py

Usage:
    python scripts/record_meeting_gui.py              # open the window
    python scripts/record_meeting_gui.py --autostart  # open and start recording at once
    python scripts/record_meeting_gui.py --autostart --tray   # ... and start minimized to tray

Records microphone + system audio with the default devices to recordings/<timestamp>_meeting.mp3.
The window can be minimized to the system tray (button, or closing the window while recording).
Tray icon: red = recording, grey = idle. Right-click for Show / Start / Stop / Quit.
After stopping, the recording can be transcribed automatically with transcribe_file.py
(opens in its own console window).

Only record meetings when all participants know about and agree with it.
"""

import argparse
import ctypes
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import record_meeting as rm
except SystemExit:  # record_meeting exits at import if PyAudioWPatch is missing
    ctypes.windll.user32.MessageBoxW(
        0, "PyAudioWPatch is not installed.\n\nRun: python -m pip install PyAudioWPatch",
        "Meeting Recorder", 0x10)
    sys.exit(1)

try:
    import pystray
except ImportError:
    pystray = None  # tray is optional; window still works

LANGUAGES = ["nl", "en", "fr", "de", "es", "it", "pt", "pl", "sv", "da", "no", "fi"]
MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]


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

        self.status = tk.StringVar(value="Ready")
        ttk.Label(frm, textvariable=self.status, wraplength=300, foreground="#555").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 8))

        self.transcribe = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Transcribe after stopping", variable=self.transcribe).grid(
            row=4, column=0, columnspan=3, sticky="w")
        self.lang = tk.StringVar(value="nl")
        self.model = tk.StringVar(value="small")
        ttk.Label(frm, text="Language").grid(row=5, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(frm, textvariable=self.lang, values=LANGUAGES, width=8).grid(
            row=5, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Label(frm, text="Model").grid(row=6, column=0, sticky="w")
        ttk.Combobox(frm, textvariable=self.model, values=MODELS, width=8,
                     state="readonly").grid(row=6, column=1, sticky="w", padx=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=3, pady=(12, 0), sticky="ew")
        self.btn = ttk.Button(btns, text="● Start recording", command=self.toggle)
        self.btn.pack(side="left", expand=True, fill="x")
        self.tray_btn = ttk.Button(btns, text="Minimize to tray", command=self.to_tray)
        self.tray_btn.pack(side="left", padx=(8, 0))
        if pystray is None:
            self.tray_btn.state(["disabled"])
            self.status.set("Ready (tray unavailable: pip install pystray)")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.pa = None
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

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── Recording ───────────────────────────────────────────────────────────────
    def toggle(self):
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.recording or (self.thread and self.thread.is_alive()):
            return
        self.pa = rm.pyaudio.PyAudio()
        try:
            sources = rm.open_sources(self.pa)
        except Exception as e:
            self.pa.terminate()
            self.status.set(f"Could not open audio device: {e}")
            self.show()
            return
        self.mp3_path = rm.build_name(None)
        self.stop_evt.clear()
        self.result = None
        self.recording = True
        self.elapsed = 0.0
        self.btn.config(text="■ Stop recording")
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

            rm.record(sources, self.mp3_path, self.stop_evt, on_tick=on_tick)
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

    def launch_transcription(self, path):
        cmd = rm.transcribe_command(path, "meeting", self.lang.get() or None,
                                    self.model.get() or None)
        # transcribe_file.py needs a real console: use python.exe, not pythonw.exe
        cmd[0] = str(Path(sys.executable).with_name("python.exe"))
        inner = subprocess.list2cmdline(cmd)
        subprocess.Popen(f'cmd /c "{inner} & pause"', creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.status.set(self.status.get() + " — transcribing in a new window")

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
