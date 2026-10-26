"""Speech recognition: NVIDIA Parakeet TDT 0.6B v3 on onnx-asr (ONNX Runtime, GPU or CPU).

The same model and export the sibling apps use (Meeting Context, Live Subtitles' file
transcription), from istupakov/parakeet-tdt-0.6b-v3-onnx in the Hugging Face cache:
fp32 on the GPU (~2.5 GB download), int8 on the CPU (~670 MB). Parakeet writes punctuation
and capitals itself, and handles 25 European languages without being told which.

This process imports onnxruntime-gpu. Never add sherpa-onnx (or anything else that ships
its own onnxruntime.dll) to it: whichever loads second breaks. See AGENTS.md.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

SR = 16000
MODEL = "nemo-parakeet-tdt-0.6b-v3"          # onnx_asr.load_model name
REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
PAD_S = 0.3                # silence around the clip: a word cut off by releasing the key still decodes
MAX_CHUNK_S = 40.0         # longer recordings are cut at a pause (attention memory grows with length)
MIN_CHUNK_S = 25.0
SILENCE_RMS = 0.002        # loudest 50 ms below this = nothing was said

_FRAME = SR // 20          # 50 ms


def frame_rms(audio: np.ndarray, frame: int = _FRAME) -> np.ndarray:
    n = audio.size // frame
    if n == 0:
        return np.zeros(0, np.float32)
    blocks = audio[:n * frame].reshape(n, frame).astype(np.float32)
    return np.sqrt(np.mean(blocks * blocks, axis=1))


def is_silent(audio: np.ndarray) -> bool:
    rms = frame_rms(audio)
    return rms.size == 0 or float(rms.max()) < SILENCE_RMS


def split_points(audio: np.ndarray, max_s: float = MAX_CHUNK_S, min_s: float = MIN_CHUNK_S) -> list[tuple[int, int]]:
    """Cut long audio into pieces of at most max_s, each ending at the quietest moment after min_s."""
    total, max_n, min_n = audio.size, int(max_s * SR), int(min_s * SR)
    spans, start = [], 0
    while total - start > max_n:
        window = audio[start + min_n:start + max_n]
        rms = frame_rms(window)
        cut = start + min_n + int(np.argmin(rms)) * _FRAME + _FRAME // 2 if rms.size else start + max_n
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def cuda_available() -> bool:
    """An NVIDIA GPU with a working driver? Asks nvcuda.dll directly, before loading ONNX Runtime."""
    import ctypes

    try:
        cuda = ctypes.WinDLL("nvcuda.dll") if sys.platform == "win32" else ctypes.CDLL("libcuda.so.1")
    except OSError:
        return False
    count = ctypes.c_int(0)
    return cuda.cuInit(0) == 0 and cuda.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0


def model_cached(gpu: bool) -> bool:
    """Is this variant of the model already downloaded?"""
    try:
        from huggingface_hub import try_to_load_from_cache

        name = "encoder-model.onnx" if gpu else "encoder-model.int8.onnx"
        return isinstance(try_to_load_from_cache(REPO, name), str)
    except Exception:
        return False


def load_model(use_gpu: bool):
    """(onnx-asr model, "GPU" | "CPU"). Falls back to the CPU if CUDA won't come up."""
    import onnxruntime as ort
    import onnx_asr

    ort.set_default_logger_severity(3)      # errors only: the CUDA graph-partition warnings are expected
    providers = ["CPUExecutionProvider"]
    if use_gpu:
        try:
            ort.preload_dlls()          # CUDA and cuDNN from the nvidia-* pip packages
        except Exception:
            logger.warning("Could not preload CUDA DLLs", exc_info=True)
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "CUDAExecutionProvider")
    gpu = providers[0].startswith("CUDA")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    model = onnx_asr.load_model(MODEL, quantization=None if gpu else "int8", providers=providers, sess_options=opts)
    return model, "GPU" if gpu else "CPU"


class Engine:
    """Loads the model on a background thread; `transcribe` waits for it."""

    def __init__(self, on_state: Callable[[str, str], None] = lambda state, detail: None):
        self.on_state = on_state          # ("loading" | "ready" | "error", detail), from the loader thread
        self.device = ""
        self.error = ""
        self._model = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self, recognizer: str = "auto") -> None:
        """Start (re)loading. recognizer: auto | gpu | cpu."""
        self._generation += 1
        gen = self._generation
        self._ready.clear()
        self._model, self.error = None, ""
        threading.Thread(target=self._load, args=(gen, recognizer), name="asr-load", daemon=True).start()

    def _load(self, gen: int, recognizer: str) -> None:
        want_gpu = recognizer == "gpu" or (recognizer == "auto" and cuda_available())
        detail = "" if model_cached(want_gpu) else ("downloading the speech model (about 2.5 GB, once)" if want_gpu
                                                    else "downloading the speech model (about 670 MB, once)")
        self.on_state("loading", detail)
        t0 = time.perf_counter()
        try:
            model, device = load_model(want_gpu)
            model.recognize(np.zeros(SR, np.float32), sample_rate=SR)   # the first CUDA run builds kernels
        except Exception as exc:
            logger.exception("Could not load the speech model")
            if gen == self._generation:
                self.error = f"{type(exc).__name__}: {exc}"
                self._ready.set()
                self.on_state("error", self.error)
            return
        if gen != self._generation:          # a newer load() replaced this one
            return
        self._model, self.device = model, device
        self._ready.set()
        logger.info("Speech model ready on the %s in %.1f s", device, time.perf_counter() - t0)
        self.on_state("ready", device)

    def transcribe(self, audio: np.ndarray, timeout: float = 900.0) -> str:
        """16 kHz mono float32 -> text ("" if nothing was said)."""
        if is_silent(audio):
            return ""
        if not self._ready.wait(timeout):
            raise RuntimeError("the speech model is still loading")
        model = self._model
        if model is None:
            raise RuntimeError(self.error or "the speech model is not loaded")
        pad = np.zeros(int(PAD_S * SR), np.float32)
        parts = []
        with self._lock:
            for s, e in split_points(audio):
                piece = np.concatenate([pad, audio[s:e].astype(np.float32, copy=False), pad])
                parts.append(clean_text(model.recognize(piece, sample_rate=SR)))
        return clean_text(" ".join(p for p in parts if p))


def read_audio(path: str) -> np.ndarray:
    """A WAV file -> 16 kHz mono float32 (8/16/24/32-bit PCM, any rate, any channel count)."""
    import wave

    import soxr

    with wave.open(path, "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        data = (np.where(ints >= 1 << 23, ints - (1 << 24), ints)).astype(np.float32) / (1 << 23)
    else:
        dtype = {2: np.int16, 4: np.int32}[width]
        data = np.frombuffer(raw, dtype).astype(np.float32) / float(np.iinfo(dtype).max)
    data = data.reshape(-1, ch).mean(axis=1)
    return soxr.resample(data, rate, SR).astype(np.float32) if rate != SR else data


def cli_main(argv: list[str]) -> int:
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print("usage: python -m parakeet_tray transcribe FILE.wav [--cpu]", file=sys.stderr)
        return 2
    model, device = load_model("--cpu" not in argv)
    logger.info("Model on the %s", device)
    for path in files:
        audio = read_audio(path)
        t0 = time.perf_counter()
        text = clean_text(" ".join(model.recognize(audio[s:e], sample_rate=SR) for s, e in split_points(audio)))
        logger.info("%s: %.1f s of audio in %.2f s", path, audio.size / SR, time.perf_counter() - t0)
        print(text)
    return 0
