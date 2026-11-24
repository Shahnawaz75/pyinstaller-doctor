"""Plain-text rendering of a Report, colored only on a real terminal."""

from __future__ import annotations

import os
import sys
import textwrap
from typing import TextIO

from .models import RESOURCE_HELPER, Report, Severity

COLORS = {Severity.HIGH: "1;31", Severity.MEDIUM: "1;33", Severity.LOW: "36"}
WIDTH = 100
INDENT = " " * 8
MAX_EVIDENCE = 4


def _enable_windows_ansi() -> bool:
    """Turn on ANSI escape processing in a Windows console (Windows 10+)."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def supports_color(stream: TextIO | None = None) -> bool:
    """Color only when writing to a terminal, and never when ``NO_COLOR`` is set."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or not getattr(stream, "isatty", lambda: False)():
        return False
    return _enable_windows_ansi() if os.name == "nt" else os.environ.get("TERM") != "dumb"


def _wrap(text: str, indent: str = "", subsequent: str | None = None) -> list[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=subsequent or indent,
                         break_long_words=False, break_on_hyphens=False) or [indent]


def render_text(report: Report, color: bool = False) -> str:
    """The human-readable report printed by the CLI."""

    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    out = [paint(f"pyinstaller-doctor {report.kind}: {report.target}", "1")]
    if report.environment:
        more = f" (+{len(report.environment) - 1} more)" if len(report.environment) > 1 else ""
        out.append(f"Environment: {report.environment[0]}{more}")
    if report.checked:
        out += _wrap("Checked: " + ", ".join(report.checked), "", "  ")
    for note in report.notes:
        out += _wrap(f"Note: {note}", "", "  ")
    out.append("")
    for f in report.findings:
        out.append(f"{paint(f.severity.name.ljust(6), COLORS[f.severity])}  {f.title}")
        out += _wrap(f.detail, INDENT)
        out += [INDENT + paint(f"- {line}", "2") for line in f.evidence[:MAX_EVIDENCE]]
        if len(f.evidence) > MAX_EVIDENCE:
            out.append(f"{INDENT}- ... and {len(f.evidence) - MAX_EVIDENCE} more")
        if f.fixes and not f.covered_by:
            out += _wrap("Fix: " + " ".join(fix.cli() for fix in f.fixes), INDENT, INDENT + "     ")
        out.append("")
    if report.ignored:
        out.append(paint(f"Safe to ignore ({len(report.ignored)}):", "1"))
        groups: dict[str, list[str]] = {}
        for item in report.ignored:
            groups.setdefault(item["reason"], []).append(item["module"])
        for reason, modules in groups.items():
            out += _wrap(f"- {reason}: {', '.join(sorted(set(modules)))}", "  ", "    ")
        out.append("")
    counts = report.counts()
    out.append(paint(f"Summary: {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low", "1"))
    if not report.findings:
        out.append("No problems found." if report.kind != "warnfile"
                   else "Nothing to fix: every missing module is safe to ignore.")
    command = report.pyinstaller_command()
    if command:
        out += ["", paint("Suggested fix (keep your other options such as --onefile, --windowed, --icon):", "1"),
                f"  {command}", "", paint("The same in a .spec file:", "1")]
        out += [f"  {line}".rstrip() for line in report.spec_snippet().splitlines()]
    if report.needs_resource_helper:
        out += ["", paint("Load your own files through this helper, e.g. open(resource_path('config.json')):", "1")]
        out += [f"  {line}".rstrip() for line in RESOURCE_HELPER.splitlines()]
    return "\n".join(out)
