# Third-party licenses

This repository's own code is under the [MIT license](LICENSE).

It does **not** contain or redistribute any of the software below. The installer
(`scripts\install.bat`) downloads it with pip from its own source, and each package stays under
its own license, which you can read in the package's `*.dist-info` folder after installing. This
file credits the projects and lists their licenses as declared in the metadata of the versions
that were installed when this file was written.

## Python packages

| Package | Version checked | License (as declared) | Used for |
|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Guillaume Klein) | 1.2.1 | MIT | Transcription |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) (OpenNMT) | 4.7.1 | MIT | Inference engine of faster-whisper |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) (Hervé Bredin) | 4.1.1 | MIT | Speaker labels |
| [PyTorch](https://pytorch.org) (PyTorch Team) | 2.11.0 | BSD-3-Clause | Used by pyannote.audio |
| [torchaudio](https://github.com/pytorch/audio) | 2.11.0 | BSD | Used by pyannote.audio |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) (Hugging Face, Inc.) | 1.12.0 | Apache-2.0 | Model download, access token |
| [PyAV](https://github.com/PyAV-Org/PyAV) | 17.0.1 | BSD-3-Clause | Reading audio, writing MP3 |
| [NumPy](https://numpy.org) | 2.4.0 | BSD-3-Clause (plus other permissive licenses for bundled parts) | Audio arrays |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) (Hubert Pham, S0D3S edition) | 0.2.12.9 | Apache-2.0 | Recording microphone and system audio (WASAPI loopback) |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) (Matthias Geier) | 0.5.5 | MIT | Live push-to-talk |
| [SoundFile](https://github.com/bastibe/python-soundfile) (Bastian Bechtold) | 0.13.1 | BSD-3-Clause | Live push-to-talk |
| [Pillow](https://python-pillow.org) | 12.3.0 | MIT-CMU | Tray icon |
| [pynput](https://github.com/moses-palmer/pynput) (Moses Palmér) | 1.8.1 | LGPL-3.0 | Live push-to-talk (hotkey) |
| [pystray](https://github.com/moses-palmer/pystray) (Moses Palmér) | 0.19.5 | LGPL-3.0 | Tray icon |

### Attribution notes

- **MIT, BSD, Apache-2.0, MIT-CMU:** these require that their copyright notice and license text
  stay with copies of the software. As nothing is redistributed here, that is satisfied by the
  license files that pip installs with each package. If you ever bundle these packages with this
  project (for example in an executable), include their license texts.
- **pynput and pystray (LGPL-3.0):** they are installed separately by pip and imported, not copied
  into this repository, so you can replace them with another version at any time. If you
  bundle them into a single executable, check the LGPL-3.0 conditions first.
- **tkinter** is part of the Python standard library (Python Software Foundation License).

## Models (downloaded when first used)

- **Whisper models** are loaded through faster-whisper. The original Whisper models are by
  OpenAI. I believe they are MIT-licensed, but I have not verified the license of the converted
  model repositories that faster-whisper downloads from Hugging Face. Check the model card.
- **`pyannote/speaker-diarization-community-1`** is only used for "With speakers". It is
  gated: you accept its terms on Hugging Face and use your own token. I have not verified its
  license text. Read it on the model page:
  <https://huggingface.co/pyannote/speaker-diarization-community-1>

## Not verified

- PyAV's pip wheels ship with FFmpeg libraries. FFmpeg is LGPL or GPL depending on the build.
  I did not check which applies to this version. See `LICENSE.txt` in the installed
  `av-*.dist-info` folder.
- Versions change. Re-check the licenses if you update packages.
