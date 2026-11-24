---
title: pyinstaller-doctor
description: Find out why your PyInstaller exe fails (FileNotFoundError, ModuleNotFoundError, missing DLLs or metadata) and get the exact --collect-data, --hidden-import or --copy-metadata fix, before or after the build.
---

# pyinstaller-doctor

**Find out why your PyInstaller exe fails, and get the exact fix.**

Your PyInstaller build "completes successfully", but the exe crashes:

- `FileNotFoundError` because a package's data files were not bundled
- `ModuleNotFoundError` because of a hidden import
- `[WinError 3]` or `Could not find module` because a folder or DLL is missing

pyinstaller-doctor tells you which package causes it, and gives you the flag that fixes it.

```bash
pip install git+https://github.com/Shahnawaz75/pyinstaller-doctor

pyinstaller-doctor scan app.py                       # before you build
pyinstaller-doctor dist dist/app                     # after the build: what is missing?
pyinstaller-doctor warnfile build/app/warn-app.txt   # which "missing module" lines matter?
```

What it checks:

- data files (json, txt, png, ttf, qss, onnx, ...) and native libraries that packages ship,
- dynamic imports, entry-point plugins, and packages that read their own metadata,
- relative paths and missing `freeze_support()` in your own code,
- whether a PyInstaller or pyinstaller-hooks-contrib hook already covers a package.

You get a prioritized HIGH / MEDIUM / LOW report, a ready-to-paste `pyinstaller` command, and the same fix as
`.spec` file code. It is stdlib-only, works without PyInstaller installed, has `--json` output and CI-friendly
exit codes, and also works with auto-py-to-exe (same flags).

## Read more

- [Example output from real builds](example-output.md): a build that crashes, the suggested flag, the working exe
- [Common PyInstaller errors and fixes](common-errors.md): FileNotFoundError, ModuleNotFoundError,
  "Failed to execute script", WinError 3/126, PackageNotFoundError, RecursionError, multiprocessing
- [README: install, options, CI, Python API, limitations, FAQ](https://github.com/Shahnawaz75/pyinstaller-doctor#readme)
- [Source code on GitHub](https://github.com/Shahnawaz75/pyinstaller-doctor) (MIT license)
