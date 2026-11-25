# transcribe_tts.py — Live Push-to-Talk Transcriber

Records speech while Space is held, transcribes on release, and appends confirmed text to a timestamped session file.

## Usage

```powershell
python scripts/transcribe_tts.py [options]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `-l`, `--language` `LANG` | prompted | Language code (`en`, `nl`, or any code from the Other list). Skips the language prompt when provided. |
| `-d`, `--device` `INDEX` | prompted | Microphone device index. Use `--list-devices` to find the right number. Skips the device prompt when provided. |
| `-m`, `--model` `SIZE` | prompted | Whisper model: `tiny` / `base` / `small` / `medium` / `large-v2` / `large-v3`. Skips the model prompt when provided. |
| `--cpu` | off | Force CPU inference even when CUDA is available. |
| `--list-devices` | — | Print available input devices and exit. |

### Examples

```powershell
# Fully interactive — prompts for device, model and language
python scripts/transcribe_tts.py

# English, system default mic, small model — no prompts
python scripts/transcribe_tts.py -l en -m small

# Dutch, specific mic, more accurate model
python scripts/transcribe_tts.py -l nl -d 2 -m large-v2

# See available microphones
python scripts/transcribe_tts.py --list-devices

# Force CPU (useful when CUDA causes issues)
python scripts/transcribe_tts.py --cpu
```

## Interactive setup

When options are omitted the script walks through a short setup sequence:

1. **Device selection** — lists all input devices; the system default is pre-selected (press Enter to confirm).
2. **Cache overview** — shows which Whisper models are already downloaded and their disk usage.
3. **Language selection** — `E` English / `D` Dutch (default) / `O` Other (shows a numbered list of 26 common languages).
4. **Model selection** — numbered list from `tiny` to `large-v3`; `small` is the default.

## Recording session

| Key | Action |
|---|---|
| `Space` (hold) | Start recording — screen shows `[LISTENING]` |
| `Space` (release) | Stop recording and transcribe — screen shows `[TRANSCRIBING]` |
| `Y` or `Enter` | Keep the transcribed text and append it to the session file |
| `N` | Discard the transcribed text |
| `Q` | Prompt to end the session |
| `Y` or `Enter` at quit prompt | Save and exit |
| `N` at quit prompt | Return to recording |

If no speech is detected after releasing Space the screen shows `[No speech detected — press SPACE to try again]`.

## Output

Each session writes to a timestamped `.txt` file:

```
transcripts\YYYY-MM-DD_HH-MM-SS_session.txt
```

The `transcripts` folder is in the repository root (shared with `transcribe_file.py`) and is created if it doesn't exist.

The file is created at startup and each kept fragment is appended immediately, so the file is safe even if the script is interrupted.

## Language codes

`-l` takes a language code. Common codes:

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

Whisper models are **multilingual** — each model supports all languages with the same files on disk. There is no per-language download. Disk usage listed in the cache overview is the total for that model regardless of which language you use.

Models are cached in:
```
C:\Users\<you>\.cache\huggingface\hub\models--Systran--faster-whisper-<size>\
```
