"""app.py with every pyinstaller-doctor finding fixed.

* humanize is installed in the build environment (pip install humanize)
* settings.json is loaded through resource_path() and bundled with --add-data
* the exporters package is bundled with --collect-submodules exporters
* freeze_support() is the first call under ``if __name__ == "__main__":``
"""

import importlib
import json
import multiprocessing
import os
import sys

import humanize


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled file; works in development and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def load_settings() -> dict:
    with open(resource_path("settings.json"), encoding="utf-8") as f:
        return json.load(f)


def load_exporter(name: str):
    return importlib.import_module(f"exporters.{name}")


def square(x: int) -> int:
    return x * x


if __name__ == "__main__":
    multiprocessing.freeze_support()
    settings = load_settings()
    exporter = load_exporter(settings["exporter"])
    with multiprocessing.Pool(2) as pool:
        print(exporter.export(pool.map(square, range(5))), humanize.intcomma(1234567))
