"""The microphone: a WASAPI input stream at the device's own rate, resampled to 16 kHz mono."""

from __future__ import annotations

import logging
import threading

import numpy as np
import pyaudiowpatch as pyaudio
import soxr

logger = logging.getLogger(__name__)

SR = 16000


def _wasapi(pa: pyaudio.PyAudio) -> dict:
    return pa.get_host_api_info_by_type(pyaudio.paWASAPI)


def _inputs(pa: pyaudio.PyAudio):
    api = _wasapi(pa)
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["hostApi"] == api["index"] and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
            yield d


def list_microphones() -> list[str]:
    pa = pyaudio.PyAudio()
    try:
        return [d["name"] for d in _inputs(pa)]
    finally:
        pa.terminate()


class Recorder:
    """One recording at a time. `start()` opens the mic; `stop()` closes it and returns the audio."""

    def __init__(self):
        self.label = ""
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._resampler: soxr.ResampleStream | None = None
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._channels = 1
        self._lock = threading.Lock()

    @property
    def seconds(self) -> float:
        return self._samples / SR

    def start(self, device_name: str = "") -> None:
        with self._lock:
            self._close()
            self._chunks, self._samples = [], 0
            self._pa = pyaudio.PyAudio()
            try:
                dev = self._pick(device_name)
                self._channels = max(1, int(dev["maxInputChannels"]))
                rate = int(dev["defaultSampleRate"])
                self._resampler = soxr.ResampleStream(rate, SR, 1, dtype="float32", quality="HQ")
                self._stream = self._pa.open(format=pyaudio.paFloat32, channels=self._channels, rate=rate,
                                             input=True, input_device_index=dev["index"],
                                             frames_per_buffer=int(rate * 0.02), stream_callback=self._callback)
                self._stream.start_stream()
            except Exception:
                self._close()
                raise
            self.label = dev["name"]
            logger.info("Recording from %s (%d ch @ %d Hz)", dev["name"], self._channels, rate)

    def stop(self) -> np.ndarray:
        """Close the mic and return everything recorded, 16 kHz mono float32."""
        with self._lock:
            self._close()
            if self._resampler is not None:
                tail = self._resampler.resample_chunk(np.zeros(0, np.float32), last=True)
                if tail.size:
                    self._chunks.append(tail)
                self._resampler = None
            chunks, self._chunks, self._samples = self._chunks, [], 0
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.exception("Error closing the microphone")
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def _pick(self, device_name: str) -> dict:
        pa = self._pa
        if device_name:
            for d in _inputs(pa):
                if d["name"] == device_name:
                    return d
            logger.warning("Microphone %r not found; using the default", device_name)
        index = _wasapi(pa)["defaultInputDevice"]
        if index < 0:
            raise RuntimeError("no microphone found")
        return pa.get_device_info_by_index(index)

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            frames = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self._channels)
            mono = frames[:, :2].mean(axis=1) if self._channels > 1 else frames[:, 0]
            out = self._resampler.resample_chunk(mono.astype(np.float32, copy=False))
            if out.size:
                self._chunks.append(out)
                self._samples += out.size
        except Exception:
            logger.exception("Microphone callback failed")
        return (None, pyaudio.paContinue)
