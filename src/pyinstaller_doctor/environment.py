"""Look inside a Python environment: site-packages, installed distributions and PyInstaller hooks."""

from __future__ import annotations

import os
import re
import sys
import sysconfig
from dataclasses import dataclass
from functools import cached_property
from importlib import metadata
from pathlib import Path
from typing import Sequence, Union

from .models import DoctorError

PathLike = Union[str, "os.PathLike[str]"]

NATIVE_RE = re.compile(r"\.(pyd|dll|dylib)$|\.so(\.\d+)*$", re.IGNORECASE)
SHARED_LIB_RE = re.compile(r"\.(dll|dylib)$|^lib.*\.so(\.\d+)*$|\.so\.\d+", re.IGNORECASE)
NOT_DATA = {".py", ".pyc", ".pyo", ".pyi", ".pyx", ".pxd", ".pxi", ".c", ".h", ".cpp", ".hpp"}
JUNK_FILES = {"py.typed", ".DS_Store", "Thumbs.db", "desktop.ini"}
DOC_RE = re.compile(r"(licen[cs]e|copying|authors|notice|readme|changelog|changes|history)\b", re.I)
TEST_DIRS = {"tests", "test"}
HOOK_SKIP_DIRS = {"pre_safe_import_module", "pre_find_module_path", "rthooks"}
NOT_PLUGIN_GROUPS = {"console_scripts", "gui_scripts", "pyinstaller40"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
REQUIREMENT_RE = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
HOOK_PATTERNS = {"data": r"collect_data_files|\bdatas\b", "binaries": r"collect_dynamic_libs|\bbinaries\b",
                 "submodules": r"collect_submodules|\bhiddenimports\b",
                 "metadata": r"copy_metadata|collect_entry_point"}


def normalize(name: str) -> str:
    """PEP 503 normalized distribution name (``Foo_Bar`` -> ``foo-bar``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_native(path: str) -> bool:
    """True for compiled code: ``.pyd``, ``.so``, ``.dll``, ``.dylib``."""
    return bool(NATIVE_RE.search(path))


def is_shared_lib(path: str) -> bool:
    """True for native libraries that are not Python extension modules (``x.dll``, ``libx.so.1``)."""
    return bool(SHARED_LIB_RE.search(path.rsplit("/", 1)[-1]))


def is_data(path: str) -> bool:
    """True for files a package may open at runtime (json, txt, png, ttf, qss, onnx, ...)."""
    name = path.rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    if is_native(name) or name in JUNK_FILES or ext in NOT_DATA:
        return False
    return not (DOC_RE.match(name) and ext in ("", ".txt", ".md", ".rst"))


def in_tests(path: str) -> bool:
    """True when the file sits in a ``tests``/``test`` folder (not needed at runtime)."""
    return any(part in TEST_DIRS for part in path.split("/")[:-1])


def site_packages_for_venv(venv: PathLike) -> list[Path]:
    """site-packages folder(s) of a virtual environment, Windows or POSIX layout."""
    root = Path(venv)
    if not root.is_dir():
        raise DoctorError(f"--venv {root}: folder not found")
    if root.name in ("site-packages", "dist-packages") or any(root.glob("*.dist-info")):
        return [root]
    candidates = [root / "Lib" / "site-packages", *sorted(root.glob("lib*/python3*/site-packages"))]
    found = [path for path in candidates if path.is_dir()]
    if not found:
        raise DoctorError(f"--venv {root}: no Lib/site-packages or lib/python3.X/site-packages inside")
    return found


def default_site_packages() -> list[Path]:
    """The activated virtualenv (``VIRTUAL_ENV``) if it is not ours, else this interpreter's path."""
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and Path(venv).is_dir() and Path(venv).resolve() != Path(sys.prefix).resolve():
        try:
            return site_packages_for_venv(venv)
        except DoctorError:
            pass
    paths = sysconfig.get_paths()
    skip = {Path(p).resolve() for p in (paths["stdlib"], paths["platstdlib"],
                                         os.path.join(sys.base_prefix, "DLLs"))}
    found: list[Path] = []
    for entry in sys.path:
        if entry and os.path.isdir(entry):
            path = Path(entry).resolve()
            if path not in skip and path not in found:
                found.append(path)
    return found


def stdlib_module_names() -> frozenset[str]:
    """Top-level standard library names (``sys.stdlib_module_names``, or a folder listing on 3.9)."""
    names = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    if not hasattr(sys, "stdlib_module_names"):  # Python 3.9
        stdlib = sysconfig.get_paths()["stdlib"]
        for folder in (stdlib, os.path.join(stdlib, "lib-dynload"), os.path.join(sys.base_prefix, "DLLs")):
            if os.path.isdir(folder):
                names.update(e.split(".")[0] for e in os.listdir(folder) if e != "site-packages")
    return frozenset(names)


@dataclass
class DistInfo:
    """What one installed distribution put into site-packages."""

    name: str
    version: str
    location: Path
    files: list[str]  # posix paths relative to ``location``; no .dist-info, __pycache__ or ../
    top_level: list[str]  # import names
    entry_points: dict[str, list[tuple[str, str]]]  # group -> [(name, "module:attr")]
    requires: list[str]  # normalized names of non-extra requirements

    @property
    def key(self) -> str:
        """Normalized name, used for lookups."""
        return normalize(self.name)

    def files_under(self, top: str) -> list[str]:
        """Files of the import package or single-file module ``top``."""
        return [f for f in self.files
                if f.split("/", 1)[0] == top or ("/" not in f and f.split(".", 1)[0] == top)]

    def outside_native(self) -> dict[str, list[str]]:
        """Native libraries in folders that are not import packages, e.g. ``numpy.libs/``."""
        found: dict[str, list[str]] = {}
        for f in self.files:
            folder = f.split("/", 1)[0]
            if "/" in f and folder not in self.top_level and is_native(f) and not in_tests(f):
                found.setdefault(folder, []).append(f)
        return found


@dataclass
class Hook:
    """A PyInstaller hook file, ``hook-<module>.py``."""

    module: str
    path: Path
    provider: str

    @cached_property
    def collects(self) -> frozenset[str]:
        """What the hook bundles: any of ``data``, ``binaries``, ``submodules``, ``metadata``."""
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return frozenset()
        if "collect_all" in text:
            return frozenset(HOOK_PATTERNS)
        return frozenset(kind for kind, pattern in HOOK_PATTERNS.items() if re.search(pattern, text))

    def describe(self) -> str:
        """Human-readable origin, e.g. ``hook-plotly.py from pyinstaller-hooks-contrib``."""
        return f"hook-{self.module}.py from {self.provider}"


def _load(dist: metadata.Distribution) -> DistInfo | None:
    """Read one distribution's RECORD, top_level.txt, entry points and requirements."""
    name = dist.metadata.get("Name") if dist.metadata is not None else None
    if not name:
        return None
    location = Path(str(dist.locate_file("")))
    raw = dist.files
    files = ["/".join(f.parts) for f in raw or ()
             if f.parts and f.parts[0] != ".." and "__pycache__" not in f.parts
             and not f.parts[0].endswith((".dist-info", ".egg-info"))]
    declared = (dist.read_text("top_level.txt") or "").split()
    inferred = {f.split("/", 1)[0] if "/" in f else f.split(".", 1)[0]
                for f in files if "/" in f or f.endswith((".py", ".pyd", ".so"))}
    top_level = sorted(t for t in (declared or inferred) if IDENTIFIER_RE.match(t))
    if raw is None:  # no RECORD (old egg-info install): walk the package folders instead
        for top in top_level:
            base = location / top
            if base.is_dir():
                files += [p.relative_to(location).as_posix() for p in base.rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts]
            elif (location / f"{top}.py").is_file():
                files.append(f"{top}.py")
    entry_points: dict[str, list[tuple[str, str]]] = {}
    for ep in dist.entry_points:
        entry_points.setdefault(ep.group, []).append((ep.name, ep.value))
    requires = []
    for requirement in dist.requires or ():
        match = REQUIREMENT_RE.match(requirement)
        if match and "extra" not in requirement.partition(";")[2]:
            requires.append(normalize(match.group(1)))
    return DistInfo(name, dist.version, location, files, top_level, entry_points, requires)


class Environment:
    """Installed distributions and PyInstaller hooks of the environment your app is built from."""

    def __init__(self, paths: Sequence[PathLike], hooks_dirs: Sequence[PathLike] = ()) -> None:
        self.paths = [Path(p) for p in paths]
        self.hooks_dirs = [Path(p) for p in hooks_dirs]
        self.stdlib = stdlib_module_names()
        self.dists: list[DistInfo] = []
        self.by_key: dict[str, DistInfo] = {}
        self.by_top: dict[str, list[DistInfo]] = {}
        for dist in metadata.distributions(path=[str(p) for p in self.paths]):
            info = _load(dist)
            if info is not None and info.key not in self.by_key:  # first one wins, like Python
                self.dists.append(info)
                self.by_key[info.key] = info
                for top in info.top_level:
                    self.by_top.setdefault(top, []).append(info)
        self.hooks = self._index_hooks()

    @classmethod
    def from_options(cls, venv: PathLike | None = None, site_packages: Sequence[PathLike] | None = None,
                     hooks_dirs: Sequence[PathLike] = ()) -> Environment:
        """Environment from CLI-style options: explicit site-packages, a venv, or the active one."""
        if site_packages:
            paths = [Path(p) for p in site_packages]
            missing = [str(p) for p in paths if not p.is_dir()]
            if missing:
                raise DoctorError(f"--site-packages: folder not found: {', '.join(missing)}")
        elif venv:
            paths = site_packages_for_venv(venv)
        else:
            paths = default_site_packages()
        for folder in hooks_dirs:
            if not Path(folder).is_dir():
                raise DoctorError(f"--hooks-dir {folder}: folder not found")
        return cls(paths, hooks_dirs)

    def dists_for_top(self, top: str) -> list[DistInfo]:
        """Distributions that provide the import name ``top``."""
        return self.by_top.get(top, [])

    def dist(self, name: str) -> DistInfo | None:
        """Distribution by (any spelling of) its name."""
        return self.by_key.get(normalize(name))

    def hook_for(self, module: str) -> Hook | None:
        """The hook PyInstaller would use for ``module``, if any."""
        return self.hooks.get(module)

    def plugin_providers(self, group: str) -> list[tuple[DistInfo, str, str]]:
        """``(distribution, name, "module:attr")`` for every entry point in ``group``."""
        return [(d, name, value) for d in self.dists for name, value in d.entry_points.get(group, [])]

    def module_exists(self, name: str) -> bool:
        """True when the dotted module ``name`` is installed here."""
        top, _, rest = name.partition(".")
        dists = self.dists_for_top(top)
        if not rest:
            return bool(dists)
        base = name.replace(".", "/")
        return any(f == base + ".py" or f.startswith(base + "/") or (f.startswith(base + ".") and is_native(f))
                   for d in dists for f in d.files)

    def _index_hooks(self) -> dict[str, Hook]:
        """Map module name -> Hook: your hooks dirs, package-provided, contrib, then PyInstaller's own."""
        hooks: dict[str, Hook] = {}

        def add(path: Path, provider: str) -> None:
            module = path.name[len("hook-"):-len(".py")]
            hooks.setdefault(module, Hook(module, path, provider))

        for folder in self.hooks_dirs:
            for path in sorted(folder.glob("hook-*.py")):
                add(path, f"your hooks folder {folder}")
        for dist in self.dists:
            if "pyinstaller40" in dist.entry_points:  # packages that register their own hook dirs
                for f in dist.files:
                    parts = f.split("/")
                    if parts[-1].startswith("hook-") and f.endswith(".py") and not HOOK_SKIP_DIRS.intersection(parts):
                        add(dist.location / f, dist.name)
        for site in self.paths:
            for sub, provider in (("_pyinstaller_hooks_contrib/stdhooks", "pyinstaller-hooks-contrib"),
                                  ("_pyinstaller_hooks_contrib/hooks/stdhooks", "pyinstaller-hooks-contrib"),
                                  ("PyInstaller/hooks", "PyInstaller")):
                folder = site / sub
                if folder.is_dir():
                    for path in sorted(folder.glob("hook-*.py")):
                        add(path, provider)
        return hooks
