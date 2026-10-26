"""Unit tests for the pure-Python pieces: hotkeys, settings, audio splitting, text, tones.

    .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import io
import itertools
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from parakeet_tray import settings as S
from parakeet_tray.asr import SR, clean_text, is_silent, read_audio, split_points
from parakeet_tray.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse
from parakeet_tray.sounds import TONES, tone_wav


class HotkeyTests(unittest.TestCase):
    def test_default_backslash(self):
        self.assertEqual(parse("Ctrl+\\"), (MOD_CONTROL, 0xDC))

    def test_modifiers_and_function_keys(self):
        self.assertEqual(parse("Ctrl+Alt+Shift+F9"), (MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x78))
        self.assertEqual(parse("Alt+Space"), (MOD_ALT, 0x20))
        self.assertEqual(parse("Esc"), (0, 0x1B))

    def test_plus_key(self):
        self.assertEqual(parse("Ctrl++"), (MOD_CONTROL, 0xBB))

    def test_rejects_garbage(self):
        for text in ("", "  ", "Ctrl", "Ctrl+Banana"):
            self.assertIsNone(parse(text), text)


class SettingsTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            s = S.Settings(hotkey="Ctrl+Alt+D", mic="USB Mic", recognizer="cpu", sounds=False)
            S.save(s, path)
            self.assertEqual(S.load(path), s)

    def test_default_model_is_english_and_every_choice_exists(self):
        from parakeet_tray.asr import DEFAULT_MODEL, MODELS
        from parakeet_tray.settings_window import LANGUAGES

        self.assertEqual(S.Settings().model, DEFAULT_MODEL)
        self.assertEqual({v for _, v in LANGUAGES}, set(MODELS))

    def test_missing_file_gives_defaults(self):
        self.assertEqual(S.load(Path(tempfile.gettempdir()) / "no-such-parakeet-settings.json"), S.Settings())

    def test_bad_types_and_unknown_keys_are_ignored(self):
        s = S.Settings.from_dict({"hotkey": 5, "sounds": "yes", "recognizer": "gpu", "future_option": 1})
        self.assertEqual(s.hotkey, S.Settings().hotkey)
        self.assertTrue(s.sounds)
        self.assertEqual(s.recognizer, "gpu")
        self.assertEqual(S.Settings.from_dict([1, 2]), S.Settings())

    def test_corrupt_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertLogs("parakeet_tray.settings", "ERROR"):
                self.assertEqual(S.load(path), S.Settings())


class AudioTests(unittest.TestCase):
    def test_short_audio_is_one_piece(self):
        self.assertEqual(split_points(np.ones(SR * 10, np.float32)), [(0, SR * 10)])

    def test_long_audio_is_cut_at_the_quiet_moment(self):
        audio = np.full(SR * 70, 0.3, np.float32)
        audio[SR * 31:SR * 31 + SR // 2] = 0.0       # a pause 31 s in
        spans = split_points(audio)
        self.assertEqual(spans[0][0], 0)
        self.assertTrue(SR * 31 <= spans[0][1] <= SR * 31 + SR // 2, spans)
        self.assertEqual(spans[-1][1], audio.size)
        for (_, e), (s, _) in itertools.pairwise(spans):
            self.assertEqual(e, s)                   # contiguous, nothing dropped
        self.assertTrue(all(e - s <= SR * 40 for s, e in spans))

    def test_silence(self):
        self.assertTrue(is_silent(np.zeros(SR, np.float32)))
        self.assertTrue(is_silent(np.zeros(10, np.float32)))
        noise = np.random.default_rng(0).normal(0, 0.05, SR).astype(np.float32)
        self.assertFalse(is_silent(noise))

    def test_clean_text(self):
        self.assertEqual(clean_text("  Hello,\n  world.  "), "Hello, world.")
        self.assertEqual(clean_text(None), "")

    def test_read_audio_resamples_and_downmixes(self):
        stereo = (np.stack([np.full(48000, 0.5), np.full(48000, -0.5)], axis=1) * 32767).astype("<i2")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "clip.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(stereo.tobytes())
            audio = read_audio(str(path))
        self.assertEqual(audio.dtype, np.float32)
        self.assertAlmostEqual(audio.size, SR, delta=2)
        self.assertLess(float(np.abs(audio).max()), 0.01)   # left and right cancel out


class ToneTests(unittest.TestCase):
    def test_every_tone_is_valid_wav(self):
        for name, notes in TONES.items():
            with wave.open(io.BytesIO(tone_wav(notes)), "rb") as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2), name)
                ms = sum(n[1] for n in notes)
                self.assertAlmostEqual(w.getnframes() / w.getframerate() * 1000, ms, delta=2, msg=name)

    def test_tones_start_and_end_quietly(self):
        data = tone_wav(TONES["start"])
        with wave.open(io.BytesIO(data), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        self.assertLess(abs(int(pcm[0])), 50)
        self.assertLess(abs(int(pcm[-1])), 300)


if __name__ == "__main__":
    unittest.main()
