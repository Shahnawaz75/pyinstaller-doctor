"""An app with the classic mistakes pyinstaller-doctor finds in your own code.

This is what NOT to do; run ``pyinstaller-doctor scan app.py`` on it to see the findings:

* ``humanize`` is imported but is not installed in the build environment
* ``settings.json`` is opened with a path relative to the current folder
* exporters are imported by name at run time (PyInstaller cannot see them)
* multiprocessing is used without ``freeze_support()``
"""

import importlib
import json
import multiprocessing

import humanize  # deliberately missing from the build venv


def load_settings() -> dict:
    with open("settings.json", encoding="utf-8") as f:
        return json.load(f)


def load_exporter(name: str):
    return importlib.import_module(f"exporters.{name}")


def square(x: int) -> int:
    return x * x


if __name__ == "__main__":
    settings = load_settings()
    exporter = load_exporter(settings["exporter"])
    with multiprocessing.Pool(2) as pool:
        print(exporter.export(pool.map(square, range(5))), humanize.intcomma(1234567))
