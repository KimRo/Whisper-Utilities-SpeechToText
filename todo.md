# TODO

## Upgrade pyannote.audio from 3.4.0 to 4.x

`transcribe_speakers.py` is pinned to `pyannote.audio==3.4.0` because 4.x needs a newer PyTorch than the installer offers.

What I found when checking the 4.1.1 wheel (verify against the current pyannote docs before upgrading):
- Requires `torch>=2.8.0`, `torchaudio>=2.8.0` and `torchcodec>=0.7.0`. This machine has torch 2.6.0+cu124.
- Default model is `pyannote/speaker-diarization-community-1`. It is gated, so its terms must be accepted on Hugging Face.
- `Pipeline.from_pretrained` takes `token=` instead of `use_auth_token=`.

Steps:
- [ ] Update the PyTorch options in `scripts/install/install.ps1` (the `$cudaOptions` list) to builds that provide torch 2.8+, and install torchaudio from the same index.
- [ ] Add `torchcodec` and check that it works on Windows.
- [ ] In `scripts/transcribe_speakers.py`, change `DIARIZATION_MODEL` and the `use_auth_token=` argument.
- [ ] Update the setup steps in the script docstring and `doc/transcribe_speakers.md` (model pages to accept).
- [ ] Update the pin in `install.ps1`, `uninstall.ps1` and `README.md`.
- [ ] Check that `faster-whisper`/`ctranslate2` still work with the newer torch and CUDA build.
- [ ] Test on a two-speaker sample and compare with the 3.4.0 output.