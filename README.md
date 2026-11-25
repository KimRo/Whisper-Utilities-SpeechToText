# Offline Whisper Transcription Tools

> All code in this project was generated during a vibe coding session with [Claude Code](https://claude.ai/code) with almost zero user programming involved.

Two offline speech-to-text tools powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (OpenAI Whisper). All processing happens locally — no internet connection required after the model is downloaded.

| Script | Purpose |
|---|---|
| `scripts/transcribe_tts.py` | Push-to-talk live transcriber — hold Space to record, release to transcribe |
| `scripts/transcribe_file.py` | Batch file transcriber — transcribe an existing audio file from the command line |
| `scripts/transcribe_speakers.py` | Speaker-labelled transcriber — transcribes a file and marks who says what (`Speaker 1`, `Speaker 2`, ...); needs a one-time free Hugging Face token, see [doc](doc/transcribe_speakers.md) |
| `scripts/record_meeting.py` | Meeting recorder — records microphone + system audio to MP3, then offers to transcribe it |
| `scripts/record_meeting_gui.py` | Window + system-tray version of the meeting recorder; after stopping it can transcribe normally or with speaker labels (choose in the window); `scripts\create_shortcut.bat` makes a one-click Desktop/Start Menu shortcut |

## Installation

Double-click **`scripts\install.bat`** — it handles everything automatically.

What the installer does:

1. Checks for Python 3.10+ and installs it via `winget` if missing
2. Upgrades `pip`
3. Shows your NVIDIA GPU (via `nvidia-smi`) and lets you pick the PyTorch build: CPU-only, CUDA 12.6 (default), 12.8 or 13.0
4. Installs all Python dependencies and verifies imports

**Dependencies installed:**

| Package | Purpose |
|---|---|
| `torch` (2.11.0) | Deep learning runtime — you choose CPU-only, CUDA 12.6 (default), 12.8 or 13.0 during install |
| `faster-whisper` | Whisper speech recognition engine |
| `sounddevice` | Microphone audio capture |
| `soundfile` | Audio file I/O |
| `pynput` | Global keyboard listener (push-to-talk) |
| `PyAudioWPatch` | WASAPI loopback capture of system audio (meeting recorder) |
| `pystray` | System-tray icon for the meeting recorder GUI (Pillow is installed with it) |
| `numpy` | Audio buffer processing |
| `torchaudio` (2.11.0) | Installed with `torch`, same version and index (required by pyannote.audio) |
| `pyannote.audio` (4.1.1) | Speaker diarization for `transcribe_speakers.py` (needs torch 2.8+) |
| `av` (below 19) | Audio decoding/encoding (PyAV); 19 breaks the current faster-whisper |

> Both scripts fall back to CPU automatically if CUDA is unavailable at runtime.

## Models

Whisper models are **multilingual** — a single model handles all 99 supported languages. There are no per-language downloads; language is a runtime setting only.

| Model | Disk | Speed | Accuracy |
|---|---|---|---|
| tiny | ~75 MB | fastest | lowest |
| base | ~145 MB | fast | low |
| small | ~460 MB | good | good |
| medium | ~1.5 GB | slower | high |
| large-v2 | ~3.1 GB | slowest | highest |
| large-v3 | ~3.1 GB | slowest | highest |

Models are downloaded automatically on first use and cached in:
```
C:\Users\<you>\.cache\huggingface\hub\
```

## Quick start

```powershell
# Live push-to-talk (interactive setup)
python scripts/transcribe_tts.py

# Transcribe an audio file
python scripts/transcribe_file.py recording.mp3

# Record a meeting (mic + system audio), stop with Enter, then transcribe
python scripts/record_meeting.py -o weekly-sync
```

## Sample

`samples\transcribe_file_sample.bat` — double-click to download and transcribe a real audio file with no setup beyond installation.

It downloads the recording of Martin Luther King Jr.'s *"I Have a Dream"* speech (August 28, 1963) from the Internet Archive (~3 MB), then transcribes it to `transcripts\<timestamp>_MLKDream.txt` using the `small` model in English. A confirmation prompt is shown before anything is downloaded.

## Documentation

- [transcribe_tts.py](doc/transcribe_tts.md) — live push-to-talk transcriber
- [transcribe_file.py](doc/transcribe_file.md) — audio file transcriber
- [transcribe_speakers.py](doc/transcribe_speakers.md) — transcriber with speaker labels
- [record_meeting.py](doc/record_meeting.md) — meeting recorder

## License

[CC0 1.0 — Public Domain](LICENSE)
