"""Short feedback tones: soft sine notes written once as WAV files, played asynchronously."""

from __future__ import annotations

import io
import logging
import wave

import numpy as np

from .paths import SOUNDS_DIR

logger = logging.getLogger(__name__)

RATE = 44100
# name -> notes as (Hz, ms). Rising = listening, falling = done, low = something went wrong.
TONES = {
    "start": ((660, 70), (990, 90)),
    "stop": ((990, 70), (660, 90)),
    "cancel": ((520, 120),),
    "error": ((220, 140), (0, 60), (220, 140)),
}


def tone_wav(notes, volume: float = 0.22) -> bytes:
    """16-bit mono WAV of the notes back to back (0 Hz = a rest), each with a short fade."""
    parts = []
    for hz, ms in notes:
        n = int(RATE * ms / 1000)
        t = np.arange(n) / RATE
        wave_ = np.sin(2 * np.pi * hz * t) if hz else np.zeros(n)
        fade = min(n // 2, int(RATE * 0.008))
        if fade:
            ramp = np.linspace(0.0, 1.0, fade)
            wave_[:fade] *= ramp
            wave_[-fade:] *= ramp[::-1]
        parts.append(wave_)
    pcm = (np.concatenate(parts) * volume * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._paths = {}
        try:
            SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
            for name, notes in TONES.items():
                path = SOUNDS_DIR / f"{name}.wav"
                data = tone_wav(notes)
                if not path.is_file() or path.read_bytes() != data:
                    path.write_bytes(data)
                self._paths[name] = str(path)
        except OSError:
            logger.exception("Could not write the feedback sounds")

    def play(self, name: str) -> None:
        if not self.enabled or name not in self._paths:
            return
        try:
            import winsound

            winsound.PlaySound(self._paths[name], winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            logger.debug("Could not play %s", name, exc_info=True)
