"""Fixtures: fake site-packages folders with real .dist-info metadata, so tests never depend on
what happens to be installed."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

#: A package module that opens a data file next to itself, like better_profanity does.
LOADER = ("import os\n"
          "HERE = os.path.dirname(os.path.abspath(__file__))\n"
          "with open(os.path.join(HERE, 'words.txt')) as f:\n"
          "    WORDS = f.read().split()\n")


@pytest.fixture
def site(tmp_path: Path) -> Path:
    path = tmp_path / "site-packages"
    path.mkdir()
    return path


@pytest.fixture
def make_dist(site: Path) -> Callable[..., Path]:
    """Install a fake distribution: its files plus ``<name>-<version>.dist-info`` with a RECORD."""

    def make(name: str, files: dict[str, str], version: str = "1.0", entry_points: str = "",
             requires: tuple[str, ...] = (), top_level: tuple[str, ...] = ()) -> Path:
        for rel, content in files.items():
            target = site / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        info = site / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir()
        meta = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
        extra = {"METADATA": "\n".join(meta + [f"Requires-Dist: {r}" for r in requires]) + "\n"}
        if entry_points:
            extra["entry_points.txt"] = entry_points
        if top_level:
            extra["top_level.txt"] = "\n".join(top_level) + "\n"
        for fname, content in extra.items():
            (info / fname).write_text(content, encoding="utf-8")
        record = [f"{rel},," for rel in files] + [f"{info.name}/{f},," for f in [*extra, "RECORD"]]
        (info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
        return site

    return make


@pytest.fixture
def write(tmp_path: Path) -> Callable[[str, str], Path]:
    """Write a file below tmp_path (creating folders) and return its path."""

    def write_file(rel: str, content: str = "") -> Path:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    return write_file


@pytest.fixture
def hook(site: Path) -> Callable[[str, str], Path]:
    """Create ``PyInstaller/hooks/hook-<module>.py`` in the fake site-packages."""

    def make_hook(module: str, content: str) -> Path:
        path = site / "PyInstaller" / "hooks" / f"hook-{module}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    return make_hook
