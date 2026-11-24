---
title: Common PyInstaller errors and fixes
description: The PyInstaller runtime and build errors people search for most (FileNotFoundError, ModuleNotFoundError, Failed to execute script, WinError 3, WinError 126, PackageNotFoundError, RecursionError, multiprocessing), with the cause and the exact fix.
---

# Common PyInstaller errors and fixes

Each section starts with the error text as you see it, then explains the cause, how
[pyinstaller-doctor](https://github.com/Shahnawaz75/pyinstaller-doctor) detects it, and the fix. Paths are
shown for Windows and PyInstaller 6 (where the bundled files live in `dist\<name>\_internal`); macOS/Linux
paths look the same with `/`.

- [FileNotFoundError: No such file or directory ... \_internal ... .json](#filenotfounderror-errno-2-no-such-file-or-directory-_internaljson)
- [FileNotFoundError: No such file or directory: 'config.json'](#filenotfounderror-errno-2-no-such-file-or-directory-configjson)
- [ModuleNotFoundError: No module named ...](#modulenotfounderror-no-module-named-)
- [Failed to execute script ... due to unhandled exception](#failed-to-execute-script--due-to-unhandled-exception)
- [[WinError 3] The system cannot find the path specified](#filenotfounderror-winerror-3-the-system-cannot-find-the-path-specified)
- [Could not find module ... dll / DLL load failed](#filenotfounderror-could-not-find-module-dll-or-one-of-its-dependencies)
- [importlib.metadata.PackageNotFoundError](#importlibmetadatapackagenotfounderror-no-package-metadata-was-found-for-)
- [No module named 'pkg_resources.py2_warn'](#modulenotfounderror-no-module-named-pkg_resourcespy2_warn)
- [RecursionError when building](#recursionerror-maximum-recursion-depth-exceeded-when-building)
- [Multiprocessing app opens many windows](#multiprocessing-app-opens-many-windows-or-keeps-starting-new-processes)

## FileNotFoundError: [Errno 2] No such file or directory: '..._internal...json'

A real example from [example-output.md](example-output.md):

```text
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\work\\demo_app\\dist\\demo_broken\\_internal\\better_profanity\\alphabetic_unicode.json'
[PYI-21764:ERROR] Failed to execute script 'app' due to unhandled exception!
```

**Cause.** A package opens a data file that sits next to its code (JSON, a word list, themes, icons,
fonts, a model). PyInstaller bundles the Python modules it finds through imports, but not these files,
unless a hook or a flag tells it to. The part after `_internal\` names the package. Well-known cases
include customtkinter's `assets\themes\blue.json` and the files in plotly's `package_data` folder. Both are
covered by pyinstaller-hooks-contrib hooks today, so the fix there is often just upgrading
pyinstaller-hooks-contrib. `scan` tells you which packages a hook covers in your environment.

**How pyinstaller-doctor detects it.** `scan` lists the non-Python files every imported package ships
and looks for code that opens files from the package folder (`os.path.dirname(__file__)`,
`Path(__file__).parent`, `importlib.resources`, `pkg_resources.resource_filename`). It also checks whether
a PyInstaller hook already collects them. After a build, `dist` lists the files that are missing from
`_internal`.

**Fix.**

```bash
pyinstaller app.py --collect-data better_profanity
```

```python
# .spec file
from PyInstaller.utils.hooks import collect_data_files
datas = collect_data_files("better_profanity")
```

## FileNotFoundError: [Errno 2] No such file or directory: 'config.json'

**Cause.** Your own code opens a file with a relative path, such as `open("config.json")`. Python resolves
it against the *current folder*, not the folder of the exe. That works while you start the app from your
project folder, and fails when the exe is double-clicked, started from a shortcut, or run on another PC.
The file may also not be bundled at all.

**How pyinstaller-doctor detects it.** `scan` flags string literals with a relative path passed to `open()`,
`Path()`, `Image.open()`, `PhotoImage(file=...)`, `iconbitmap()`, `pandas.read_csv()` and similar calls in
your code, and prints the `--add-data` flag for files it finds next to your script.

**Fix.** Bundle the file and load it through `sys._MEIPASS`:

```bash
pyinstaller app.py --add-data "config.json;."      # Windows; use : on macOS/Linux (PyInstaller 6 accepts : everywhere)
```

```python
import os
import sys


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled file; works in development and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


with open(resource_path("config.json"), encoding="utf-8") as f:
    ...
```

Files your app *writes* (settings, logs, databases) belong in a user folder such as `%APPDATA%`, not
next to the exe, and not in `sys._MEIPASS`, which is a temporary folder in onefile builds.

## ModuleNotFoundError: No module named '...'

**Cause.** One of four things:

1. **Hidden import.** The module is imported by name at run time (`importlib.import_module(name)`,
   `__import__(name)`, plugin loaders, `pkgutil.iter_modules`). PyInstaller only follows `import`
   statements, so it never saw it.
2. **Not installed where PyInstaller runs.** PyInstaller bundles what the Python that runs it can import.
   If you installed the package in a venv but ran a global `pyinstaller`, it is missing.
3. **Your own module is not on the search path**, for example it lives in a `src` folder.
4. **Entry-point plugins.** The plugin modules are found through package metadata and never imported
   statically.

**How pyinstaller-doctor detects it.**
- `scan` flags dynamic imports in your code and in libraries, entry-point plugin lookups, and imports that
  no installed distribution provides.
- `warnfile` sorts PyInstaller's `missing module named ...` list into real problems and harmless entries.
  It also tells you when a "missing" module is actually installed, which means PyInstaller ran from another
  environment.

**Fix.**
- Hidden imports: `--hidden-import package.module`. For an installed package: `--collect-submodules package`.
- For a package of *your own* next to the script, list each module with `--hidden-import`; pyinstaller-doctor
  prints the list. With PyInstaller 6.22.3, `--collect-submodules` silently collected nothing for such a
  package: `collect_submodules()` runs before the script folder is on PyInstaller's search path (see
  [example-output.md](example-output.md#the-fixed-version)).
- Wrong environment: activate the venv and run `python -m PyInstaller app.py` from it.
- Your own modules in another folder: `--paths src`.
- Plugins: `--copy-metadata <plugin-dist> --hidden-import <plugin.module>` for each plugin.

## Failed to execute script '...' due to unhandled exception

```text
[PYI-28516:ERROR] Failed to execute script 'app' due to unhandled exception!
```

Older PyInstaller versions print `Failed to execute script app`. A `--windowed`/`--noconsole` build shows the
error in a message box instead.

**Cause.** This is not the real error. The PyInstaller bootloader prints it after your program raised an
exception it did not handle. The real exception is the traceback printed *above* this line (console builds)
or in the dialog (windowed builds).

**How pyinstaller-doctor detects it.** Indirectly: the underlying errors on this page are what `scan`,
`dist` and `warnfile` look for.

**Fix.** Build once without `--windowed`/`--noconsole` and start the exe from a terminal (`cmd`,
PowerShell) so the traceback stays visible. Then look up the real error, usually one of the others on this
page.

## FileNotFoundError: [WinError 3] The system cannot find the path specified

```text
FileNotFoundError: [WinError 3] The system cannot find the path specified: 'C:\\...\\_internal\\somepackage\\themes'
```

**Cause.** A package lists one of its own folders, for example
`os.listdir(os.path.join(os.path.dirname(__file__), "themes"))` or `glob()` / `Path(__file__).parent.iterdir()`.
The folder was not bundled, so it does not exist inside `_internal`. The same happens when a package
looks for a folder of plugins or native libraries next to itself.

**How pyinstaller-doctor detects it.** `scan` follows names computed from `__file__` (such as
`HERE = os.path.dirname(__file__)`) into `os.listdir`, `os.scandir`, `os.walk`, `glob`, `iterdir` and
`rglob` calls, and reports the package's data files. `dist` shows which of them are missing.

**Fix.** `--collect-data <package>`. If the folder holds native libraries, use `--collect-binaries <package>`.
If it holds both and the package also imports submodules dynamically, use `--collect-all <package>`.

## FileNotFoundError: Could not find module '...dll' (or one of its dependencies)

```text
FileNotFoundError: Could not find module 'C:\...\_internal\somepackage\engine.dll' (or one of its dependencies). Try using the full path with constructor syntax.
```

Related messages: `OSError: [WinError 126] The specified module could not be found` and
`ImportError: DLL load failed while importing _something: The specified module could not be found.`

**Cause.** A native library (`.dll`, `.so`, `.dylib`, or a `.pyd` extension module) is not in the bundle,
or one of the DLLs it depends on is missing. PyInstaller finds libraries that extension modules link
against, but not ones a package opens at run time with `ctypes.CDLL()`, `cdll.LoadLibrary()`,
`os.add_dll_directory()` or `importlib.util.spec_from_file_location()`. mssql-python is one example: it
loads its `ddbc_bindings` extension module by path.

**How pyinstaller-doctor detects it.** `scan` lists native files inside each package and in folders
outside the package (such as `<package>.libs`), and flags the loader calls above. `dist` reports native
files that are missing from the bundle.

**Fix.** `--collect-binaries <package>`. For libraries outside the package folder, use
`--add-binary "<site-packages>\<folder>;<folder>"` (pyinstaller-doctor prints the exact path). For your own
DLL, use `--add-binary "engine.dll;."` and load it through `resource_path("engine.dll")`.

## importlib.metadata.PackageNotFoundError: No package metadata was found for ...

```text
importlib.metadata.PackageNotFoundError: No package metadata was found for somepackage
```

With `pkg_resources`, the message is
`pkg_resources.DistributionNotFound: The 'somepackage' distribution was not found and is required by the application`.

**Cause.** The package reads its own (or another package's) metadata, often its version via
`importlib.metadata.version(__name__)`. That metadata lives in the `.dist-info` folder, which a frozen
app does not have unless you copy it. PyInstaller copies it automatically for calls with a *literal* name
such as `version("requests")`, but not for computed names like `__name__` or `__package__`.

**How pyinstaller-doctor detects it.** `scan` finds `importlib.metadata` / `importlib_metadata` calls
(`version`, `metadata`, `distribution`, `files`, `requires`) and `pkg_resources.get_distribution` /
`require`. It reports HIGH when the call runs at import time and is not inside `try/except`. `dist`
reports `.dist-info` folders that are missing from the bundle.

**Fix.** `--copy-metadata <distribution name>` (the pip name, e.g. `--copy-metadata nice-version`). In a
`.spec` file: `datas += copy_metadata("nice-version")`. If it also needs the metadata of its
requirements, use `--recursive-copy-metadata <name>`.

## ModuleNotFoundError: No module named 'pkg_resources.py2_warn'

**Cause.** An old-toolchain problem from 2020. Some setuptools releases of that time made `pkg_resources`
import a `pkg_resources.py2_warn` module by name, and the PyInstaller hooks of that time did not know about
it. Current setuptools and PyInstaller versions do not have this problem.

**How pyinstaller-doctor detects it.** When `pkg_resources` is part of your app, `scan` reports its
literal `__import__("pkg_resources.py2_warn")` as a hidden import.

**Fix.** Upgrade PyInstaller and setuptools. If you are stuck on the old versions, add
`--hidden-import pkg_resources.py2_warn`.

## RecursionError: maximum recursion depth exceeded (when building)

**Cause.** PyInstaller analyses imports recursively. Very deep import chains (big scientific stacks are
the usual case) can hit Python's default recursion limit while building. This is a build-time error, not
a run-time one.

**How pyinstaller-doctor detects it.** It does not; nothing is wrong with your app or your flags.

**Fix.** This is the workaround PyInstaller itself prints. Add this line near the top of your `.spec` file,
then build from the spec file:

```python
import sys ; sys.setrecursionlimit(sys.getrecursionlimit() * 5)
```

```bash
pyinstaller myapp.spec
```

Upgrading PyInstaller also helps.

## Multiprocessing app opens many windows (or keeps starting new processes)

**Cause.** In a frozen app, every worker process starts *the exe itself* again. Without
`multiprocessing.freeze_support()`, each worker runs your whole program instead of the worker code, so it
opens another window or starts more workers. This affects Windows and macOS (spawn), and Linux with the
spawn or forkserver start methods; forkserver is the Linux default since Python 3.14. PyInstaller's
runtime hook provides a working `freeze_support()`, but only if your code calls it.

**How pyinstaller-doctor detects it.** `scan` reports HIGH when your code imports `multiprocessing` (or
uses `ProcessPoolExecutor`) and the entry script never calls `freeze_support()`.

**Fix.** Make it the first line under the main guard of your entry script:

```python
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

This was verified with a real PyInstaller 6.22.3 build that uses `multiprocessing.Pool`
([example-output.md](example-output.md#the-fixed-version)).
