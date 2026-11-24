"""Shared data model: severities, fixes, findings and the report object."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class DoctorError(Exception):
    """Bad input (missing file, wrong folder, ...). The CLI prints it and exits with code 2."""


class Severity(IntEnum):
    """How likely a finding is to break the frozen app."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3

    def lowered(self) -> Severity:
        """One level less severe (LOW stays LOW)."""
        return Severity(max(int(self) - 1, 1))


#: Order in which options appear in the suggested command.
OPTION_ORDER = ("collect-all", "collect-data", "collect-binaries", "collect-submodules",
                "hidden-import", "copy-metadata", "add-data", "add-binary")

#: ``PyInstaller.utils.hooks`` helper used for each option in a ``.spec`` file.
SPEC_HELPERS = {"collect-data": "collect_data_files", "collect-binaries": "collect_dynamic_libs",
                "collect-submodules": "collect_submodules", "copy-metadata": "copy_metadata",
                "collect-all": "collect_all"}

RESOURCE_HELPER = '''\
import os
import sys


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled file; works in development and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)
'''


@dataclass(frozen=True)
class Fix:
    """One PyInstaller command-line option, e.g. ``Fix("collect-data", "customtkinter")``."""

    option: str
    value: str

    def cli(self) -> str:
        """The option as typed on the command line (``--collect-data customtkinter``)."""
        if self.option in ("add-data", "add-binary") or " " in self.value:
            return f'--{self.option} "{self.value}"'
        return f"--{self.option} {self.value}"

    def spec_line(self) -> str:
        """The same option as a line of Python for a ``.spec`` file."""
        if self.option in ("add-data", "add-binary"):
            src, _, dest = self.value.rpartition(os.pathsep)
            target = "datas" if self.option == "add-data" else "binaries"
            return f"{target} += [({src!r}, {dest!r})]"
        value = repr(self.value)
        return {
            "collect-data": f"datas += collect_data_files({value})",
            "collect-binaries": f"binaries += collect_dynamic_libs({value})",
            "collect-submodules": f"hiddenimports += collect_submodules({value})",
            "hidden-import": f"hiddenimports += [{value}]",
            "copy-metadata": f"datas += copy_metadata({value})",
            "collect-all": (f"tmp = collect_all({value}); "
                            "datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]"),
        }[self.option]


@dataclass
class Finding:
    """One (potential) problem with a plain-English explanation and the fix."""

    severity: Severity
    code: str
    package: str
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    covered_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return {"severity": self.severity.name, "code": self.code, "package": self.package,
                "title": self.title, "detail": self.detail, "evidence": self.evidence,
                "flags": [fix.cli() for fix in self.fixes], "covered_by": self.covered_by}


@dataclass
class Report:
    """Result of one check: ``scan``, ``warnfile`` or ``dist``."""

    kind: str
    target: str
    environment: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ignored: list[dict[str, Any]] = field(default_factory=list)
    script: str | None = None
    needs_resource_helper: bool = False

    def counts(self) -> dict[str, int]:
        """Number of findings per severity, e.g. ``{"HIGH": 1, "MEDIUM": 0, "LOW": 2}``."""
        counts = {severity.name: 0 for severity in sorted(Severity, reverse=True)}
        for finding in self.findings:
            counts[finding.severity.name] += 1
        return counts

    @property
    def has_high(self) -> bool:
        """True when at least one HIGH finding exists."""
        return any(f.severity is Severity.HIGH for f in self.findings)

    def exit_code(self, fail_on: str = "high") -> int:
        """1 when a finding at or above ``fail_on`` exists, else 0 (``never`` always gives 0)."""
        if fail_on == "never":
            return 0
        threshold = Severity[fail_on.upper()]
        return int(any(f.severity >= threshold for f in self.findings))

    def sort(self) -> None:
        """Most severe first, then by package name."""
        self.findings.sort(key=lambda f: (-f.severity, f.package.lower(), f.code))

    def suggested_fixes(self) -> list[Fix]:
        """Unique fixes of MEDIUM/HIGH findings; data + binaries + submodules become --collect-all."""
        fixes = {fix for f in self.findings
                 if f.severity >= Severity.MEDIUM and not f.covered_by for fix in f.fixes}
        trio = ("collect-data", "collect-binaries", "collect-submodules")
        for value in {fix.value for fix in fixes}:
            if all(Fix(option, value) in fixes for option in trio):
                fixes -= {Fix(option, value) for option in trio}
                fixes.add(Fix("collect-all", value))
        return sorted(fixes, key=lambda fx: (OPTION_ORDER.index(fx.option), fx.value.lower()))

    def pyinstaller_command(self) -> str:
        """Ready-to-paste ``pyinstaller`` command with every suggested option ("" if none)."""
        fixes = self.suggested_fixes()
        if not fixes:
            return ""
        script = self.script or "your_script.py"
        if " " in script:
            script = f'"{script}"'
        return " ".join(["pyinstaller", script, *(fix.cli() for fix in fixes)])

    def spec_snippet(self) -> str:
        """The same options as ``.spec`` file code ("" if none)."""
        fixes = self.suggested_fixes()
        if not fixes:
            return ""
        helpers = sorted({SPEC_HELPERS[fx.option] for fx in fixes if fx.option in SPEC_HELPERS})
        lines = [f"from PyInstaller.utils.hooks import {', '.join(helpers)}", ""] if helpers else []
        lines.append("datas, binaries, hiddenimports = [], [], []")
        lines += [fix.spec_line() for fix in fixes]
        script = os.path.basename(self.script) if self.script else "your_script.py"
        lines += ["", "# then pass them on (merge with any lists you already have):",
                  f"# a = Analysis([{script!r}], datas=datas, binaries=binaries, "
                  "hiddenimports=hiddenimports, ...)"]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation (what ``--json`` prints)."""
        from . import __version__

        return {
            "tool": "pyinstaller-doctor", "version": __version__, "command": self.kind,
            "target": self.target, "environment": self.environment, "summary": self.counts(),
            "findings": [f.to_dict() for f in self.findings], "checked": self.checked,
            "notes": self.notes, "ignored": self.ignored,
            "fix": {"flags": [fix.cli() for fix in self.suggested_fixes()],
                    "command": self.pyinstaller_command(), "spec": self.spec_snippet(),
                    "resource_path_helper": RESOURCE_HELPER if self.needs_resource_helper else None},
        }
