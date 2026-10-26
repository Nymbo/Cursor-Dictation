# Parakeet Tray

Dictation for Windows. Press a hotkey, talk, and what you said is typed wherever your cursor
is: an editor, a chat box, a browser, a terminal. It runs in the system tray.

- **Local.** NVIDIA's Parakeet TDT 0.6B v3 runs on your NVIDIA GPU, or on the CPU when
  there isn't one. Audio never leaves the PC.
- **Fast.** On a GTX 1070, 7 seconds of speech comes back in about a second and 80 seconds
  in under one. The CPU (int8) model is about as quick for short clips.
- **Punctuated.** Parakeet writes capitals and punctuation itself, and handles 25 European
  languages without being told which one you're speaking.
- **Tap or hold.** Tap the hotkey to start and again to stop, or hold it while you talk
  and let go. Esc cancels.
- **Leaves your clipboard alone.** Text goes in by paste, the one method nearly every app
  accepts, and whatever was on the clipboard before (text, an image, files) is put back
  afterwards. The dictated text stays out of Windows' clipboard history.

## Install

Needs Windows 10 or 11, Python 3.13 and [uv](https://docs.astral.sh/uv/). For the GPU, an
NVIDIA card with ~2.5 GB of free VRAM and a current driver; CUDA itself comes from pip.

```powershell
git clone https://github.com/Nymbo/Parakeet-Tray.git
cd Parakeet-Tray
.\setup.ps1
.\.venv\Scripts\pythonw.exe run.pyw          # the tray app, no console window
```

`.\.venv\Scripts\python.exe -m parakeet_tray` runs it with a console (log output). A second
launch opens the running copy's settings. The speech model downloads on first use into
the Hugging Face cache: about 2.5 GB for the GPU, or 670 MB for the CPU.

To try the model without the tray:

```powershell
.\.venv\Scripts\python.exe -m parakeet_tray transcribe clip.wav          # add --cpu for the CPU
```

## Using it

- **Dictate:** press **Ctrl+\\** (change it in Settings). A rising tone means it's
  listening, a falling tone means it's transcribing. The text is pasted into whichever
  window has focus when the transcription finishes.
- **Tray icon:** amber while the model loads, teal when ready, red while listening, blue
  while transcribing, grey if the model couldn't load. Click it for Settings. The menu also
  has Cancel and "Copy last dictation" (for when the paste landed in the wrong place).
- **Settings:** the hotkey, the microphone (or "Windows default", which follows changes),
  GPU or CPU, the tones, a trailing space after each dictation, clipboard restore, and
  "Start with Windows".
- A recording stops on its own after 15 minutes. Long recordings are split at pauses and
  transcribed piece by piece.

Settings live in `%APPDATA%\Parakeet-Tray\settings.json`, logs in
`%LOCALAPPDATA%\Parakeet-Tray\logs`.

## How it works

`capture.py` records the microphone through WASAPI at the device's own rate and resamples
to 16 kHz mono (soxr). `asr.py` runs Parakeet through
[onnx-asr](https://github.com/istupakov/onnx-asr) on ONNX Runtime: fp32 with CUDA on the
GPU, int8 on the CPU, with a CPU fallback if CUDA won't start. `paste.py` puts the text on
the clipboard, waits for you to let go of the hotkey's modifiers, sends Ctrl+V, and
restores the clipboard. The hotkey is a Win32 `RegisterHotKey`, so no keyboard hook is
installed.

Before October 2026 this app lived in a monorepo and ran Parakeet on NVIDIA NeMo and
PyTorch. It now uses the same ONNX engine as its sibling apps, Live Subtitles and Meeting
Context: the environment went from 4.8 GB to 3 GB (most of what's left is CUDA and cuDNN),
the model is ready 3 to 5 seconds after launch, and it no longer needs a low-level
keyboard hook.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## License

MIT. The speech model, [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3),
is licensed CC-BY-4.0 by NVIDIA; the ONNX export is
[istupakov/parakeet-tdt-0.6b-v3-onnx](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx).
