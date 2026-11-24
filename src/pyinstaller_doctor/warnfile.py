"""``pyinstaller-doctor warnfile``: explain ``build/<name>/warn-<name>.txt`` in plain English."""

from __future__ import annotations

import re
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .environment import Environment, PathLike
from .models import DoctorError, Finding, Fix, Report, Severity
from .project import find_local
from .scanner import PIP_NAMES, display

LINE_RE = re.compile(r"^(missing|excluded) module named (?:'([^']+)'|(\S+)) - imported by (.*)$")
KINDS = r"(?:top-level|conditional|delayed|optional)"
IMPORTER_RE = re.compile(rf"(.+?) \(({KINDS}(?:, {KINDS})*)\)(?:, |$)")

INTERNAL = {"_frozen_importlib", "_frozen_importlib_external", "__main__"}
RUNTIME_ALIASES = {"collections.abc", "os.path"}  # registered in sys.modules, no file of their own
PLATFORM_ONLY = {
    # POSIX only
    "posix", "pwd", "grp", "fcntl", "termios", "resource", "_posixsubprocess", "_posixshmem", "readline",
    "_curses", "_curses_panel", "syslog", "spwd", "crypt", "_crypt", "nis", "ossaudiodev", "_gdbm",
    "_dbm", "_scproxy", "_osx_support",
    # Windows only
    "nt", "winreg", "_winreg", "_winapi", "msvcrt", "_overlapped", "winsound", "_msi", "msilib",
    # other platforms and Python implementations
    "java", "org", "vms_lib", "riscos", "riscosenviron", "riscospath", "ce", "os2", "_emx_link",
    "EasyDialogs", "MacOS", "Carbon", "__pypy__", "_android_support", "_ios_support", "_wasi",
}
PYTHON2 = {"__builtin__", "urllib2", "urlparse", "StringIO", "cStringIO", "cPickle", "ConfigParser",
           "Queue", "thread", "httplib", "HTMLParser", "htmlentitydefs", "Cookie", "cookielib",
           "copy_reg", "commands", "sets", "exceptions", "md5", "sha", "anydbm", "dummy_thread",
           "_dummy_thread", "dummy_threading", "_dummy_threading", "SocketServer", "BaseHTTPServer",
           "SimpleHTTPServer", "Tkinter", "tkMessageBox", "tkFileDialog", "ttk", "xmlrpclib", "UserDict"}
REMOVED = {"imp", "distutils", "asynchat", "asyncore", "smtpd", "cgi", "cgitb", "nntplib", "telnetlib",
           "audioop", "chunk", "imghdr", "mailcap", "pipes", "sndhdr", "sunau", "uu", "xdrlib", "aifc",
           "lib2to3"}
TEST_MARKERS = (".tests", ".test.", ".testing", "conftest", "test_", "_pytest", "pytest")
REASONS = {
    "internal": "provided by PyInstaller or Python itself at run time",
    "platform": "only exists on another operating system or Python implementation",
    "python2": "Python 2 name; libraries import it only as a fallback",
    "attribute": "not a module of its (existing) parent package; a function or class imported with "
                 "'from x import y'",
    "tests": "only imported by test modules",
    "optional": "optional import (inside try/except, an if-block or a function); only matters if you use "
                "that feature",
    "excluded": "excluded on purpose (--exclude-module, a hook or the spec file)",
    "parent": "part of a package that is reported missing itself",
    "runtime": "standard-library module that Python creates at run time, not a file PyInstaller can see "
               "(e.g. collections.abc on Python 3.14)",
}


@dataclass
class WarnEntry:
    """One ``missing module named X - imported by ...`` line."""

    status: str  # "missing" or "excluded"
    module: str
    importers: list[tuple[str, tuple[str, ...]]]  # (importer, ("top-level", "optional", ...))


def parse_warnfile(text: str) -> list[WarnEntry]:
    """Parse the text of a PyInstaller warn file into entries (header lines are skipped)."""
    entries = []
    for line in text.splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        rest = match.group(4)
        importers = [(m.group(1), tuple(m.group(2).split(", "))) for m in IMPORTER_RE.finditer(rest)]
        if not importers and rest:  # very old format without import types
            importers = [(name.strip(), ()) for name in rest.split(", ")]
        entries.append(WarnEntry(match.group(1), match.group(2) or match.group(3), importers))
    return entries


def _created_at_run_time(name: str) -> bool:
    """True for stdlib aliases that only exist in ``sys.modules`` (``collections.abc`` on 3.14)."""
    module = sys.modules.get(name)
    alias = "." in name and module is not None and getattr(module, "__name__", name) != name
    return alias or name in RUNTIME_ALIASES


def _stdlib_has(name: str) -> bool:
    """True when the standard library has a module file (or package folder) for dotted ``name``."""
    base = Path(sysconfig.get_paths()["stdlib"]).joinpath(*name.split("."))
    return base.with_name(base.name + ".py").is_file() or base.is_dir()


def _short(importer: str) -> str:
    return display(importer) if "/" in importer or "\\" in importer else importer


def _is_user_code(importer: str, roots: Sequence[Path]) -> bool:
    """Your entry script is listed by path; your own modules exist in the project folder."""
    if "/" in importer or "\\" in importer:
        low = importer.replace("\\", "/").lower()
        return not any(part in low for part in ("/site-packages/", "/dist-packages/", "/pyinstaller/"))
    return find_local(importer.split(".")[0], roots) is not None


def classify(entry: WarnEntry, env: Environment, missing: set[str], roots: Sequence[Path] = ()) -> Finding | str:
    """A :class:`Finding` for likely-real problems, or the ``REASONS`` key for safe-to-ignore ones.

    ``roots`` are your project folders, used to recognise your own modules among the importers.
    """
    name, top = entry.module, entry.module.split(".")[0]
    parent, _, last = name.rpartition(".")
    importers = ", ".join(f"{_short(imp)} ({', '.join(kinds)})" for imp, kinds in entry.importers[:4])
    user = [_short(imp) for imp, kinds in entry.importers if _is_user_code(imp, roots)]
    user_top = [_short(imp) for imp, kinds in entry.importers
                if "top-level" in kinds and _is_user_code(imp, roots)]
    top_level = [_short(imp) for imp, kinds in entry.importers if "top-level" in kinds]
    if top.startswith("pyimod") or top in INTERNAL:
        return "internal"
    if entry.status == "excluded":
        return "excluded"
    if top in PLATFORM_ONLY or name in PLATFORM_ONLY:
        return "platform"
    if top in PYTHON2:
        return "python2"
    if top != name and top in missing:
        return "parent"
    if top in env.stdlib and _created_at_run_time(name):
        return "runtime"
    if env.module_exists(name):
        level = Severity.HIGH if top_level or user else Severity.MEDIUM
        return Finding(level, "installed-but-missing", name, f"{name}: installed, but PyInstaller did not find it",
                       f"{name} is installed in the inspected environment, yet PyInstaller could not import it "
                       "while building. Usually PyInstaller ran from a different Python or venv than the one "
                       "your packages are in (run 'python -m PyInstaller' from that venv), or the module is "
                       "imported in a way PyInstaller cannot see.", [importers], [Fix("hidden-import", name)])
    if parent and parent not in missing and (last[:1].isupper() or env.module_exists(parent)
                                             or (top in env.stdlib and not _stdlib_has(name))):
        return "attribute"  # from multiprocessing import get_context -> "multiprocessing.get_context"
    if entry.importers and all(any(m in imp for m in TEST_MARKERS) for imp, _ in entry.importers):
        return "tests"
    if top in REMOVED:
        install = (f"{top} was removed from the standard library in Python 3.12/3.13 (PEP 594/632), so the "
                   "code needs an update or a backport package")
    elif top in env.stdlib:
        install = (f"{top} is part of the standard library but missing from the Python that ran PyInstaller "
                   "(some installers leave out tkinter, for example)")
    else:
        install = f"install it in the environment you build from (pip install {PIP_NAMES.get(top, top)})"
    if user_top:
        return Finding(Severity.HIGH, "missing-module", name, f"{name}: your code imports it, but it was not found",
                       f"{', '.join(user_top[:2])} imports {name} at the top level, so the exe stops with "
                       f"ModuleNotFoundError: No module named '{name}'. Fix: {install}; if it is your own "
                       "module, add its folder with --paths.", [importers])
    if top_level:
        return Finding(Severity.MEDIUM, "missing-module", name, f"{name}: imported at top level by a library",
                       f"{top_level[0]} imports {name} unconditionally, so importing {top_level[0]} in the exe "
                       f"fails with ModuleNotFoundError. If your app uses it: {install}. If not, ignore this.",
                       [importers])
    if user:
        optional = all("optional" in kinds for imp, kinds in entry.importers if _is_user_code(imp, roots))
        return Finding(Severity.LOW if optional else Severity.MEDIUM, "missing-module", name,
                       f"{name}: imported by your code inside a function, if or try block",
                       f"The code path that imports {name} raises ModuleNotFoundError in the exe. If that path "
                       f"matters: {install}.", [importers])
    return "optional"


def check_warnfile(path: PathLike, *, venv: PathLike | None = None,
                   site_packages: Sequence[PathLike] | None = None) -> Report:
    """Classify every entry of a PyInstaller warn file; returns a :class:`Report`."""
    warn = Path(path)
    if not warn.is_file():
        raise DoctorError(f"{path}: file not found (PyInstaller writes it to build/<name>/warn-<name>.txt)")
    entries = parse_warnfile(warn.read_text(encoding="utf-8", errors="replace"))
    env = Environment.from_options(venv=venv, site_packages=site_packages)
    report = Report("warnfile", display(warn), environment=[str(p) for p in env.paths])
    if not entries:
        report.notes.append("no 'missing module named ...' lines found in this file")
    missing = {e.module for e in entries if e.status == "missing"}
    parents = warn.resolve().parents  # PyInstaller writes <project>/build/<name>/warn-<name>.txt
    roots = [parents[2] if len(parents) > 2 and parents[1].name == "build" else warn.resolve().parent]
    for entry in entries:
        result = classify(entry, env, missing, roots)
        if isinstance(result, Finding):
            report.findings.append(result)
        else:
            report.ignored.append({"module": entry.module, "reason": REASONS[result],
                                   "imported_by": [f"{i} ({', '.join(k)})" for i, k in entry.importers]})
    report.checked.append(f"{len(entries)} entries: {len(report.findings)} to look at, "
                          f"{len(report.ignored)} safe to ignore")
    report.sort()
    return report
