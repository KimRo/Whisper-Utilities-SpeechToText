# transcribe_file.md — Audio File Transcriber

Transcribes an existing audio file and writes the result to a `.txt` file. Can be run interactively (no arguments) or fully from the command line.

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
4. **Output file** — defaults to `<audio stem>.txt` beside the input file; press Enter to accept.

## Command-line arguments

| Argument | Description |
|---|---|
| `audio` | Path to the audio file to transcribe (optional — omit to use interactive mode) |

### Options

| Flag | Default | Description |
|---|---|---|
| `-l`, `--language` `LANG` | `nl` | Language code. Any valid Whisper code works (`en`, `nl`, `fr`, `de`, …). |
| `-o`, `--output` `FILE` | `<audio stem>.txt` | Output path. Defaults to a `.txt` file next to the input (e.g. `meeting.mp3` → `meeting.txt`). |
| `--model` `SIZE` | `small` | Whisper model: `tiny` / `base` / `small` / `medium` / `large-v2` / `large-v3`. |
| `--cpu` | off | Force CPU inference even when CUDA is available. |

### Examples

```powershell
# Interactive — prompts for all options
python scripts/transcribe_file.py

# Transcribe with defaults (Dutch, small model, output next to input)
python scripts/transcribe_file.py recording.mp3

# English transcription
python scripts/transcribe_file.py interview.wav -l en

# Save to a specific file
python scripts/transcribe_file.py meeting.mp3 -o transcripts/meeting.txt

# Use a more accurate model
python scripts/transcribe_file.py lecture.m4a --model large-v2

# French audio, medium model, specific output
python scripts/transcribe_file.py conference.wav -l fr --model medium -o conference_fr.txt

# Force CPU
python scripts/transcribe_file.py audio.mp3 --cpu
```

## Output

- The transcribed text is written to the output `.txt` file (UTF-8).
- The same text is also printed to **stdout**, so you can pipe it:
  ```powershell
  python scripts/transcribe_file.py audio.mp3 | clip
  ```
- Progress messages (model loading, duration, save path) go to **stderr** and do not interfere with piping.

## Supported audio formats

Any format supported by `soundfile` and `ffmpeg`: `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.mp4`, and more.

## Language codes

Any of the 99 Whisper-supported language codes work with `-l`. Common examples:

| Code | Language | Code | Language |
|---|---|---|---|
| `en` | English | `fr` | French |
| `nl` | Dutch | `de` | German |
| `es` | Spanish | `it` | Italian |
| `pt` | Portuguese | `ru` | Russian |
| `zh` | Chinese | `ja` | Japanese |
| `ko` | Korean | `ar` | Arabic |

For the full list, choose `O` at the language prompt or pass any valid Whisper language code with `-l`.

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
