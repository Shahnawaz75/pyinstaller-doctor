# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-24

First release.

### Added

- `pyinstaller-doctor scan app.py`: a static pre-build check.
  - Follows your import graph, maps imports to installed distributions (and their dependencies), and
    inspects their files.
  - Flags data files, native libraries (inside and outside the package folder), entry-point plugins,
    dynamic imports, native loading by path, and metadata lookups.
  - Your own code: relative paths, `resource_path()` files, dynamic imports, missing `freeze_support()`,
    and imports that are not installed.
  - Hook coverage from PyInstaller, pyinstaller-hooks-contrib, `pyinstaller40` entry points and
    `--hooks-dir`.
  - Prints a ready-to-paste `pyinstaller` command, a `.spec` snippet and a `resource_path()` helper.
- `pyinstaller-doctor warnfile`: classifies PyInstaller's `warn-<name>.txt` entries into likely real
  problems and safe-to-ignore entries (with reasons).
- `pyinstaller-doctor dist`: post-build check of onedir bundles (PyInstaller 6 `_internal` and 5.x
  layouts). It takes the package list from `build/<name>/PYZ-00.toc` or `--script`.
- `--json` output, `--fail-on` and CI-friendly exit codes (0 = fine, 1 = findings, 2 = bad input).
- Python API: `scan()`, `check_dist()`, `check_warnfile()`, `parse_warnfile()`.
- Docs: common PyInstaller errors and fixes, real example output, GitHub Pages landing page.

[0.1.0]: https://github.com/Shahnawaz75/pyinstaller-doctor/releases/tag/v0.1.0
