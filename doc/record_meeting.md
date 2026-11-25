# record_meeting.py

Records a live meeting: your **microphone** and the **system audio** (the other participants in Teams, Zoom, Meet, ...) are mixed into one mono 16 kHz MP3. Nothing is transcribed while recording. When you stop, the script offers to transcribe the MP3 with [transcribe_file.py](transcribe_file.md).

Windows only. System audio is captured with WASAPI loopback via `PyAudioWPatch`; MP3 encoding uses PyAV (installed with `faster-whisper`), so ffmpeg is not required.

> Only record meetings when all participants know about and agree with it. Local law and company policy may require consent.

## Usage

```powershell
python scripts/record_meeting.py
python scripts/record_meeting.py -o weekly-sync
python scripts/record_meeting.py -o weekly-sync -l en --model medium --transcribe yes
python scripts/record_meeting.py --list-devices
python scripts/record_meeting.py --mic 5 --loopback 12
```

Stop recording with **Enter** or **Ctrl+C**. While recording, the elapsed time and a level meter for each source are shown, so you can see that both the microphone and the system audio are picked up.

## Options

| Option | Description |
|---|---|
| `-o, --output` | Name part of the file (default: `meeting`) |
| `--mic ID` | Microphone device id (default: Windows default input) |
| `--loopback ID` | System-audio device id (default: loopback of the default output device) |
| `--no-mic` | Record system audio only |
| `--no-system` | Record microphone only |
| `--duck` | Hybrid-meeting mode: lower the microphone while system audio plays (see below) |
| `--separate-channels` | Stereo MP3 with the microphone on the left and system audio on the right, instead of one mixed channel (see below) |
| `--list-devices` | Print device ids and exit |
| `--transcribe ask\|yes\|no` | Run `transcribe_file.py` afterwards (default: `ask`) |
| `-l, --language` | Passed to `transcribe_file.py` |
| `--model` | Passed to `transcribe_file.py` (default: `medium`) |
| `--cpu` | Passed to `transcribe_file.py` |

## Output

Recordings are saved to the repo-root `recordings\` folder as `<YYYY-MM-DD_HH-MM-SS>_<name>.mp3` (mono, 16 kHz, 64 kbps — roughly 30 MB per hour). Transcripts end up in `transcripts\` as usual.

## GUI and shortcut

`scripts/record_meeting_gui.py` is a small window with a timer, level meters for both sources, a Start/Stop button, a "Transcribe after stopping" checkbox and language/model pickers (defaults `nl` / `medium`). Two dropdowns list the detected **microphones** and **system-audio (loopback) devices**: each defaults to the Windows default device and can be set to *Off*; **Refresh devices** rescans (for example after plugging in a headset). The dropdowns are locked while recording. **Minimize to tray**, or the window's own minimize button, hides it in the system tray instead of the taskbar (grey icon = idle, red = recording; right-click for Show / Start / Stop / Quit). Closing the window while recording also moves it to the tray; closing it while idle quits. Transcription (after stopping, or via **Transcribe a recording…**) runs hidden in the background: the **Status** box at the bottom shows the current step and elapsed time, then a green *Transcription finished* line with the saved file name, or a red *Transcription failed* line with the error. When it ends, the window comes to the front again, also from the tray. Several transcriptions can run at once. Because there is no console, the speaker transcription cannot ask for a Hugging Face token: set `HF_TOKEN` first (see [transcribe_speakers.md](transcribe_speakers.md)), otherwise it fails with a message saying so. If you quit the window while a transcription is running, it keeps running hidden and still saves the transcript.

**Start-up check.** When the window opens it checks which packages are installed and greys out what cannot work, listing what is missing in the Status box (the check only looks whether the packages exist; it does not load them):

| Missing | Greyed out |
|---|---|
| PyAudioWPatch, PyAV (`av`) or NumPy | Everything for recording: Start, the device pickers, Refresh, the hybrid-meeting and separate-channel checkboxes |
| faster-whisper, PyAV or NumPy | All transcription: "Transcribe after stopping", Normal / With speakers, language and model, "Transcribe a recording…" |
| pyannote.audio, PyTorch, or a Hugging Face token (`HF_TOKEN` or `huggingface-cli login`) | Only "With speakers" |
| Pillow or pystray | The tray button and tray icon |

Run `scripts\install.bat` to install missing packages. The same check, from the shared `scripts\requirements_check.py`, runs first in every command-line tool (`record_meeting.py`, `transcribe_file.py`, `transcribe_speakers.py`, `transcribe_tts.py`): instead of a Python traceback they stop at once with a message naming what is missing and how to install it. `record_meeting.py` also checks the transcription packages before recording, so a missing one is noticed up front (with `--transcribe yes` it stops; otherwise it records only and says so). Run `python scripts\requirements_check.py` at any time to see the full list; the installer runs it at the end.

```powershell
python scripts/record_meeting_gui.py                       # open the window
python scripts/record_meeting_gui.py --autostart           # open and start recording
python scripts/record_meeting_gui.py --autostart --tray    # start recording, hidden in the tray
```

Double-click **`scripts\create_shortcut.bat`** to create a *Meeting Recorder* shortcut on the Desktop and in the Start Menu. It runs the GUI without a console window with `--autostart`, i.e. one click starts recording with the default microphone and speakers. Run it with `-Tray` to make the shortcut start hidden in the tray, or `-Remove` to delete the shortcuts. Only one instance can run at a time.

## Separate channels (`--separate-channels` / GUI checkbox)

Normally both sources are mixed into one mono track, so it is no longer known who was on the microphone and who was on the system audio (the remote participants in Teams and similar apps). With `--separate-channels`, or the GUI checkbox **"Keep mic and system audio on separate channels"** (on by default), the MP3 is stereo: microphone on the left, system audio on the right. `transcribe_file.py` reads it exactly as before, and `transcribe_speakers.py` uses it to label your own voice as **You** (see [transcribe_speakers.md](transcribe_speakers.md)).

- The file is larger: 96 kbps instead of 64 kbps.
- It only applies when both a microphone and system audio are recorded. In the window, the checkbox is unchecked and disabled while either source is set to **Off** (the recording is mono) and returns to your last choice when both are on again. On the command line, `--separate-channels` together with `--no-mic` or `--no-system` prints a note and records mono.
- With **Hybrid meeting** ducking also on, the microphone channel is recorded quieter while remote audio plays, so you talking over a remote participant may not be recognised as "You".
- Use headphones. With speakers, the remote voices are picked up again by the microphone, which makes them look like you.

## Hybrid meetings (`--duck` / GUI checkbox)

In a hybrid meeting the colleagues' voices come out of the room speaker, and the room microphone hears them a second time (slightly delayed) in addition to the system-audio capture, so remote voices would be recorded twice and sound echoey.

With **"Hybrid meeting: lower mic while remote audio plays"** (GUI) or `--duck` (command line), the microphone level is reduced to 15% while the system audio is playing, and restored 0.4 s after it goes quiet. The values are constants at the top of `record_meeting.py` (`DUCK_GAIN`, `DUCK_THRESHOLD`, `DUCK_HOLD`).

Limitations:
- People in the room who talk **over** a remote colleague are recorded quieter.
- Ducking only starts when the system audio exceeds `DUCK_THRESHOLD` (about -40 dBFS). If the Teams volume is very low, raise it or lower the threshold.
- It needs both the microphone and system audio to be recording. It is off by default.
- Alternative without any processing: record the room microphone only (set *System audio* to Off, or use `--no-system`); the room mic then hears both the room and the speaker.

## Notes

- System audio is taken from the **default output device**. If your meeting uses a headset that is not the Windows default, pick its loopback device with `--list-devices` and `--loopback`.
- Loopback delivers no data while nothing is playing; the recorder fills such gaps with silence, so timing stays correct.
- If a source stays silent for the whole recording, a warning is shown at the end.
