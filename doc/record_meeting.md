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
| `--list-devices` | Print device ids and exit |
| `--transcribe ask\|yes\|no` | Run `transcribe_file.py` afterwards (default: `ask`) |
| `-l, --language` | Passed to `transcribe_file.py` |
| `--model` | Passed to `transcribe_file.py` |
| `--cpu` | Passed to `transcribe_file.py` |

## Output

Recordings are saved to the repo-root `recordings\` folder as `<YYYY-MM-DD_HH-MM-SS>_<name>.mp3` (mono, 16 kHz, 64 kbps — roughly 30 MB per hour). Transcripts end up in `transcripts\` as usual.

## GUI and shortcut

`scripts/record_meeting_gui.py` is a small window with a timer, level meters for both sources, a Start/Stop button, a "Transcribe after stopping" checkbox and language/model pickers (defaults `nl` / `small`). **Minimize to tray** hides it in the system tray (grey icon = idle, red = recording; right-click for Show / Start / Stop / Quit). Closing the window while recording also moves it to the tray; closing it while idle quits. Transcription opens in its own console window.

```powershell
python scripts/record_meeting_gui.py                       # open the window
python scripts/record_meeting_gui.py --autostart           # open and start recording
python scripts/record_meeting_gui.py --autostart --tray    # start recording, hidden in the tray
```

Double-click **`scripts\create_shortcut.bat`** to create a *Meeting Recorder* shortcut on the Desktop and in the Start Menu. It runs the GUI without a console window with `--autostart`, i.e. one click starts recording with the default microphone and speakers. Run it with `-Tray` to make the shortcut start hidden in the tray, or `-Remove` to delete the shortcuts. Only one instance can run at a time.

## Notes

- System audio is taken from the **default output device**. If your meeting uses a headset that is not the Windows default, pick its loopback device with `--list-devices` and `--loopback`.
- Loopback delivers no data while nothing is playing; the recorder fills such gaps with silence, so timing stays correct.
- If a source stays silent for the whole recording, a warning is shown at the end.
