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
2. Accept the terms on both pages:
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>
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
- Pinned to pyannote.audio 3.4.0 with `huggingface_hub<1.0` (3.4.0 passes `use_auth_token`, which huggingface_hub 1.x removed). The installer pins torch/torchaudio so pyannote's dependencies cannot replace the CUDA build.
- PyTorch 2.6+ only loads allow-listed classes from checkpoints. The script allow-lists the four pyannote/torch classes the 3.1 pipeline needs, so the safety check stays on.
