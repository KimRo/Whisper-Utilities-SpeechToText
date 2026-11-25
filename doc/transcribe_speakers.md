# transcribe_speakers.py

Transcribes an audio file and labels who says what. Text comes from faster-whisper, speakers from [pyannote.audio](https://github.com/pyannote/pyannote-audio) diarization.

```
[00:00:03] Speaker 1: Goedemorgen allemaal.
[00:00:07] Speaker 2: Goedemorgen, zullen we beginnen?
```

Speakers are anonymous and numbered in order of first appearance. It does not recognise known voices; use `--names` to substitute real names afterwards.

## One-time setup

The pyannote models are gated on Hugging Face (free):

1. Create an account at <https://huggingface.co>.
2. Accept the terms on the model page: <https://huggingface.co/pyannote/speaker-diarization-community-1>
3. Create a **read** token (Settings → Access Tokens) and make it available:
   - `setx HF_TOKEN hf_xxxxxxxx` (open a new terminal afterwards), or
   - `huggingface-cli login`, or
   - paste it when the script asks. A pasted token is used for that run only and is not saved.

After the first download the models are cached and the script works offline.

## Usage

```powershell
python scripts/transcribe_speakers.py meeting.mp3
python scripts/transcribe_speakers.py meeting.mp3 -l en --speakers 3
python scripts/transcribe_speakers.py meeting.mp3 --names "Kim,Jan"
python scripts/transcribe_speakers.py            # interactive
```

| Option | Meaning |
|---|---|
| `-l, --language` | Language code (default `nl`) |
| `-o, --output` | Output base name; always saved in `transcripts/` as `<timestamp>_<name>.txt` |
| `--model` | Whisper model (default `medium`) |
| `--cpu` | Force CPU |
| `--speakers N` | Exact number of speakers (most effective accuracy hint) |
| `--min-speakers N`, `--max-speakers N` | Bounds on the speaker count |
| `--names A,B,C` | Names in order of first appearance |

## Limitations

- Overlapping speech is not separated: each word goes to the speaker with the most overlap.
- The number of speakers can be mis-detected, especially with similar voices or poor audio. Pass `--speakers` when you know it.
- Without a GPU the speaker step is slow on long recordings.
- Uses pyannote.audio 4.1.1 and its `community-1` model, which needs PyTorch 2.8 or newer. The installer pins torch and torchaudio (2.11.0) together and holds them with a constraints file so pyannote's dependencies cannot replace the CUDA build.
- PyAV is kept below version 19, because faster-whisper 1.2.1 passes an argument that PyAV 19 removed.
- The words are matched against pyannote's "exclusive" diarization, which has no overlapping turns.
