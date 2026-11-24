# Contributing to pyinstaller-doctor

Thanks for helping. The most valuable contributions are reports from real projects:

- a **false alarm**: something was flagged, but the exe works,
- a **missed problem**: the exe failed, but pyinstaller-doctor said nothing.

Please include the package name and version, the PyInstaller and pyinstaller-hooks-contrib versions, your
OS and Python version, the command you ran, and its output (`--json` is ideal).

## Development setup

```bash
git clone https://github.com/Shahnawaz75/pyinstaller-doctor
cd pyinstaller-doctor
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

On Windows with long paths disabled, keep the clone in a short folder (for example `C:\src`). pip and
PyInstaller both create deep paths below `.venv` and `build`.

## Ground rules

- **Standard library only** at run time. PyInstaller stays an optional extra; the checks read files and
  never import PyInstaller, your app or its packages.
- **Tests never depend on what is installed.** Build fake distributions in a temporary site-packages
  folder with the `make_dist` fixture in `tests/conftest.py`, which writes real `.dist-info` folders with
  `RECORD` files. Tests must not use the network.
- **Accuracy over volume.** A new detector must come with a test for what it finds *and* for what it must
  not flag. If a finding cannot say exactly which flag fixes it, it should be LOW or not exist.
- Type hints and docstrings on public functions. Explanations in findings are plain English and name
  the error the user will see.

## Where things live

| File | What it does |
|---|---|
| `src/pyinstaller_doctor/analysis.py` | AST visitor: imports and code patterns of one file |
| `src/pyinstaller_doctor/project.py` | follows the import graph of your own code |
| `src/pyinstaller_doctor/environment.py` | site-packages, distributions, file classification, hooks |
| `src/pyinstaller_doctor/scanner.py` | `scan`: turns inspections into findings with fixes |
| `src/pyinstaller_doctor/warnfile.py` | `warnfile`: parser and classifier |
| `src/pyinstaller_doctor/distcheck.py` | `dist`: bundle comparison |
| `src/pyinstaller_doctor/models.py` | `Finding`, `Fix`, `Report`, command and `.spec` rendering |
| `src/pyinstaller_doctor/render.py`, `cli.py` | text output and the command line |

## Adding a detector

1. Add a kind constant and the call matching in `analysis.py` (`_Visitor.visit_Call`).
2. Turn hits into a `Finding` with `Fix` objects in `scanner.py` (and in `distcheck.py` if it applies
   to finished builds).
3. Add tests in `tests/test_analysis.py` (detector) and `tests/test_scan.py` (finding and fix).
4. If it maps to a common runtime error, add a section to `docs/common-errors.md`.

## Pull requests

Keep them small and focused, run `python -m pytest` before pushing, and add a line to `CHANGELOG.md`
under an "Unreleased" heading.
