"""Tiny demo app for pyinstaller-doctor's end-to-end check.

It uses two packages that ship data files:

* customtkinter    - theme JSON files; pyinstaller-hooks-contrib has a hook for it.
* better_profanity - a word list and a JSON file opened via os.path.dirname(__file__);
                     no hook exists, so a plain ``pyinstaller app.py`` build crashes.

It prints and exits (no window), so it can run in a terminal or in CI.
"""

import sys

import customtkinter
from better_profanity import profanity


def main() -> int:
    profanity.load_censor_words()
    print("customtkinter theme loaded, button color:", customtkinter.ThemeManager.theme["CTkButton"]["fg_color"])
    print("better_profanity says:", profanity.censor("this build is crap"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
