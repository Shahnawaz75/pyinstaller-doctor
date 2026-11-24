---
title: Example output (real runs)
description: Real pyinstaller-doctor output from real PyInstaller 6.22.3 builds on Windows 11 with Python 3.14 - a broken build, the suggested fix, and the working exe.
---

# Example output: real runs, real builds

Everything below was produced by real commands on **Windows 11, Python 3.14.10, PyInstaller 6.22.3,
pyinstaller-hooks-contrib 2026.10** with pyinstaller-doctor 0.1.0. Nothing is invented or edited, except
that the long temporary work folder was shortened to `C:\work` for readability. Exit codes are shown
as `[exit code N]`. For the PyInstaller builds only the last log line is shown.

Each app has its own virtual environment in `.venv` (PyInstaller plus the app's packages);
pyinstaller-doctor was installed in a separate environment and pointed at `.venv` with `--venv`.

Contents:

1. [Data files: a build that crashes, and the flag that fixes it](#1-data-files-a-build-that-crashes-and-the-flag-that-fixes-it)
2. [Mistakes in your own code](#2-mistakes-in-your-own-code)
3. [JSON output](#3-json-output)

## 1. Data files: a build that crashes, and the flag that fixes it

[`examples/demo_app/app.py`](../examples/demo_app/app.py) uses two packages that ship data files:

* **customtkinter 6.0.0**: theme JSON and font files. pyinstaller-hooks-contrib has a hook for it.
* **better-profanity 0.7.0**: a word list and a JSON file, opened via `os.path.dirname(__file__)`.
  There is no hook for it.

```text
> pyinstaller-doctor --version
pyinstaller-doctor 0.1.0
[exit code 0]

> .venv\Scripts\pyinstaller --version
6.22.3
[exit code 0]
```

### Before the build: `scan`

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

The same in a .spec file:
  from PyInstaller.utils.hooks import collect_data_files

  datas, binaries, hiddenimports = [], [], []
  datas += collect_data_files('better_profanity')

  # then pass them on (merge with any lists you already have):
  # a = Analysis(['app.py'], datas=datas, binaries=binaries, hiddenimports=hiddenimports, ...)
[exit code 1]
```

customtkinter is reported as covered by its hook; better_profanity is a real HIGH.

### Build without the flag: the exe crashes

```text
> .venv\Scripts\pyinstaller --noconfirm --name demo_broken app.py
Build complete! The results are available in: C:\work\demo_app\dist
[exit code 0]
```

```text
> dist\demo_broken\demo_broken.exe
Traceback (most recent call last):
  File "app.py", line 15, in <module>
    from better_profanity import profanity
  File "<frozen importlib._bootstrap>", line 1371, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1342, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 938, in _load_unlocked
  File "pyimod02_importers.py", line 457, in exec_module
  File "better_profanity\__init__.py", line 3, in <module>
  File "<frozen importlib._bootstrap>", line 1371, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1342, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 938, in _load_unlocked
  File "pyimod02_importers.py", line 457, in exec_module
  File "better_profanity\better_profanity.py", line 5, in <module>
  File "<frozen importlib._bootstrap>", line 1371, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1342, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 938, in _load_unlocked
  File "pyimod02_importers.py", line 457, in exec_module
  File "better_profanity\constants.py", line 14, in <module>
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\work\\demo_app\\dist\\demo_broken\\_internal\\better_profanity\\alphabetic_unicode.json'
[PYI-21764:ERROR] Failed to execute script 'app' due to unhandled exception!
[exit code 1]
```

### After the build: `dist` names the missing files

The package list is read from PyInstaller's own `build\demo_broken\PYZ-00.toc`.

```text
> pyinstaller-doctor dist dist\demo_broken --venv .venv
pyinstaller-doctor dist: dist\demo_broken
Environment: .venv\Lib\site-packages
Checked: better-profanity 0.7.0 (0/2 files present), customtkinter 6.0.0 (8/8 files present),
  darkdetect 0.8.0 (0/0 files present), packaging 26.4 (0/0 files present)
Note: package list taken from build\demo_broken\PYZ-00.toc

HIGH    better_profanity: 2 of 2 data files are missing from the bundle
        These files are installed with better-profanity 0.7.0 but were not copied into the build.
        Its code opens files from its own folder (better_profanity/utils.py:8
        os.path.abspath(os.path.dirname(__file__))), so the exe will raise FileNotFoundError.
        - better_profanity/alphabetic_unicode.json
        - better_profanity/profanity_wordlist.txt
        Fix: --collect-data better_profanity

Summary: 1 high, 0 medium, 0 low

Suggested fix (keep your other options such as --onefile, --windowed, --icon):
  pyinstaller your_script.py --collect-data better_profanity

The same in a .spec file:
  from PyInstaller.utils.hooks import collect_data_files

  datas, binaries, hiddenimports = [], [], []
  datas += collect_data_files('better_profanity')

  # then pass them on (merge with any lists you already have):
  # a = Analysis(['your_script.py'], datas=datas, binaries=binaries, hiddenimports=hiddenimports, ...)
[exit code 1]
```

### The warn file: nothing to worry about here

PyInstaller listed 17 missing modules. All of them are harmless, and pyinstaller-doctor says why
(note `collections.abc`: on Python 3.14 it is created at run time and has no file of its own):

```text
> pyinstaller-doctor warnfile build\demo_broken\warn-demo_broken.txt --venv .venv
pyinstaller-doctor warnfile: build\demo_broken\warn-demo_broken.txt
Environment: .venv\Lib\site-packages
Checked: 17 entries: 0 to look at, 17 safe to ignore

Safe to ignore (17):
  - standard-library module that Python creates at run time, not a file PyInstaller can see (e.g.
    collections.abc on Python 3.14): collections.abc
  - only exists on another operating system or Python implementation: _posixsubprocess, _scproxy,
    fcntl, grp, java, java.lang, posix, pwd, resource, vms_lib
  - provided by PyInstaller or Python itself at run time: _frozen_importlib,
    _frozen_importlib_external
  - optional import (inside try/except, an if-block or a function); only matters if you use that
    feature: Foundation, PIL, PyObjCTools, typing_extensions

Summary: 0 high, 0 medium, 0 low
Nothing to fix: every missing module is safe to ignore.
[exit code 0]
```

### Build with the suggested flag: the exe works

The flags were taken from `scan --json` (`fix.flags`) and passed to PyInstaller unchanged.

```text
> .venv\Scripts\pyinstaller --noconfirm --name demo_fixed app.py --collect-data better_profanity
Build complete! The results are available in: C:\work\demo_app\dist
[exit code 0]
```

```text
> dist\demo_fixed\demo_fixed.exe
customtkinter theme loaded, button color: ['#3B8ED0', '#1F6AA5']
better_profanity says: this build is ****
[exit code 0]
```

```text
> pyinstaller-doctor dist dist\demo_fixed --venv .venv
pyinstaller-doctor dist: dist\demo_fixed
Environment: .venv\Lib\site-packages
Checked: better-profanity 0.7.0 (2/2 files present), customtkinter 6.0.0 (8/8 files present),
  darkdetect 0.8.0 (0/0 files present), packaging 26.4 (0/0 files present)
Note: package list taken from build\demo_fixed\PYZ-00.toc

Summary: 0 high, 0 medium, 0 low
No problems found.
[exit code 0]
```

## 2. Mistakes in your own code

[`examples/common_mistakes/app.py`](../examples/common_mistakes/app.py) has four classic problems: a package
that is not installed in the build environment, `open("settings.json")` with a relative path, a module
imported by name at run time, and multiprocessing without `freeze_support()`.

```text
> pyinstaller-doctor scan app.py --venv .venv
pyinstaller-doctor scan: app.py
Environment: .venv\Lib\site-packages

HIGH    multiprocessing is used but the entry script never calls freeze_support()
        In a frozen app every worker process starts the exe again. Without
        multiprocessing.freeze_support() as the first line under if __name__ == '__main__': each
        worker runs your whole program, so windows multiply or the app hangs. Needed on Windows and
        macOS, and on Linux for the spawn/forkserver start methods (the default from Python 3.14).

HIGH    humanize: imported but not installed in this environment
        PyInstaller can only bundle what is installed in the Python it runs from, so the exe fails
        with ModuleNotFoundError: No module named 'humanize'. Install it there (pip install
        humanize) or point --venv at the environment you build from.
        - app.py:15  import humanize

MEDIUM  app.py: imports modules by name at run time
        PyInstaller only follows import statements, so these modules are not bundled unless you list
        them. Modules of your own packages are listed one by one: --collect-submodules finds nothing
        for a package that sits next to your script.
        - app.py:24  importlib.import_module(f'exporters.{name}')
        Fix: --hidden-import exporters.csv_exporter

MEDIUM  app.py: opens files with a path relative to the current folder
        A relative path is resolved against the folder the exe is started from (a shortcut,
        double-click or scheduler may use another one), and bundled files live in sys._MEIPASS. Use
        resource_path() below and bundle the file with --add-data.
        - app.py:19  open('settings.json', encoding='utf-8')
        Fix: --add-data "settings.json;."

Summary: 2 high, 2 medium, 0 low

Suggested fix (keep your other options such as --onefile, --windowed, --icon):
  pyinstaller app.py --hidden-import exporters.csv_exporter --add-data "settings.json;."

The same in a .spec file:
  datas, binaries, hiddenimports = [], [], []
  hiddenimports += ['exporters.csv_exporter']
  datas += [('settings.json', '.')]

  # then pass them on (merge with any lists you already have):
  # a = Analysis(['app.py'], datas=datas, binaries=binaries, hiddenimports=hiddenimports, ...)

Load your own files through this helper, e.g. open(resource_path('config.json')):
  import os
  import sys


  def resource_path(relative_path: str) -> str:
      """Absolute path to a bundled file; works in development and in a PyInstaller build."""
      base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
      return os.path.join(base, relative_path)
[exit code 1]
```

Building it anyway gives an exe that stops at the missing import:

```text
> .venv\Scripts\pyinstaller --noconfirm app.py
Build complete! The results are available in: C:\work\common_mistakes\dist
[exit code 0]
```

```text
> dist\app\app.exe
Traceback (most recent call last):
  File "app.py", line 15, in <module>
    import humanize  # deliberately missing from the build venv
    ^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'humanize'
[PYI-16612:ERROR] Failed to execute script 'app' due to unhandled exception!
[exit code 1]
```

In this real warn file, 1 of 19 entries is a real problem:

```text
> pyinstaller-doctor warnfile build\app\warn-app.txt --venv .venv
pyinstaller-doctor warnfile: build\app\warn-app.txt
Environment: .venv\Lib\site-packages
Checked: 19 entries: 1 to look at, 18 safe to ignore

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
  - standard-library module that Python creates at run time, not a file PyInstaller can see (e.g.
    collections.abc on Python 3.14): collections.abc
  - not a module of its (existing) parent package; a function or class imported with 'from x import
    y': multiprocessing.AuthenticationError, multiprocessing.BufferTooShort,
    multiprocessing.TimeoutError, multiprocessing.get_context, multiprocessing.get_start_method,
    multiprocessing.set_start_method

Summary: 1 high, 0 medium, 0 low
[exit code 1]
```

### The fixed version

[`examples/common_mistakes/app_fixed.py`](../examples/common_mistakes/app_fixed.py) applies the advice in code
(`resource_path()` for `settings.json`, `multiprocessing.freeze_support()` first under `__main__`), and
`humanize` was installed into `.venv` with `pip install humanize`. Scanning again:

```text
> pyinstaller-doctor scan app_fixed.py --venv .venv
pyinstaller-doctor scan: app_fixed.py
Environment: .venv\Lib\site-packages
Checked: humanize 4.17.0

MEDIUM  app_fixed.py: files loaded through resource_path()
        resource_path() looks inside the bundle (sys._MEIPASS), so every file it loads must be added
        with --add-data, or the exe raises FileNotFoundError. Skip this if your build command
        already adds them.
        - app_fixed.py:25  resource_path('settings.json')
        Fix: --add-data "settings.json;."

MEDIUM  app_fixed.py: imports modules by name at run time
        PyInstaller only follows import statements, so these modules are not bundled unless you list
        them. Modules of your own packages are listed one by one: --collect-submodules finds nothing
        for a package that sits next to your script.
        - app_fixed.py:30  importlib.import_module(f'exporters.{name}')
        Fix: --hidden-import exporters.csv_exporter

LOW     humanize: 72 data file(s) that PyInstaller does not bundle by default - covered by a hook
        hook-humanize.py from pyinstaller-hooks-contrib already bundles the data files, so there is
        nothing to do.

Summary: 0 high, 2 medium, 1 low

Suggested fix (keep your other options such as --onefile, --windowed, --icon):
  pyinstaller app_fixed.py --hidden-import exporters.csv_exporter --add-data "settings.json;."

The same in a .spec file:
  datas, binaries, hiddenimports = [], [], []
  hiddenimports += ['exporters.csv_exporter']
  datas += [('settings.json', '.')]

  # then pass them on (merge with any lists you already have):
  # a = Analysis(['app_fixed.py'], datas=datas, binaries=binaries, hiddenimports=hiddenimports, ...)
[exit code 0]
```

humanize ships 72 locale files, but its contrib hook covers them. Building with exactly the suggested flags
gives a working exe, including the multiprocessing pool:

```text
> .venv\Scripts\pyinstaller --noconfirm app_fixed.py --hidden-import exporters.csv_exporter --add-data "settings.json;."
Build complete! The results are available in: C:\work\common_mistakes\dist
[exit code 0]
```

```text
> dist\app_fixed\app_fixed.exe
0,1,4,9,16 1,234,567
[exit code 0]
```

A lesson from this run: the first version of pyinstaller-doctor suggested `--collect-submodules exporters`
for the local `exporters` package. With PyInstaller 6.22.3 that silently collected nothing, because
`collect_submodules()` runs before the script's folder is on PyInstaller's search path, and the exe failed with
`ModuleNotFoundError: No module named 'exporters'`. pyinstaller-doctor now lists the modules of your own
packages one by one with `--hidden-import`, as shown above.

## 3. JSON output

`--json` prints the same report in machine-readable form (here: `scan` of the demo app):

```json
{
  "tool": "pyinstaller-doctor",
  "version": "0.1.0",
  "command": "scan",
  "target": "app.py",
  "environment": [
    ".venv\\Lib\\site-packages"
  ],
  "summary": {
    "HIGH": 1,
    "MEDIUM": 0,
    "LOW": 1
  },
  "findings": [
    {
      "severity": "HIGH",
      "code": "data-files",
      "package": "better_profanity",
      "title": "better_profanity: 2 data file(s) that PyInstaller does not bundle by default",
      "detail": "better-profanity 0.7.0 ships non-Python files (alphabetic_unicode.json, profanity_wordlist.txt); its code opens files from its own folder (better_profanity/utils.py:8  os.path.abspath(os.path.dirname(__file__))). PyInstaller bundles imported Python code, not data files, unless told to, so the exe fails with FileNotFoundError (or [WinError 3] for a missing folder).",
      "evidence": [
        "better_profanity/utils.py:8  os.path.abspath(os.path.dirname(__file__))"
      ],
      "flags": [
        "--collect-data better_profanity"
      ],
      "covered_by": null
    },
    {
      "severity": "LOW",
      "code": "data-files",
      "package": "customtkinter",
      "title": "customtkinter: 8 data file(s) that PyInstaller does not bundle by default - covered by a hook",
      "detail": "hook-customtkinter.py from pyinstaller-hooks-contrib already bundles the data files, so there is nothing to do.",
      "evidence": [],
      "flags": [
        "--collect-data customtkinter"
      ],
      "covered_by": "hook-customtkinter.py from pyinstaller-hooks-contrib"
    }
  ],
  "checked": [
    "better-profanity 0.7.0",
    "customtkinter 6.0.0",
    "darkdetect 0.8.0 (via customtkinter)",
    "packaging 26.4 (via customtkinter)"
  ],
  "notes": [],
  "ignored": [],
  "fix": {
    "flags": [
      "--collect-data better_profanity"
    ],
    "command": "pyinstaller app.py --collect-data better_profanity",
    "spec": "from PyInstaller.utils.hooks import collect_data_files\n\ndatas, binaries, hiddenimports = [], [], []\ndatas += collect_data_files('better_profanity')\n\n# then pass them on (merge with any lists you already have):\n# a = Analysis(['app.py'], datas=datas, binaries=binaries, hiddenimports=hiddenimports, ...)",
    "resource_path_helper": null
  }
}
```
