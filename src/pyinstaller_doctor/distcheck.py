"""``pyinstaller-doctor dist``: compare a finished onedir build with what its packages need."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Sequence

from . import analysis as A
from .environment import Environment, PathLike, is_shared_lib, normalize
from .models import DoctorError, Finding, Fix, Report, Severity
from .project import walk_project
from .scanner import Inspection, apply_hook, display, inspect_distribution, select_distributions, where

ONEFILE_HELP = ("{path} is a single file, which looks like a onefile build. Build once with --onedir "
                "(the default) to inspect it, or list what is inside the exe with pyi-archive_viewer.")
HOOK_EXCLUDED = ("{hook} collected the other files, so these were probably left out on purpose "
                 "(tests, examples, optional extras).")


def bundle_roots(dist_dir: Path) -> list[Path]:
    """Folders a onedir build keeps its files in: ``_internal`` (PyInstaller 6+) or the root (5.x)."""
    if dist_dir.is_file():
        raise DoctorError(ONEFILE_HELP.format(path=dist_dir))
    if not dist_dir.is_dir():
        exe = dist_dir.with_name(dist_dir.name + ".exe")
        raise DoctorError(ONEFILE_HELP.format(path=exe) if exe.is_file() else f"{dist_dir}: folder not found")
    inner = [dist_dir / "_internal", dist_dir / "Contents" / "Frameworks", dist_dir / "Contents" / "Resources"]
    return [p for p in inner if p.is_dir()] + [dist_dir]


def toc_modules(toc: Path) -> set[str]:
    """Module names listed in a PyInstaller TOC file such as ``build/<name>/PYZ-00.toc``."""
    try:
        data = ast.literal_eval(toc.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, SyntaxError, MemoryError, RecursionError):
        return set()
    names: set[str] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            if len(item) == 3 and all(isinstance(x, str) for x in item) and item[2] in ("PYMODULE", "EXTENSION"):
                names.add(item[0])
            else:
                stack.extend(item)
    return names


def _bundled_packages(root: Path, roots: list[Path], script: PathLike | None, build_dir: PathLike | None,
                      env: Environment, report: Report) -> tuple[set[str], bool]:
    """Top-level names to check, and whether to follow their dependencies."""
    if script:
        if not Path(script).is_file():
            raise DoctorError(f"--script {script}: file not found")
        report.notes.append(f"package list taken from the imports of {display(script)}")
        return set(walk_project(script, (), env.stdlib).third_party), True
    build = Path(build_dir) if build_dir else root.parent.parent / "build" / root.name
    for name in ("PYZ-00.toc", "Analysis-00.toc"):
        modules = toc_modules(build / name) if (build / name).is_file() else set()
        if modules:
            report.notes.append(f"package list taken from {display(build / name)}")
            return {m.split(".")[0] for m in modules}, False
    report.notes.append("no build folder (build/<name>/PYZ-00.toc) and no --script given, so only packages "
                        "that already have files in the bundle were checked; pass --script app.py for a "
                        "complete check.")
    return {p.name.split(".")[0] for r in roots for p in r.iterdir()} & set(env.by_top), False


def _missing(env: Environment, insp: Inspection, present: set[str], names: set[str],
             dist_infos: set[str]) -> list[Finding]:
    out: list[Finding] = []
    dist = insp.dist
    for top in insp.tops:
        hook, data, native = env.hook_for(top), insp.data[top], insp.native[top]
        lost_data = [f for f in data if f not in present]
        lost_native = [f for f in native if f not in present and f.rsplit("/", 1)[-1].lower() not in names]
        if lost_data:
            loaders = insp.hits_of(top, *A.LOADER_KINDS)
            reason = (f" Its code opens files from its own folder ({where(loaders[0])}), so the exe will raise "
                      "FileNotFoundError." if loaders else "")
            out.append(apply_hook(Finding(
                Severity.HIGH if loaders else Severity.MEDIUM, "missing-data", top,
                f"{top}: {len(lost_data)} of {len(data)} data files are missing from the bundle",
                f"These files are installed with {dist.name} {dist.version} but were not copied into the "
                f"build.{reason}", lost_data, [Fix("collect-data", top)]), hook, "data", HOOK_EXCLUDED))
        if lost_native:
            loading = insp.hits_of(top, A.NATIVE_LOAD)
            shared = any(is_shared_lib(f) for f in lost_native)
            level = Severity.HIGH if loading else Severity.MEDIUM if shared else Severity.LOW
            reason = (f" Its code loads native code by path ({where(loading[0])})." if loading else
                      "" if shared else " They are extension modules nothing imported statically; usually "
                      "optional (speedups, test helpers).")
            out.append(apply_hook(Finding(
                level, "missing-binaries", top,
                f"{top}: {len(lost_native)} of {len(native)} native files are missing from the bundle",
                f"These compiled files are installed with {dist.name} but were not copied into the build."
                f"{reason}", lost_native, [Fix("collect-binaries", top)]), hook, "binaries", HOOK_EXCLUDED))
        for rel, hit in insp.hits_of(top, A.METADATA):
            target = dist if hit.arg is None else env.dist(hit.arg)
            if target is None or target.key in dist_infos:
                continue
            dist_infos.add(target.key)  # report each missing .dist-info once
            level = Severity.LOW if hit.guarded else Severity.HIGH if hit.module_level else Severity.MEDIUM
            out.append(apply_hook(Finding(
                level, "missing-metadata", top, f"{top}: metadata of {target.name} is not in the bundle",
                f"{top} reads the package metadata of {target.name} ({where((rel, hit))}) but no "
                f"{normalize(target.name).replace('-', '_')}-*.dist-info folder was bundled, so the exe raises "
                "importlib.metadata.PackageNotFoundError.", [], [Fix("copy-metadata", target.name)]),
                hook, "metadata", HOOK_EXCLUDED))
    for folder, files in sorted(dist.outside_native().items()):
        lost = [f for f in files if f not in present and f.rsplit("/", 1)[-1].lower() not in names]
        if lost:
            out.append(Finding(
                Severity.MEDIUM, "missing-binaries", folder,
                f"{folder}: {len(lost)} native libraries outside the package folder are missing",
                f"{dist.name} keeps these next to its package, where --collect-binaries does not look.",
                lost, [Fix("add-binary", f"{dist.location / folder}{os.pathsep}{folder}")]))
    return out


def check_dist(dist_dir: PathLike, *, script: PathLike | None = None, build_dir: PathLike | None = None,
               venv: PathLike | None = None, site_packages: Sequence[PathLike] | None = None,
               hooks_dirs: Sequence[PathLike] = ()) -> Report:
    """Post-build check of a onedir build folder such as ``dist/myapp``; returns a :class:`Report`.

    The packages to check come from ``script`` (its import graph), else from PyInstaller's
    ``build/<name>/PYZ-00.toc``, else from what is already in the bundle.
    """
    root = Path(dist_dir)
    roots = bundle_roots(root)
    env = Environment.from_options(venv=venv, site_packages=site_packages, hooks_dirs=hooks_dirs)
    report = Report("dist", display(root), environment=[str(p) for p in env.paths],
                    script=display(script) if script else None)
    if not any((r / "base_library.zip").is_file() for r in roots):
        report.notes.append(f"no base_library.zip in {display(root)}: is this a PyInstaller onedir build?")
    tops, follow = _bundled_packages(root, roots, script, build_dir, env, report)
    present: set[str] = set()
    names: set[str] = set()
    dist_infos: set[str] = set()
    for base in roots:
        for path in base.rglob("*"):
            if path.is_dir():
                if path.name.endswith(".dist-info"):
                    dist_infos.add(normalize(path.name[: -len(".dist-info")].rsplit("-", 1)[0]))
            else:
                present.add(path.relative_to(base).as_posix())
                names.add(path.name.lower())
    for dist, dist_tops, via in select_distributions(tops, env, follow):
        insp = inspect_distribution(dist, dist_tops, via)
        report.findings += _missing(env, insp, present, names, dist_infos)
        data = sum(len(v) for v in insp.data.values())
        native = sum(len(v) for v in insp.native.values())
        lost = {f for finding in report.findings if finding.package in insp.tops for f in finding.evidence}
        report.checked.append(f"{dist.name} {dist.version} ({data + native - len(lost)}/{data + native} "
                              "files present)")
    report.sort()
    return report
