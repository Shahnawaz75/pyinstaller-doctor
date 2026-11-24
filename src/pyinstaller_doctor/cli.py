"""Command line interface: ``pyinstaller-doctor scan | warnfile | dist``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .distcheck import check_dist
from .models import DoctorError, Report
from .render import render_text, supports_color
from .scanner import scan
from .warnfile import check_warnfile


def build_parser() -> argparse.ArgumentParser:
    """The argument parser (exposed for documentation and tests)."""
    parser = argparse.ArgumentParser(
        prog="pyinstaller-doctor",
        description="Find out why your PyInstaller exe fails, and get the exact fix.",
        epilog="Exit codes: 0 = fine, 1 = findings at or above --fail-on, 2 = bad input.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print a JSON report instead of text")
    common.add_argument("--no-color", action="store_true", help="never use colors")
    common.add_argument("--fail-on", choices=["high", "medium", "low", "never"], default="high",
                        help="exit with code 1 when findings of this severity or worse exist (default: high)")
    common.add_argument("--venv", metavar="PATH", help="virtual environment you build from (default: the active one)")
    common.add_argument("--site-packages", metavar="DIR", action="append",
                        help="site-packages folder to inspect instead (repeatable)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("scan", parents=[common], help="check a script before you build",
                       description="Pre-build check of a script and every package it imports.")
    p.add_argument("script", help="your entry script, e.g. app.py")
    p.add_argument("--paths", metavar="DIR", action="append", default=[],
                   help="extra folder with your own modules (like pyinstaller --paths)")
    p.add_argument("--hooks-dir", metavar="DIR", action="append", default=[],
                   help="your own hooks folder (like pyinstaller --additional-hooks-dir)")
    p.add_argument("--no-deps", action="store_true", help="do not inspect the dependencies of imported packages")

    w = sub.add_parser("warnfile", parents=[common], help="explain build/<name>/warn-<name>.txt",
                       description="Explain PyInstaller's warn file: what is safe to ignore, what is not.")
    w.add_argument("warnfile", help="path to warn-<name>.txt")

    d = sub.add_parser("dist", parents=[common], help="check a finished onedir build",
                       description="Post-build check: compare dist/<name> with what the packages need.")
    d.add_argument("dist_dir", help="the onedir build folder, e.g. dist/myapp")
    d.add_argument("--script", help="your entry script; checks every package it imports")
    d.add_argument("--build", metavar="DIR", help="PyInstaller work folder (default: build/<name> next to dist/)")
    d.add_argument("--hooks-dir", metavar="DIR", action="append", default=[],
                   help="your own hooks folder (like pyinstaller --additional-hooks-dir)")
    return parser


def run(args: argparse.Namespace) -> Report:
    """Run the selected subcommand and return its report."""
    env = {"venv": args.venv, "site_packages": args.site_packages}
    if args.command == "scan":
        return scan(args.script, hooks_dirs=args.hooks_dir, paths=args.paths,
                    follow_dependencies=not args.no_deps, **env)
    if args.command == "warnfile":
        return check_warnfile(args.warnfile, **env)
    return check_dist(args.dist_dir, script=args.script, build_dir=args.build, hooks_dirs=args.hooks_dir, **env)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``pyinstaller-doctor`` command; returns the exit code."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except DoctorError as exc:
        print(f"pyinstaller-doctor: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_text(report, color=not args.no_color and supports_color(sys.stdout)))
    return report.exit_code(args.fail_on)
