# pyinstaller-doctor: find out why your PyInstaller exe fails, and get the exact fix

[![CI](https://github.com/Shahnawaz75/pyinstaller-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahnawaz75/pyinstaller-doctor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

pyinstaller-doctor checks a Python app before and after a PyInstaller build. It tells you which missing data
files (the usual `FileNotFoundError`), hidden imports (`ModuleNotFoundError`), DLLs and package metadata will
break your exe, and gives you the exact `--collect-data`, `--hidden-import` or `--copy-metadata` flag for each one.

This is real output from [`examples/demo_app`](examples/demo_app/app.py), which uses customtkinter and
better-profanity:

```text
> pyinstaller-doctor scan app.py --venv .venv
pyinstaller-doctor scan: app.py
Environment: .venv\Lib\site-packages
Checked: better-profanity 0.7.0, customtkinter 6.0.0, darkdetect 0.8.0 (via customtkinter),
  packaging 26.4 (via customtkinter)

HIGH    better_profanity: 2 data file(s) that PyInstaller does not bundle by default
        better-profanity 0.7.0 ships non-Python files (alphabetic_unicode.json,
        profanity_wordlist.txt); its code opens files from its own folder
        (better_profanity/utils.py:8  os.path.abspath(os.path.dirname(__file__))). PyInstaller
        bundles imported Python code, not data files, unless told to, so the exe fails with
        FileNotFoundError (or [WinError 3] for a missing folder).
        - better_profanity/utils.py:8  os.path.abspath(os.path.dirname(__file__))
        Fix: --collect-data better_profanity

LOW     customtkinter: 8 data file(s) that PyInstaller does not bundle by default - covered by a hook
        hook-customtkinter.py from pyinstaller-hooks-contrib already bundles the data files, so
        there is nothing to do.

Summary: 1 high, 0 medium, 1 low

Suggested fix (keep your other options such as --onefile, --windowed, --icon):
  pyinstaller app.py --collect-data better_profanity
```

Built without that flag, the exe crashed with
`FileNotFoundError: ... _internal\better_profanity\alphabetic_unicode.json`. Built with it, the exe ran.
The full session (build logs, `dist` and `warnfile` output, JSON) is in
[docs/example-output.md](docs/example-output.md).

## Why pyinstaller-doctor?

PyInstaller follows your `import` statements. It cannot know that a package opens `themes/blue.json` next
to its own code, loads a DLL with `ctypes`, imports plugins by name, or reads its own version from
`.dist-info` metadata. Hooks from PyInstaller and
[pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib) cover many popular
packages, but not all of them, and never your own code. So the build "completes successfully" and the exe
crashes at start-up, often only on someone else's PC. Then the trial and error with `--add-data`,
`--collect-data`, `--collect-all` and `--hidden-import` begins.

pyinstaller-doctor reads what PyInstaller reads (your imports, the installed files of every package, the
hooks, the warn file and the finished bundle) and turns it into a short, prioritized list with the exact
flag for each problem.

| Problem it finds | Typical error in the exe | Fix it suggests |
|---|---|---|
| Package data files (json, txt, csv, png, ico, ttf, html, js, css, qss, ui, sql, onnx, ...) | `FileNotFoundError`, `[WinError 3]` | `--collect-data PKG` |
| Native code loaded by path (`ctypes.CDLL`, `os.add_dll_directory`, `.pyd` via `spec_from_file_location`) | `OSError: [WinError 126]`, `Could not find module` | `--collect-binaries PKG`, `--add-binary` |
| Modules imported by name (`importlib.import_module`, `__import__`, `pkgutil`) | `ModuleNotFoundError` | `--hidden-import`, `--collect-submodules` |
| Packages that read their own metadata (`version(__name__)`) | `importlib.metadata.PackageNotFoundError` | `--copy-metadata DIST` |
| Entry-point plugins (`entry_points(group=...)`) | plugins silently missing | `--copy-metadata` + `--hidden-import` |
| Your code: relative paths (`open("config.json")`) | `FileNotFoundError` when started from another folder | `resource_path()` + `--add-data` |
| Your code: multiprocessing without `freeze_support()` | new windows/processes keep appearing | add `freeze_support()` |
| Imports that are not installed in the build environment | `ModuleNotFoundError` | install into the venv you build from |

## Install

```bash
pip install git+https://github.com/Shahnawaz75/pyinstaller-doctor
```

It needs Python 3.9 or newer and has no dependencies. It never imports PyInstaller or your packages; it
only reads files. Install it into the environment you build from, or anywhere else and point it at that
environment with `--venv`. PyPI release: coming soon.

To install PyInstaller in the same step, use the optional extra:
`pip install "pyinstaller-doctor[pyinstaller] @ git+https://github.com/Shahnawaz75/pyinstaller-doctor"`.

## Quick start

```bash
pyinstaller-doctor scan app.py                       # before you build
pyinstaller app.py --collect-data better_profanity   # build with the suggested flags
pyinstaller-doctor dist dist/app                     # after the build: what is still missing?
pyinstaller-doctor warnfile build/app/warn-app.txt   # which "missing module" lines matter?
```

By default it inspects the active virtual environment, or the Python that runs it. Use `--venv .venv` (or
`--site-packages DIR`) to check the environment you actually build from. Every command accepts `--json`,
and the exit code is 1 when HIGH findings exist.

## Check before you build (scan)

`pyinstaller-doctor scan app.py` does a static pre-build check:

1. It follows the import graph of your entry script and your own modules and packages (relative imports
   included), and collects every third-party import.
2. It maps each import to its installed distribution, plus that distribution's dependencies. Then it
   inspects the installed files: data files, native libraries inside and outside the package folder, and
   entry-point plugin groups.
3. It runs code-pattern checks on the packages' sources and on your own code:
   - `os.path.dirname(__file__)` / `Path(__file__).parent`, and `os.listdir()`/`glob()` on the package
     folder
   - `pkg_resources.resource_filename()` and `importlib.resources.files()`
   - `import_module()` / `__import__()` with computed names, and `pkgutil.iter_modules()`
   - `ctypes.CDLL()`, `cdll.LoadLibrary()`, `os.add_dll_directory()`, `spec_from_file_location()`
   - `importlib.metadata.version()` and friends
   - `entry_points(group=...)`
   - `multiprocessing` without `freeze_support()`
   - relative file paths in your code
4. It checks whether a PyInstaller hook already covers the package: PyInstaller's own hooks,
   pyinstaller-hooks-contrib, hooks that packages ship via the `pyinstaller40` entry point, and your
   `--hooks-dir`. It also reads the hook to see *what* it collects. A covering hook turns the finding into
   LOW.

Severities: **HIGH** means the exe will very likely crash. **MEDIUM** means a likely problem; adding the flag
is cheap. **LOW** means for your information, or already covered by a hook. You get one ready-to-paste
`pyinstaller` command and the same fix as `.spec` file code (`collect_data_files`, `collect_dynamic_libs`,
`collect_submodules`, `copy_metadata`, `collect_all`). If your own code uses relative paths, you also get
this small `resource_path()` helper:

```python
import os
import sys


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled file; works in development and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)
```

Options: `--venv PATH`, `--site-packages DIR` (repeatable), `--paths DIR` (extra folders with your
modules, like `pyinstaller --paths`), `--hooks-dir DIR` (like `--additional-hooks-dir`), `--no-deps`,
`--json`, `--fail-on {high,medium,low,never}`, `--no-color`.

## Explain the warn file

After each build, PyInstaller writes `build/<name>/warn-<name>.txt`, often with dozens of
`missing module named ...` lines, and most of them are harmless.
`pyinstaller-doctor warnfile build/app/warn-app.txt` sorts them:

- **Likely real problems:** your own code imports the module at top level; the module is installed but
  PyInstaller did not find it (usually PyInstaller ran from another Python or venv); a library imports it
  unconditionally; or a module was removed from the standard library (PEP 594).
- **Safe to ignore, with the reason:** modules of other platforms (`posix`, `pwd`, `_winreg`, `java`,
  `org.python`, ...), Python 2 fallbacks, optional imports inside `try`/`if`/functions, functions imported
  with `from x import y`, test-only imports, and PyInstaller internals.

Real output for the [`common_mistakes`](examples/common_mistakes/app.py) example, where 1 of 19 entries
matters:

```text
HIGH    humanize: your code imports it, but it was not found
        app.py imports humanize at the top level, so the exe stops with ModuleNotFoundError: No
        module named 'humanize'. Fix: install it in the environment you build from (pip install
        humanize); if it is your own module, add its folder with --paths.
        - app.py (top-level)

Safe to ignore (18):
  - provided by PyInstaller or Python itself at run time: _frozen_importlib,
    _frozen_importlib_external, pyimod02_importers
  - only exists on another operating system or Python implementation: _posixshmem, _posixsubprocess,
    _scproxy, fcntl, grp, posix, pwd, resource
  ...
```

## Check a finished build (dist)

`pyinstaller-doctor dist dist/myapp` checks a **onedir** build. For each package in the app, it compares
the data files and native libraries in site-packages with what landed in the bundle:
`dist/myapp/_internal` on PyInstaller 6+, or `dist/myapp` itself on 5.x. It lists what is missing, together
with the flag that would include it. It also notices a missing `.dist-info` folder for packages that read
their own metadata.

The package list comes from PyInstaller's own `build/<name>/PYZ-00.toc` when the build folder sits next to
`dist/`, or from `--script app.py` (`--build DIR` points at another work folder).

**Onefile builds** are a single exe, so there is no folder to compare. Build once with `--onedir` (the
default) to inspect, or list what is inside the exe with PyInstaller's `pyi-archive_viewer`.

## Common PyInstaller errors and fixes

[docs/common-errors.md](docs/common-errors.md) is a searchable page of the most common runtime and build
errors, each with its cause, how pyinstaller-doctor detects it, and the fix:

- `FileNotFoundError: [Errno 2] No such file or directory: '...\_internal\...json'`
- `ModuleNotFoundError: No module named '...'`
- `Failed to execute script '...' due to unhandled exception`
- `[WinError 3] The system cannot find the path specified`
- `OSError: [WinError 126]` / `Could not find module '...dll' (or one of its dependencies)`
- `importlib.metadata.PackageNotFoundError: No package metadata was found for ...`
- `ModuleNotFoundError: No module named 'pkg_resources.py2_warn'` (old setuptools)
- `RecursionError: maximum recursion depth exceeded` while building
- A multiprocessing app that keeps opening new windows

## Use in CI

Exit codes: `0` means fine, `1` means findings at or above `--fail-on` (default `high`), `2` means bad
input. With `--json` you get a machine-readable report.

```yaml
# .github/workflows/build.yml (excerpt)
- run: pip install pyinstaller git+https://github.com/Shahnawaz75/pyinstaller-doctor
- run: pyinstaller-doctor scan app.py                      # fails the job on HIGH findings
- run: pyinstaller --noconfirm app.py --collect-data better_profanity
- run: pyinstaller-doctor dist dist/app --fail-on medium   # nothing may be missing from the bundle
```

## Python API

```python
from pyinstaller_doctor import check_dist, check_warnfile, scan

report = scan("app.py", venv=".venv")
for finding in report.findings:
    print(finding.severity.name, finding.title, [fix.cli() for fix in finding.fixes])

print(report.pyinstaller_command())  # "pyinstaller app.py --collect-data better_profanity"
print(report.spec_snippet())         # the same as .spec file code
data = report.to_dict()              # what --json prints
```

`check_dist("dist/app", script="app.py")` and `check_warnfile("build/app/warn-app.txt")` return the same
`Report` type.

## How it works

- **Static only.** Python's `ast` and a little regex. Your code and your packages are never imported or
  executed.
- **Imports to distributions.** The `RECORD` files of installed distributions map import names to packages
  (like `importlib.metadata.packages_distributions()`, but for any site-packages folder). The same files
  list each package's data files and native libraries.
- **Hooks.** It looks for `hook-<module>.py` in PyInstaller's hooks, in pyinstaller-hooks-contrib, in
  packages that register a `pyinstaller40` entry point, and in your `--hooks-dir`. It reads each hook to
  see whether it collects data files, binaries, submodules or metadata.
- **Severity.** Data files plus code that opens files from the package folder give HIGH; a covering hook
  turns that into LOW. Native libraries loaded by path give HIGH. A package reading its own metadata at
  import time gives HIGH. Dynamic imports and plugins give MEDIUM.
- **dist** compares files on disk; **warnfile** parses PyInstaller's
  `missing module named X - imported by Y (top-level), Z (optional)` lines.

## Limitations

- Static analysis cannot see everything. Names built at run time, files found through environment
  variables or config files, and libraries loaded by native code itself can be missed. Code paths that
  never run can be over-reported, such as a data file only used on another platform.
- It does not know the options you already pass (an existing `.spec` file, `--add-data`), so some MEDIUM
  findings may already be handled. It does not run PyInstaller or your app.
- Hook coverage is found by reading the hook's source; a hook that only collects files under some
  conditions still counts as covering.
- Onefile builds cannot be inspected directly (see above). Editable installs and packages without `RECORD`
  files are inspected less precisely. At most 3,000 source files per package are pattern-checked.
- Verified end to end on Windows 11 with Python 3.14 and PyInstaller 6.22.3; the unit tests also ran on
  Python 3.12. CI runs the tests on Linux, macOS and Windows.

## FAQ

### Why does my PyInstaller exe say FileNotFoundError?

A package or your own code opens a file that PyInstaller did not copy into the bundle. PyInstaller bundles
the Python modules it finds through imports, but not the JSON, images, fonts or models next to them,
unless a hook or a flag says so. The path in the error shows which package it is (`...\_internal\<package>\...`).
`pyinstaller-doctor scan app.py` names the package and the flag, usually `--collect-data <package>`. For
your own files, use `--add-data` and a `resource_path()` helper.

### How do I include data files in PyInstaller?

For an installed package: `--collect-data <package>` (in a `.spec` file:
`datas += collect_data_files('<package>')`). For your own files and folders, use `--add-data SRC;DEST`
(Windows) or `--add-data SRC:DEST` (macOS/Linux; PyInstaller 6 accepts `:` everywhere), for example
`--add-data "assets;assets"`. Then load them through `sys._MEIPASS` with the `resource_path()` helper above.

### What is the difference between --collect-data and --collect-all?

`--collect-data X` adds only the data files of package `X`. `--collect-binaries X` adds its native libraries,
`--collect-submodules X` imports all of its submodules, and `--copy-metadata X` adds its `.dist-info`
folder. `--collect-all X` does all four at once: data files, binaries, every submodule and the metadata.
That is convenient, but it makes the bundle bigger. pyinstaller-doctor suggests the narrow flags, and
`--collect-all` only when data, binaries and submodules are all needed.

### Why does my exe work on my PC but not on another PC?

Usually because something the exe needs comes from your PC, not from the bundle:
- a relative path that works because you start the exe from your project folder,
- an absolute path into your source tree,
- a DLL that another program put on your `PATH`.

On a clean machine those are missing. Run `pyinstaller-doctor dist dist/<name>` to list files that are not
in the bundle. Load your own files with `resource_path()`. Then test the `dist` folder from a different
location, ideally on a clean PC or VM.

### Does it work with auto-py-to-exe?

Yes. auto-py-to-exe runs PyInstaller with the options you choose in its UI, so the flags are the same.
You can add them in the *Advanced* section (it has fields for `--collect-data`, `--hidden-import`,
`--copy-metadata`, ...). Or paste the suggested flags into *Settings → Manual Argument Input*. To check
the result, choose *One Directory* and run `pyinstaller-doctor dist <output folder>\<name> --script app.py`.
Pass `--script` because auto-py-to-exe usually builds in a temporary work folder, so `PYZ-00.toc` is gone.

### Does it run or import my code?

No. It only reads files: your sources, the installed packages' files and metadata, the hooks, the warn file
and the bundle.

## Contributing

Bug reports with a package name and version (false alarms and missed problems alike) are the most useful
contribution. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Shahnawaz75.

If pyinstaller-doctor saved you a round of trial and error, a star helps other people find it.
