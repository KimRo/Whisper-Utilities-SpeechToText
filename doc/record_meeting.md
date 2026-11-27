# record_meeting.py

Records a live meeting: your **microphone** and the **system audio** (the other participants in Teams, Zoom, Meet, ...) are mixed into one mono 16 kHz MP3 (or, with separate channels, kept apart in one stereo MP3). Nothing is transcribed while recording. When you stop, the script offers to transcribe the MP3 with [transcribe_file.py](transcribe_file.md).

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
| `--mic ID\|NAME` | Microphone: device id, (part of) a device name, `default` or `off` (default: Windows default input) |
| `--loopback ID\|NAME`, `--system` | System audio, same forms (default: loopback of the default output device) |
| `--output-dir DIR` | The one output folder (default: `Documents\Meeting Recorder`, see below); every recording gets its own subfolder in it, holding the audio, transcript and log |
| `--settings FILE` | Settings file to use (default: `%APPDATA%\WhisperMeetingRecorder\settings.json`, see below) |
| `--no-mic` | Record system audio only |
| `--no-system` | Record microphone only |
| `--format mp3\|wav` | Recording format (default `mp3`): MP3 at 64 kbps, or uncompressed 16 kHz 16-bit WAV (about 4x larger) |
| `--duck`, `--no-duck` | Hybrid-meeting mode: lower the microphone while system audio plays (see below) |
| `--separate-channels`, `--no-separate-channels` | Stereo MP3 with the microphone on the left and system audio on the right, instead of one mixed channel (see below) |
| `--list-devices` | Print device ids and exit |
| `--transcribe ask\|yes\|no` | Run `transcribe_file.py` afterwards (default: `ask`) |
| `-l, --language` | Passed to `transcribe_file.py` |
| `--model` | Passed to `transcribe_file.py` (default: `medium`) |
| `--cpu` | Passed to `transcribe_file.py` |

## Output folder

You set **one** output folder. Every recorded meeting gets its own subfolder in it, named `<YYYY-MM-DD_HH-MM-SS>_<name>`, that holds everything belonging to that meeting:

```
<output folder>\
  2026-11-27_09-30-40_Budget_review\
    2026-11-27_09-30-40_Budget_review.mp3        the recording (part files while it is being recorded)
    2026-11-27_09-30-40_Budget_review.txt        the transcript (the combined one for a split recording)
    2026-11-27_09-30-40_Budget_review.log.txt    the log of the Status box
```

The default output folder is `Documents\Meeting Recorder`, in your Documents folder as Windows reports it (a redirected Documents folder is followed), so nothing is kept in the repository. Change it in the GUI ("Output folder" and its "…" button; saved as a setting) or with `--output-dir` (the GUI and `record_meeting.py`). Folders are created when needed.

- **Transcribing a recording again:** a second transcription of a recording in its meeting folder adds another timestamped `.txt` there and appends to the same log.
- **Transcribing an audio file from somewhere else** ("Transcribe a recording…"): its transcript and log go in a new `<timestamp>_<file name>` folder in the output folder (the audio file itself is not copied or moved).
- **The other tools:** `transcribe_file.py` and `transcribe_speakers.py` save to a new `<timestamp>_<name>` folder in the saved output folder unless you give `--output-dir` (then the transcript goes directly into that folder), and `transcribe_tts.py` makes a `<timestamp>_session` folder, so they follow the folder chosen in the GUI.
- **Earlier versions:** files recorded before this layout stay where they were (`recordings` and `transcripts` in the repository, or a folder you had chosen); they are not moved. An output, transcript or log folder saved by an earlier version is ignored; pick the output folder again once.

## Output

Recordings are saved in the meeting's folder (see above) as `<YYYY-MM-DD_HH-MM-SS>_<name>.mp3` or `.wav` (chosen with the "Recording" list in the window). MP3 is 16 kHz, mono at 64 kbps, about 30 MB per hour, or stereo at 96 kbps, about 43 MB per hour, with separate channels. WAV is 16 kHz 16-bit uncompressed, about 115 MB per hour mono. The transcript is saved in the same folder.

## Saved settings

The GUI saves every setting as soon as you change it, and both programs read them at start-up, so the next run starts with your last choices. The file is `%APPDATA%\WhisperMeetingRecorder\settings.json` (or the file given with `--settings`); delete it to go back to the defaults. Saved: microphone and system-audio device (by name, so a changed device id does not matter; an unplugged device falls back to the default), hybrid mode, separate channels, transcribe after stopping, mode (normal / with speakers), language, model, recording format, split minutes and the output folder. The recording **name** is per recording and not saved.

**Command-line options always win** over the saved value, for that run only: they are never written to the settings file, so `record_meeting_gui.py --model tiny` does not change your saved model. A boolean option has an opposite form (`--duck` / `--no-duck`) so you can switch off something that was saved on. Priority: command line, then saved setting, then built-in default. Differences between the two programs: `record_meeting.py` only uses the saved devices, format, folders, language, model, duck, separate channels and transcribe (saved on = `yes`, off = `no`, never saved = `ask`); it does not split recordings and has no `--cpu` setting.

Command-line options of the GUI (`record_meeting_gui.py`), all optional: `--autostart`, `--tray`, `--settings FILE`, `--name NAME`, `--mic` / `--system` (`default`, `off` or part of a device name), `--duck` / `--no-duck`, `--separate-channels` / `--no-separate-channels`, `--transcribe` / `--no-transcribe`, `--mode normal|speakers`, `-l/--language`, `--model`, `--format mp3|wav`, `--chunk-minutes 0-60`, `--output-dir`.

## GUI and shortcut

`scripts/record_meeting_gui.py` is a small window with a timer, level meters for both sources and a Start/Stop button.

- **Devices:** two dropdowns list the detected **microphones** and **system-audio (loopback) devices**. Each defaults to the Windows default device and can be set to *Off*; **Refresh devices** rescans (for example after plugging in a headset). They are locked while recording.
- **Transcription:** a "Transcribe after stopping" checkbox, language and model pickers (defaults `nl` / `medium`), and a choice between **Normal** and **With speakers** (speaker labels, see [transcribe_speakers.md](transcribe_speakers.md)). Because there is no console, the speaker transcription cannot ask for a Hugging Face token: set `HF_TOKEN` first, otherwise it fails with a message saying so.
- **Also transcribe while recording, every [5] min (0 = off):** for long meetings. The recording continues without a gap, but every N minutes a new part file (`<name>_part01.mp3`, `_part02`, ...) is started and the finished part is transcribed in the background with the selected mode, language and model. Transcription of a part may take longer than N minutes: parts then wait in a queue (the Status box shows the part being transcribed and how many are waiting). All text goes into **one combined transcript** in `transcripts\<name>.txt`, one `--- Part N (hh:mm:ss - hh:mm:ss) ---` block per part; it grows while you record, so "Open last transcription" works mid-meeting. In *With speakers* mode the `[hh:mm:ss]` stamps are shifted to the time in the whole recording, but each part is diarized separately, so remote speakers may be numbered differently from part to part ("You" stays the same). A word that falls on a part boundary may be split over two parts. When recording has stopped and every part is transcribed, the parts are merged into one recording `<name>.mp3` and the part files are removed; if a part failed to transcribe or the merge failed, the part files are kept. Needs transcription to be available; each part starts a new transcription process, so the model is loaded again per part. Quitting while parts are still queued asks for confirmation; untranscribed parts stay in `recordings`.
- **Output folder:** where the meeting folders are created (see *Output folder* above). The "…" button picks another folder (created if missing; locked while recording).
- **Transcribe a recording...:** transcribes any existing audio file with the same settings.
- **Open last transcription:** opens the newest transcript from the `transcripts` folder. It is greyed out while a transcription is running in the background, and when there is no transcript yet.
- **Log and Open log:** everything shown in the Status box is also written, with timestamps, to `<meeting folder>\<recording name>.log.txt` (transcribing an existing file appends to `<that file's name>.log.txt` there). "Open log", below the Status box, opens the log of the transcription that is running, or the newest log when none is running.
- **Background transcription:** it runs hidden. The **Status** box at the bottom shows the current step and elapsed time, then a green *Transcription finished* line with the saved file name, or a red *Transcription failed* line with the error. When it ends, the window comes to the front again, also from the tray. Several transcriptions can run at once. If you quit the window meanwhile, the transcription keeps running hidden and still saves the transcript.
- **Tray:** **Minimize to tray**, or the window's own minimize button, hides it in the system tray instead of the taskbar (grey icon = idle, red = recording; right-click for Show / Start / Stop / Quit). Closing the window while recording also moves it to the tray; closing it while idle quits.

**Start-up check.** When the window opens it checks which packages are installed and greys out what cannot work, listing what is missing in the Status box (the check only looks whether the packages exist; it does not load them):

| Missing | Greyed out |
|---|---|
| PyAudioWPatch, PyAV (`av`) or NumPy | Everything for recording: Start, the device pickers, Refresh, the hybrid-meeting and separate-channel checkboxes |
| faster-whisper, PyAV or NumPy | All transcription: "Transcribe after stopping", Normal / With speakers, language and model, "Transcribe a recording…" |
| pyannote.audio, PyTorch, or a Hugging Face token (`HF_TOKEN` or `hf auth login`) | Only "With speakers" |
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

- The file is larger: 96 kbps instead of 64 kbps (about 43 MB per hour instead of 30 MB).
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
