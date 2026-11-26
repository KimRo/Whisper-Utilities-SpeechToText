# TODO

## Upgrade pyannote.audio from 3.4.0 to 4.x  (done, see notes at the end)

Originally `transcribe_speakers.py` was pinned to `pyannote.audio==3.4.0` because 4.x needs a newer PyTorch than the installer offers. It now uses `pyannote.audio==4.1.1`.

What I found when checking the 4.1.1 wheel (verify against the current pyannote docs before upgrading):
- Requires `torch>=2.8.0`, `torchaudio>=2.8.0` and `torchcodec>=0.7.0`. This machine has torch 2.6.0+cu124.
- Default model is `pyannote/speaker-diarization-community-1`. It is gated, so its terms must be accepted on Hugging Face.
- `Pipeline.from_pretrained` takes `token=` instead of `use_auth_token=`.

Steps:
- [x] Update the PyTorch options in `scripts/install/install.ps1` (the `$cudaOptions` list) to builds that provide torch 2.8+, and install torchaudio from the same index. (CPU / cu126 default / cu128 / cu130; torch and torchaudio both pinned to 2.11.0, which exists on all four indexes. The cu121/cu124 indexes stop at torch 2.6.0.)
- [x] Add `torchcodec` and check that it works on Windows. (It installs as a pyannote.audio dependency and imports. The script passes audio as an in-memory waveform, so torchcodec's FFmpeg decoding is not used.)
- [x] In `scripts/transcribe_speakers.py`, change `DIARIZATION_MODEL` and the `use_auth_token=` argument. (Also uses `output.exclusive_speaker_diarization`; the torch 2.6 allow-list workaround was removed.)
- [x] Update the setup steps in the script docstring and `doc/transcribe_speakers.md` (model pages to accept).
- [x] Update the pin in `install.ps1`, `uninstall.ps1` and `README.md`.
- [x] Check that `faster-whisper`/`ctranslate2` still work with the newer torch and CUDA build. (ctranslate2 4.9.1 loads CUDA fine. Found: PyAV 19 breaks faster-whisper 1.2.1, so `av<19` is pinned.)