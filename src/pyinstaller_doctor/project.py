"""Follow the import graph of your own code, starting at the entry script."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .analysis import FREEZE_SUPPORT, ImportRef, ModuleAnalysis, analyze_source


@dataclass
class Project:
    """Your entry script plus every local module it (transitively) imports."""

    entry: Path
    roots: list[Path]
    analyses: dict[Path, ModuleAnalysis] = field(default_factory=dict)
    third_party: dict[str, list[tuple[Path, ImportRef]]] = field(default_factory=dict)

    @property
    def uses_multiprocessing(self) -> bool:
        """True when any of your modules imports multiprocessing or ProcessPoolExecutor."""
        return any(a.uses_multiprocessing for a in self.analyses.values())

    @property
    def entry_calls_freeze_support(self) -> bool:
        """True when the entry script calls ``multiprocessing.freeze_support()``."""
        return any(hit.kind == FREEZE_SUPPORT for hit in self.analyses[self.entry].hits)


def find_local(name: str, roots: Sequence[Path]) -> tuple[Path | None, bool] | None:
    """``(file, is_package)`` for a module in your project; file is None for a namespace folder."""
    parts = name.split(".")
    for root in roots:
        base = root.joinpath(*parts)
        if (base / "__init__.py").is_file():
            return base / "__init__.py", True
        module = base.with_name(parts[-1] + ".py")
        if module.is_file():
            return module, False
        if base.is_dir() and any(base.glob("*.py")):
            return None, True
    return None


def local_submodules(package: str, roots: Sequence[Path]) -> list[str] | None:
    """Every module inside your own package ``package``; None when it is not a local package."""
    for root in roots:
        folder = root.joinpath(*package.split("."))
        if folder.is_dir():
            names = []
            for source in sorted(folder.rglob("*.py")):
                parts = source.relative_to(root).with_suffix("").parts
                if "__pycache__" not in parts:
                    name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
                    if name != package:
                        names.append(name)
            return names
    return None


def walk_project(entry: str | Path, extra_paths: Sequence[str | Path] = (),
                 stdlib: frozenset[str] = frozenset()) -> Project:
    """Parse ``entry`` and follow its local imports; collect third-party top-level imports."""
    entry = Path(entry).resolve()
    roots = [entry.parent, *(Path(p).resolve() for p in extra_paths)]
    project = Project(entry, roots)
    queue: list[tuple[Path, str, bool]] = [(entry, entry.stem, False)]
    while queue:
        path, name, is_package = queue.pop(0)
        if path in project.analyses:
            continue
        try:
            source = path.read_bytes()
        except OSError as exc:
            project.analyses[path] = ModuleAnalysis(error=str(exc))
            continue
        analysis = analyze_source(source, str(path), name, is_package, user_code=True)
        project.analyses[path] = analysis
        for ref in analysis.imports:
            top = ref.name.split(".")[0]
            local = find_local(top, roots)
            if local is None or (local[0] is None and top in stdlib):  # a bare folder never shadows stdlib
                if top not in stdlib:
                    project.third_party.setdefault(top, []).append((path, ref))
                continue
            parts = ref.name.split(".")
            names = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
            for candidate in names + [f"{ref.name}.{n}" for n in ref.from_names]:
                found = find_local(candidate, roots)
                if found and found[0] is not None:
                    queue.append((found[0].resolve(), candidate, found[1]))
    return project
