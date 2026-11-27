# transcribe_file.md — Audio File Transcriber

Transcribes an existing audio file and writes the result to a timestamped `.txt` file in a new `<timestamp>_<name>` folder of the output folder (default: `Documents\Meeting Recorder`, see [record_meeting.md](record_meeting.md)), or directly in the folder given with `--output-dir`. Can be run interactively (no arguments) or fully from the command line.

## Usage

**Interactive** — omit the audio file to be prompted for all options:

```powershell
python scripts/transcribe_file.py
```

**Command-line** — pass the audio file and any options directly:

```powershell
python scripts/transcribe_file.py <audio> [options]
```

## Interactive mode

Running the script without arguments starts a short setup sequence:

1. **Audio file** — enter the path to the file (drag-and-drop into the terminal works). Re-prompts until a valid file is found.
2. **Language** — `E` English / `D` Dutch (default) / `O` Other (shows a numbered list of 26 languages).
3. **Model** — numbered list from `tiny` to `large-v3`; `small` is the default.
4. **Output name** — defaults to the audio file's name; press Enter to accept. The file is always saved in the `transcripts` folder as `<YYYY-MM-DD_HH-MM-SS>_<name>.txt`.

## Command-line arguments

| Argument | Description |
|---|---|
| `audio` | Path to the audio file to transcribe (optional — omit to use interactive mode) |

### Options

| Flag | Default | Description |
|---|---|---|
| `-l`, `--language` `LANG` | `nl` | Language code. Any valid Whisper code works (`en`, `nl`, `fr`, `de`, …). |
| `-o`, `--output` `NAME` | `<audio stem>` | Output base name. Any folder or extension given is ignored; the file is always saved to `transcripts\<timestamp>_<name>.txt` (e.g. `meeting.mp3` → `transcripts\2026-11-25_14-30-05_meeting.txt`). |
| `--model` `SIZE` | `small` | Whisper model: `tiny` / `base` / `small` / `medium` / `large-v2` / `large-v3`. |
| `--cpu` | off | Force CPU inference even when CUDA is available. |

### Examples

```powershell
# Interactive — prompts for all options
python scripts/transcribe_file.py

# Transcribe with defaults (Dutch, small model, output in transcripts folder)
python scripts/transcribe_file.py recording.mp3

# English transcription
python scripts/transcribe_file.py interview.wav -l en

# Use a custom base name (saved as transcripts\<timestamp>_team_meeting.txt)
python scripts/transcribe_file.py meeting.mp3 -o team_meeting

# Use a more accurate model
python scripts/transcribe_file.py lecture.m4a --model large-v2

# French audio, medium model, custom base name
python scripts/transcribe_file.py conference.wav -l fr --model medium -o conference_fr

# Force CPU
python scripts/transcribe_file.py audio.mp3 --cpu
```

## Output

- The transcribed text is written (UTF-8) to `<output folder>\<YYYY-MM-DD_HH-MM-SS>_<name>\<YYYY-MM-DD_HH-MM-SS>_<name>.txt` (or the `--output-dir` folder). The folder is created if it doesn't exist.
- The same text is also printed to **stdout**, so you can pipe it:
  ```powershell
  python scripts/transcribe_file.py audio.mp3 | clip
  ```
- Progress messages (model loading, duration, save path) go to **stderr** and do not interfere with piping.

## Supported audio formats

Any format PyAV (installed with `faster-whisper`, no separate ffmpeg needed) can decode: `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.mp4`, and more.

## Language codes

`-l` takes a language code. Common examples:

| Code | Language | Code | Language |
|---|---|---|---|
| `en` | English | `fr` | French |
| `nl` | Dutch | `de` | German |
| `es` | Spanish | `it` | Italian |
| `pt` | Portuguese | `ru` | Russian |
| `zh` | Chinese | `ja` | Japanese |
| `ko` | Korean | `ar` | Arabic |

Whisper itself knows about 99 languages, but these tools accept the 28 codes above (the list behind option `O` at the language prompt). Any other code, such as `af`, is rejected with "unknown language".

All accepted codes: `ar` `cs` `da` `de` `el` `en` `es` `fi` `fr` `he` `hi` `hu` `id` `it` `ja` `ko` `nl` `no` `pl` `pt` `ro` `ru` `sv` `th` `tr` `uk` `vi` `zh`.

## Model notes

Whisper models are **multilingual** — each model supports all languages with the same files on disk. There is no per-language download. Choosing `-l fr` and `-l de` with the same model uses identical cached files.

Models are cached automatically on first use in:
```
C:\Users\<you>\.cache\huggingface\hub\models--Systran--faster-whisper-<size>\
```

Approximate sizes:

| Model | Disk |
|---|---|
| tiny | ~75 MB |
| base | ~145 MB |
| small | ~460 MB |
| medium | ~1.5 GB |
| large-v2 | ~3.1 GB |
| large-v3 | ~3.1 GB |
