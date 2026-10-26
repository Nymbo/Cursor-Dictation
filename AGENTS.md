# Agent Instructions

Cursor Dictation is a Windows tray app (PySide6) for dictation: a global hotkey records the
microphone, NVIDIA Parakeet TDT 0.6B transcribes it locally (v2 for English by default, v3
for 25 languages), and the text is pasted at the cursor of whatever window has focus.
Public repository (MIT). The README's "Model choice" section records why v2 is the
default; re-measure with Live Subtitles' `bench.phrases` before changing it.

It was called Parakeet Tray until 2026-10-26, when it moved out of the owner's HF-Dev
monorepo (the NeMo/PyTorch version is in that repo's history) and was rebuilt on the
conventions of its siblings, Live Subtitles (`Nymbo/Live-Subtitles`) and Meeting Context
(a private repo). They share code by copying, never at runtime; don't import across repos.

## Layout

- `cursor_dictation/app.py` wires it together and owns the one-at-a-time state machine
  (idle -> recording -> transcribing -> idle), the hotkey's tap-or-hold logic, and the
  single-instance check (a named mutex; a second launch opens Settings in the first).
- `capture.py` (WASAPI mic -> 16 kHz mono float32), `asr.py` (onnx-asr Parakeet; the
  `Engine` loads on a thread, `transcribe` splits long audio at pauses), `paste.py`
  (clipboard snapshot, Ctrl+V, restore), `hotkeys.py` (Win32 `RegisterHotKey` through a
  Qt native event filter), `sounds.py` (generated tones), `tray.py`, `settings_window.py`,
  `settings.py`, `paths.py`, `autostart.py`.
- `python -m cursor_dictation transcribe FILE.wav [--cpu]` runs the engine without the tray.
- `tests/test_core.py` covers the pure-Python parts.

## Rules that are easy to break

- **One ONNX Runtime per process.** The app imports `onnxruntime-gpu` (through onnx-asr)
  in-process. Never add sherpa-onnx, or anything else that ships its own
  `onnxruntime.dll`: whichever loads second breaks. If a feature needs one, run it in a
  child process the way Meeting Context's `asr-worker` does.
- **Pins for Pascal GPUs** (the dev machine has a GTX 1070): `onnxruntime-gpu` stays below
  1.27 (the first CUDA 13 build drops Pascal) and `nvidia-cudnn-cu12` at 9.10.2.21 (9.11+
  fails on Pascal), as in the sibling repos. Move all three repos together.
- **No keyboard hooks.** Hotkeys are `RegisterHotKey`; key release is read with
  `GetAsyncKeyState`. Don't bring back the `keyboard` package: it installs a global
  low-level hook that sees every keystroke on the machine.
- **The clipboard is the user's.** `paste.insert_text` restores what was there; keep that
  working for non-text formats (images, files), and keep the history-exclusion format on
  the transient text.
- **Data lives outside the repo.** Settings in `%APPDATA%\Cursor-Dictation`; logs and the
  generated tones in `%LOCALAPPDATA%\Cursor-Dictation`; the model in the Hugging Face cache.
  `APP_NAME` names those folders and the instance mutex, so changing it orphans settings.
- The repo is public: no personal paths, names or recordings in code, tests or docs.

## Environment and checks

- `.\setup.ps1` builds `.venv` with uv from `requirements.txt`. Don't install with bare
  pip; change `requirements.txt` and re-run the script.
- Verify with the unit tests and the import check. A full launch registers a global
  hotkey and pastes into the focused window, so only launch it when the task needs that:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -c "import cursor_dictation.app, cursor_dictation.settings_window, cursor_dictation.asr; print('imports ok')"
```

- For engine changes, transcribe a real WAV with both models on both devices:
  `python -m cursor_dictation transcribe clip.wav`, then with `--cpu`, `--multilingual`, and both.
