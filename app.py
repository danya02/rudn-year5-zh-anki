#!/usr/bin/env python3
"""
app.py — Entry point for the packaged (PyInstaller) build.

Double-clicking the bundled executable lands the user straight in the guided
wizard. On Windows we keep the console window open at the end so a
double-click user can read the final message instead of the window vanishing.
"""

import sys

import wizard
from paths import force_utf8, is_frozen


def main() -> None:
    force_utf8()
    try:
        wizard.run()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
    finally:
        if is_frozen() and sys.platform.startswith("win"):
            try:
                input("\n  Press Enter to close this window …")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    main()
