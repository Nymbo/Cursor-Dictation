"""Entry point.

    python -m cursor_dictation                                    # tray app
    python -m cursor_dictation transcribe FILE.wav                # print a WAV file's transcript (no tray)
    python -m cursor_dictation transcribe FILE.wav --cpu          # same, on the CPU
    python -m cursor_dictation transcribe FILE.wav --multilingual # Parakeet v3 instead of English-only v2
"""

import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "transcribe":
        import logging

        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
        from .asr import cli_main

        return cli_main(argv[1:])
    from .app import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
