"""``pyinstaller-doctor scan``: check a script and the packages it imports before you build."""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from . import analysis as A
from .environment import (NOT_PLUGIN_GROUPS, DistInfo, Environment, Hook, PathLike, in_tests, is_data,
                          is_native, is_shared_lib)
from .models import DoctorError, Finding, Fix, Report, Severity
from .project import Project, local_submodules, walk_project

MAX_SOURCES_PER_PACKAGE = 3000
#: Import name -> pip name, for the "not installed" advice.
PIP_NAMES = {"cv2": "opencv-python", "PIL": "Pillow", "yaml": "PyYAML", "sklearn": "scikit-learn",
             "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
             "serial": "pyserial", "win32api": "pywin32", "win32con": "pywin32", "win32gui": "pywin32",
             "Crypto": "pycryptodome", "docx": "python-docx", "pptx": "python-pptx", "fitz": "PyMuPDF",
             "jwt": "PyJWT", "magic": "python-magic", "attr": "attrs", "skimage": "scikit-image",
             "wx": "wxPython", "gi": "PyGObject", "OpenGL": "PyOpenGL", "usb": "pyusb"}
NEEDS = {"data": "data files", "binaries": "native libraries", "submodules": "submodules",
         "metadata": "package metadata"}


@dataclass
class Inspection:
    """Files and risky code patterns of one installed distribution."""

    dist: DistInfo
    tops: list[str]
    via: str | None = None
    data: dict[str, list[str]] = field(default_factory=dict)
    native: dict[str, list[str]] = field(default_factory=dict)
    hits: dict[str, list[tuple[str, A.Hit]]] = field(default_factory=dict)
    truncated: bool = False

    def hits_of(self, top: str, *kinds: str) -> list[tuple[str, A.Hit]]:
        """``(file, hit)`` pairs of the given kinds inside package ``top``."""
        return [(rel, hit) for rel, hit in self.hits.get(top, []) if hit.kind in kinds]


def display(path: PathLike) -> str:
    """Path relative to the current folder when that is shorter, else absolute."""
    try:
        rel = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)
    return str(path) if rel.startswith("..") else rel


def where(item: tuple[str, A.Hit]) -> str:
    rel, hit = item
    return f"{rel}:{hit.lineno}  {hit.code}"


def sample(files: Sequence[str], limit: int = 3) -> str:
    names = [f.rsplit("/", 1)[-1] for f in files[:limit]]
    return ", ".join(names) + (f" and {len(files) - limit} more" if len(files) > limit else "")


def apply_hook(finding: Finding, hook: Hook | None, need: str, covered: str | None = None) -> Finding:
    """Lower the severity when a PyInstaller hook already handles (or partly handles) the problem.

    ``covered`` is appended to the explanation when the hook covers it; by default the explanation
    is replaced by a short "nothing to do" sentence.
    """
    if hook is None:
        return finding
    if need in hook.collects:
        finding.severity = Severity.LOW
        finding.covered_by = hook.describe()
        finding.title += " - covered by a hook"
        if covered is None:
            finding.detail = f"{hook.describe()} already bundles the {NEEDS[need]}, so there is nothing to do."
            finding.evidence = []
        else:
            finding.detail += " " + covered.format(hook=hook.describe())
    else:
        finding.severity = finding.severity.lowered()
        finding.detail += (f" A hook exists ({hook.describe()}) but it does not seem to collect "
                           f"{NEEDS[need]}; add the flag only if the exe still fails.")
    return finding


def inspect_distribution(dist: DistInfo, tops: Iterable[str], via: str | None = None) -> Inspection:
    """Classify the files of ``dist`` and run the pattern checks on its Python sources."""
    inspection = Inspection(dist, sorted(set(tops)), via)
    for top in inspection.tops:
        files = [f for f in dist.files_under(top) if not in_tests(f)]
        inspection.data[top] = [f for f in files if is_data(f)]
        inspection.native[top] = [f for f in files if is_native(f)]
        hits = inspection.hits[top] = []
        sources = [f for f in files if f.endswith(".py")]
        if len(sources) > MAX_SOURCES_PER_PACKAGE:
            inspection.truncated, sources = True, sources[:MAX_SOURCES_PER_PACKAGE]
        for rel in sources:
            try:
                raw = (dist.location / rel).read_bytes()
            except OSError:
                continue
            if not A.PREFILTER.search(raw):
                continue
            module, is_package = rel[:-3].replace("/", "."), rel.endswith("__init__.py")
            if is_package:
                module = module[: -len(".__init__")] if "." in module else module
            hits.extend((rel, hit) for hit in A.analyze_source(raw, rel, module, is_package).hits)
    return inspection


def select_distributions(tops: Iterable[str], env: Environment, follow: bool = True
                         ) -> list[tuple[DistInfo, list[str], str | None]]:
    """Distributions providing ``tops`` plus, when ``follow``, everything they depend on."""
    chosen: dict[str, tuple[DistInfo, set[str], str | None]] = {}
    for top in sorted(tops):
        for dist in env.dists_for_top(top):
            chosen.setdefault(dist.key, (dist, set(), None))[1].add(top)
    queue = [item[0] for item in chosen.values()] if follow else []
    while queue:
        parent = queue.pop(0)
        for requirement in parent.requires:
            dep = env.by_key.get(requirement)
            if dep is not None and dep.key not in chosen:
                chosen[dep.key] = (dep, set(dep.top_level), parent.name)
                queue.append(dep)
    return [(dist, sorted(tops_), via) for dist, tops_, via in chosen.values()]


def package_findings(env: Environment, insp: Inspection) -> list[Finding]:
    """Findings for one third-party distribution."""
    out: list[Finding] = []
    dist, via = insp.dist, f" (needed by {insp.via})" if insp.via else ""
    for top in insp.tops:
        hook, data, native = env.hook_for(top), insp.data[top], insp.native[top]
        loaders = insp.hits_of(top, *A.LOADER_KINDS)
        if data:
            how = (f"its code opens files from its own folder ({where(loaders[0])})" if loaders else
                   "no code that obviously opens them was found, but it may load them indirectly")
            out.append(apply_hook(Finding(
                Severity.HIGH if loaders else Severity.MEDIUM, "data-files", top,
                f"{top}: {len(data)} data file(s) that PyInstaller does not bundle by default{via}",
                f"{dist.name} {dist.version} ships non-Python files ({sample(data)}); {how}. PyInstaller "
                "bundles imported Python code, not data files, unless told to, so the exe fails with "
                "FileNotFoundError (or [WinError 3] for a missing folder).",
                [where(x) for x in loaders[:3]], [Fix("collect-data", top)]), hook, "data"))
        loading = insp.hits_of(top, A.NATIVE_LOAD)
        if native and (loading or any(is_shared_lib(f) for f in native)):
            why = (f"its code loads native code by path ({where(loading[0])}), which PyInstaller cannot "
                   "follow" if loading else "PyInstaller usually finds libraries that extension modules "
                   "link against, but not ones opened at run time")
            out.append(apply_hook(Finding(
                Severity.HIGH if loading else Severity.LOW, "native-binaries", top,
                f"{top}: {len(native)} native file(s) in the package folder{via}",
                f"{dist.name} ships compiled files ({sample(native)}); {why}. A missing one shows up as "
                "ImportError, OSError: [WinError 126] or 'FileNotFoundError: Could not find module'.",
                [where(x) for x in loading[:3]], [Fix("collect-binaries", top)]), hook, "binaries"))
        # optional (try/except ImportError) imports and other packages' modules are not this package's problem
        dynamic = [(rel, h) for rel, h in insp.hits_of(top, A.DYNAMIC_IMPORT) if not h.guarded
                   and (h.arg is None or h.arg.split(".")[0] == top)]
        literal = sorted({h.arg for _, h in dynamic if h.arg and env.module_exists(h.arg)})
        prefixes = sorted({h.arg[:-2] for _, h in dynamic if h.arg and h.arg.endswith(".*")
                           and env.module_exists(h.arg[:-2])})
        computed = any(h.arg is None for _, h in dynamic)
        fixes = ([Fix("collect-submodules", top)] if computed or len(literal) > 5 else
                 [Fix("collect-submodules", p) for p in prefixes] + [Fix("hidden-import", m) for m in literal])
        if fixes:
            out.append(apply_hook(Finding(
                Severity.MEDIUM, "dynamic-imports", top, f"{top}: imports modules by name at run time{via}",
                f"{dist.name} uses importlib.import_module(), __import__() or pkgutil, so PyInstaller cannot "
                "see which modules it needs. If the exe raises ModuleNotFoundError for one of them, this "
                "is the reason.", [where(x) for x in dynamic[:3]], fixes), hook, "submodules"))
        out += _metadata_findings(env, insp, top, hook, via)
    loads_native = any(insp.hits_of(top, A.NATIVE_LOAD) for top in insp.tops)
    hook = next((env.hook_for(t) for t in insp.tops if env.hook_for(t)), None)
    for folder, files in sorted(dist.outside_native().items()):
        out.append(apply_hook(Finding(
            Severity.MEDIUM if loads_native else Severity.LOW, "native-outside", folder,
            f"{folder}: {len(files)} native librar{'y' if len(files) == 1 else 'ies'} outside the "
            f"package folder{via}",
            f"{dist.name} keeps native libraries in {folder}/ next to its package ({sample(files)}), so "
            "--collect-binaries does not see them. PyInstaller usually finds them when an extension "
            "module links against them; if they are loaded at run time, add the folder explicitly.",
            [], [Fix("add-binary", f"{dist.location / folder}{os.pathsep}{folder}")]), hook, "binaries"))
    return out


def _metadata_findings(env: Environment, insp: Inspection, top: str, hook: Hook | None,
                       via: str) -> list[Finding]:
    severity: dict[str, Severity] = {}
    evidence: dict[str, list[str]] = defaultdict(list)
    for rel, hit in insp.hits_of(top, A.METADATA):
        if hit.arg is None:  # version(__name__) & co.: its own metadata, invisible to PyInstaller
            target = insp.dist.name
            level = Severity.LOW if hit.guarded else Severity.HIGH if hit.module_level else Severity.MEDIUM
        else:
            other = env.dist(hit.arg)
            if other is None:
                continue
            target, level = other.name, Severity.LOW
        severity[target] = max(severity.get(target, Severity.LOW), level)
        evidence[target].append(where((rel, hit)))
    out = []
    for target, level in sorted(severity.items()):
        note = (" PyInstaller collects metadata automatically for calls with a literal name, so this is "
                "usually handled." if level is Severity.LOW else "")
        out.append(apply_hook(Finding(
            level, "metadata", top, f"{top}: reads the package metadata of {target}{via}",
            f"importlib.metadata / pkg_resources look for the .dist-info folder of {target}, which a "
            "frozen app does not have unless you copy it; the exe then fails with "
            f"importlib.metadata.PackageNotFoundError (or DistributionNotFound).{note}",
            evidence[target][:3], [Fix("copy-metadata", target)]), hook, "metadata"))
    return out


def user_code_findings(project: Project, env: Environment, report: Report) -> None:
    """Findings for your own modules: relative paths, dynamic imports, native loading, freeze_support."""
    for path, analysis in project.analyses.items():
        rel = display(path)
        if analysis.error:
            report.notes.append(f"could not parse {rel}: {analysis.error}")
        hits: dict[str, list[A.Hit]] = defaultdict(list)
        for hit in analysis.hits:
            hits[hit.kind].append(hit)

        def evidence(kind_hits: list[A.Hit]) -> list[str]:
            return [f"{rel}:{h.lineno}  {h.code}" for h in kind_hits[:5]]

        def bundle(option: str, items: list[A.Hit]) -> list[Fix]:
            """--add-data/--add-binary for each referenced file or folder that exists."""
            fixes = []
            for h in items:
                source = path.parent / h.arg if h.arg else None
                if source is not None and source.exists():
                    arg = h.arg.replace("\\", "/").rstrip("/")
                    dest = arg if source.is_dir() else (os.path.dirname(arg) or ".")
                    fixes.append(Fix(option, f"{display(source)}{os.pathsep}{dest}"))
            return fixes

        bundled = bundle("add-data", hits[A.BUNDLED_FILE])
        if bundled:
            report.findings.append(Finding(
                Severity.MEDIUM, "bundle-files", rel, f"{rel}: files loaded through resource_path()",
                "resource_path() looks inside the bundle (sys._MEIPASS), so every file it loads must be "
                "added with --add-data, or the exe raises FileNotFoundError. Skip this if your build "
                "command already adds them.", evidence(hits[A.BUNDLED_FILE]), bundled))
        if hits[A.RELATIVE_OPEN]:
            report.needs_resource_helper = True
            report.findings.append(Finding(
                Severity.MEDIUM, "relative-path", rel, f"{rel}: opens files with a path relative to the "
                "current folder", "A relative path is resolved against the folder the exe is started from "
                "(a shortcut, double-click or scheduler may use another one), and bundled files live in "
                "sys._MEIPASS. Use resource_path() below and bundle the file with --add-data.",
                evidence(hits[A.RELATIVE_OPEN]), bundle("add-data", hits[A.RELATIVE_OPEN])))
        loaders = [h for kind in A.LOADER_KINDS for h in hits[kind]]
        if loaders and not analysis.uses_meipass:
            report.findings.append(Finding(
                Severity.LOW, "own-data-files", rel, f"{rel}: loads files that live next to your code",
                "That works in a PyInstaller build (__file__ points inside the bundle) as long as every "
                "such file is added with --add-data SRC" + os.pathsep + "DEST, keeping the same folder layout.",
                evidence(loaders)))
        dynamic = hits[A.DYNAMIC_IMPORT]
        if dynamic:
            fixes, local = [], False
            for h in dynamic:
                if h.arg and h.arg.endswith(".*"):
                    modules = local_submodules(h.arg[:-2], project.roots)
                    local |= modules is not None
                    fixes += ([Fix("hidden-import", m) for m in modules[:50]] if modules is not None
                              else [Fix("collect-submodules", h.arg[:-2])])
                elif h.arg:
                    fixes.append(Fix("hidden-import", h.arg))
            report.findings.append(Finding(
                Severity.MEDIUM, "dynamic-imports", rel, f"{rel}: imports modules by name at run time",
                "PyInstaller only follows import statements, so these modules are not bundled unless you "
                "list them." + (" Modules of your own packages are listed one by one: --collect-submodules "
                                "finds nothing for a package that sits next to your script." if local else "")
                + (" For names computed at run time, add a --hidden-import for each possible module."
                   if any(h.arg is None for h in dynamic) else ""), evidence(dynamic), fixes))
        if hits[A.NATIVE_LOAD]:
            report.findings.append(Finding(
                Severity.MEDIUM, "native-load", rel, f"{rel}: loads a native library by path",
                "Bundle the library with --add-binary and build its path from resource_path() or "
                "os.path.dirname(__file__); otherwise the exe raises OSError or 'FileNotFoundError: Could "
                "not find module'.", evidence(hits[A.NATIVE_LOAD]), bundle("add-binary", hits[A.NATIVE_LOAD])))
        for hit in hits[A.METADATA]:
            dist = env.dist(hit.arg) if hit.arg else None
            level = Severity.LOW if dist else Severity.MEDIUM
            report.findings.append(Finding(
                level, "metadata", rel, f"{rel}: reads package metadata ({hit.arg or 'computed name'})",
                "The exe has no .dist-info folders unless you copy them, so this raises "
                "importlib.metadata.PackageNotFoundError." + (
                    " PyInstaller handles literal names automatically when the package is installed."
                    if dist else " Make sure the package is installed and add --copy-metadata NAME."),
                evidence([hit]), [Fix("copy-metadata", dist.name)] if dist else []))
    if project.uses_multiprocessing and not project.entry_calls_freeze_support:
        elsewhere = any(h.kind == A.FREEZE_SUPPORT for a in project.analyses.values() for h in a.hits)
        report.findings.append(Finding(
            Severity.LOW if elsewhere else Severity.HIGH, "freeze-support", display(project.entry),
            "multiprocessing is used but the entry script " + (
                "calls freeze_support() only in another module" if elsewhere else "never calls freeze_support()"),
            "In a frozen app every worker process starts the exe again. Without "
            "multiprocessing.freeze_support() as the first line under if __name__ == '__main__': each worker "
            "runs your whole program, so windows multiply or the app hangs. Needed on Windows and macOS, and "
            "on Linux for the spawn/forkserver start methods (the default from Python 3.14)."
            + (" Make sure that call runs before anything else." if elsewhere else "")))


def not_installed_findings(project: Project, env: Environment) -> list[Finding]:
    """Third-party imports that no installed distribution provides."""
    out = []
    for top, refs in sorted(project.third_party.items()):
        if env.dists_for_top(top):
            continue
        optional = all(ref.optional for _, ref in refs)
        out.append(Finding(
            Severity.LOW if optional else Severity.HIGH, "not-installed", top,
            f"{top}: imported but not installed in this environment",
            f"PyInstaller can only bundle what is installed in the Python it runs from, so the exe fails with "
            f"ModuleNotFoundError: No module named '{top}'. Install it there (pip install "
            f"{PIP_NAMES.get(top, top)}) or point --venv at the environment you build from."
            + (" The import is inside try/except, so your app may cope without it." if optional else ""),
            [f"{display(p)}:{r.lineno}  import {r.name}" for p, r in refs[:3]]))
    return out


def plugin_findings(project: Project, inspections: list[Inspection], env: Environment) -> list[Finding]:
    """Entry-point plugins: consumers that look plugins up, and providers that register them."""
    used: dict[str, list[tuple[str, str]]] = defaultdict(list)  # group -> [(consumer, evidence)]
    for path, analysis in project.analyses.items():
        for hit in analysis.hits:
            if hit.kind == A.ENTRY_POINTS and hit.arg:
                used[hit.arg].append((display(path), f"{display(path)}:{hit.lineno}  {hit.code}"))
    for insp in inspections:
        for top in insp.tops:
            for item in insp.hits_of(top, A.ENTRY_POINTS):
                if item[1].arg:
                    used[item[1].arg].append((top, where(item)))
    out = []
    for group, users in sorted(used.items()):
        providers = env.plugin_providers(group)[:10]
        if not providers or group in NOT_PLUGIN_GROUPS:
            continue
        fixes = sorted({Fix("copy-metadata", d.name) for d, _, _ in providers}
                       | {Fix("hidden-import", value.split(":")[0].strip()) for _, _, value in providers},
                       key=lambda fx: (fx.option, fx.value))
        names = ", ".join(sorted({d.name for d, _, _ in providers}))
        consumer = users[0][0]
        out.append(apply_hook(Finding(
            Severity.MEDIUM, "entry-point-plugins", consumer,
            f"{consumer}: loads plugins from entry-point group '{group}'",
            f"Plugins are discovered through the entry_points.txt metadata of the packages that provide "
            f"them ({names}). A frozen app has no metadata unless you copy it, and the plugin modules are "
            "never imported statically, so the plugins silently disappear or fail to load.",
            [ev for _, ev in users[:3]], fixes), env.hook_for(consumer), "metadata"))
    for insp in inspections:
        for group, eps in sorted(insp.dist.entry_points.items()):
            if group in NOT_PLUGIN_GROUPS or group in used:
                continue
            modules = sorted({value.split(":")[0].strip() for _, value in eps})
            out.append(Finding(
                Severity.LOW, "registers-plugins", insp.tops[0] if insp.tops else insp.dist.name,
                f"{insp.dist.name}: registers plugins in entry-point group '{group}'",
                "Only matters if some library in your app discovers these plugins at run time; then add "
                "the flags below.", [f"{name} = {value}" for name, value in eps[:3]],
                [Fix("copy-metadata", insp.dist.name), *(Fix("hidden-import", m) for m in modules[:5])]))
    return out


def scan(script: PathLike, *, venv: PathLike | None = None, site_packages: Sequence[PathLike] | None = None,
         hooks_dirs: Sequence[PathLike] = (), paths: Sequence[PathLike] = (),
         follow_dependencies: bool = True) -> Report:
    """Check ``script`` and every package it imports before you build; returns a :class:`Report`.

    ``venv`` or ``site_packages`` select the environment to inspect (default: the active one),
    ``hooks_dirs`` are your own ``--additional-hooks-dir`` folders and ``paths`` extra folders with
    your own modules (like ``pyinstaller --paths``).
    """
    entry = Path(script)
    if not entry.is_file():
        raise DoctorError(f"{script}: file not found")
    env = Environment.from_options(venv=venv, site_packages=site_packages, hooks_dirs=hooks_dirs)
    project = walk_project(entry, paths, env.stdlib)
    report = Report("scan", display(entry), environment=[str(p) for p in env.paths], script=display(entry))
    if env.dist("pyinstaller") is None:
        report.notes.append("PyInstaller is not installed in this environment, so hooks shipped with it "
                            "were not checked (install it there, or pass --venv).")
    user_code_findings(project, env, report)
    inspections = [inspect_distribution(dist, tops, via)
                   for dist, tops, via in select_distributions(project.third_party, env, follow_dependencies)]
    for insp in inspections:
        report.findings += package_findings(env, insp)
        report.checked.append(f"{insp.dist.name} {insp.dist.version}" + (f" (via {insp.via})" if insp.via else ""))
        if insp.truncated:
            report.notes.append(f"{insp.dist.name}: only the first {MAX_SOURCES_PER_PACKAGE} source files "
                                "were checked for code patterns")
    report.findings += not_installed_findings(project, env)
    report.findings += plugin_findings(project, inspections, env)
    report.sort()
    return report
