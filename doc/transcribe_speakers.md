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
| `--names A,B,C` | Names for the remote speakers, in order of first appearance |
| `--dual-channel auto\|on\|off` | Treat a stereo file as microphone (left) + system audio (right). `auto` (default) = on for 2-channel files |
| `--me NAME` | Label for the microphone channel (default `You`) |

## Meetings recorded with separate channels

If the recording was made with **Keep mic and system audio on separate channels** (`record_meeting.py --separate-channels`, on by default in the GUI), the file is stereo: your microphone on the left, system audio (the other participants in Teams, Zoom and similar) on the right. The script then:

- labels words where the microphone clearly dominates as **You** (or the `--me` name),
- runs the speaker separation on the system-audio channel only, so the other participants are numbered `Speaker 1`, `Speaker 2`, ... without your voice mixed in.

```
[00:00:06] Speaker 1: Goedemorgen allemaal.
[00:00:11] You: Goedemorgen, zullen we beginnen?
```

Things to know:

- Everyone talking into your microphone gets the `You` label, for example all people sitting in your room.
- Use headphones. With speakers, remote voices leak into the microphone channel and can be labelled `You`. The thresholds are `YOU_RATIO` and `YOU_MIN_RMS` at the top of the script.
- A stereo file that did *not* come from this recorder would be misread as microphone/system audio; use `--dual-channel off` for those.
- If you talk while remote audio plays and the hybrid-meeting ducking option was on, your microphone is recorded quieter and may count as remote.

## Limitations

- Overlapping speech is not separated: each word goes to the speaker with the most overlap, and sentences are then assigned as a whole (see below).
- The number of speakers can be mis-detected, especially with similar voices or poor audio. Pass `--speakers` when you know it.
- Without a GPU the speaker step is slow on long recordings.
- Uses pyannote.audio 4.1.1 and its `community-1` model, which needs PyTorch 2.8 or newer. The installer pins torch and torchaudio (2.11.0) together and holds them with a constraints file so pyannote's dependencies cannot replace the CUDA build.
- PyAV is kept below version 19, because faster-whisper 1.2.1 passes an argument that PyAV 19 removed.
- The words are matched against pyannote's "exclusive" diarization, which has no overlapping turns.
- Speaker changes are moved to sentence boundaries: a sentence ends at `.`, `?`, `!` or a pause of 0.8 s, and a short stretch (under 2 s) by another speaker inside a sentence goes to whoever speaks most of it. Longer stretches are kept, so real interruptions still show, but a speaker change inside a long unpunctuated stretch can still fall mid-sentence. The thresholds are `PAUSE_SPLIT` and `MIN_RUN` at the top of the script.
