"""Warn-file parsing and classification, with lines in PyInstaller's real format."""

import pytest

from pyinstaller_doctor import DoctorError, Fix, Severity, check_warnfile, parse_warnfile

HEADER = """
This file lists modules PyInstaller was not able to find. This does not
necessarily mean these modules are required for running your program.

Types of import:
* top-level: imported at the top-level - look at these first
* optional: imported within a try-except-statement

"""
LINES = r"""
missing module named 'collections.abc' - imported by _colorize (top-level), typing (top-level), packaging.version (top-level)
missing module named pwd - imported by posixpath (delayed, conditional, optional), shutil (delayed, optional)
missing module named 'org.python' - imported by copy (optional), xml.sax (delayed, conditional)
missing module named _winreg - imported by platform (delayed, optional)
excluded module named _frozen_importlib - imported by importlib (optional), importlib.abc (optional)
missing module named urllib2 - imported by oldlib.compat (conditional)
missing module named fancywords - imported by C:\Users\Dev\My Project (x86)\app.py (top-level)
missing module named simplejson - imported by requests.compat (conditional, optional)
missing module named 'pandas.DataFrame' - imported by reports (top-level)
missing module named IPython - imported by richlib.jupyter (top-level)
missing module named pytest - imported by numpylike.testing (top-level), numpylike.tests.test_core (top-level)
excluded module named tkinter - imported by guilib (top-level)
missing module named installedpkg - imported by mylib.core (top-level)
missing module named 'installedpkg.sub' - imported by mylib.core (top-level)
missing module named distutils - imported by oldlib.setup_helpers (top-level)
missing module named multiprocessing.get_context - imported by multiprocessing (top-level), multiprocessing.pool (top-level)
"""


@pytest.fixture
def report(tmp_path, make_dist, site):
    make_dist("installedpkg", {"installedpkg/__init__.py": ""})
    make_dist("mylib", {"mylib/__init__.py": "", "mylib/core.py": ""})
    warn = tmp_path / "warn-app.txt"
    warn.write_text(HEADER + LINES, encoding="utf-8")
    return check_warnfile(warn, site_packages=[site])


def test_parse_real_format_with_quotes_paths_and_import_types():
    entries = parse_warnfile(HEADER + LINES)
    assert len(entries) == 16
    assert entries[0].module == "collections.abc"
    assert entries[1].importers == [("posixpath", ("delayed", "conditional", "optional")),
                                    ("shutil", ("delayed", "optional"))]
    assert entries[6].importers == [(r"C:\Users\Dev\My Project (x86)\app.py", ("top-level",))]
    assert entries[4].status == "excluded"
    assert parse_warnfile(HEADER) == []


def test_safe_entries_are_ignored_with_a_reason(report):
    reasons = {item["module"]: item["reason"] for item in report.ignored}
    assert "another operating system" in reasons["pwd"] and "another operating system" in reasons["org.python"]
    assert "another operating system" in reasons["_winreg"]
    assert "Python 2" in reasons["urllib2"]
    assert "run time" in reasons["collections.abc"] and "run time" in reasons["_frozen_importlib"]
    assert "optional" in reasons["simplejson"]
    assert "not a module" in reasons["pandas.DataFrame"]
    assert "not a module" in reasons["multiprocessing.get_context"]
    assert "test modules" in reasons["pytest"]
    assert "excluded" in reasons["tkinter"]
    assert "reported missing itself" in reasons["installedpkg.sub"]


def test_likely_real_problems_are_findings(report):
    by_module = {f.package: f for f in report.findings}
    assert set(by_module) == {"fancywords", "installedpkg", "IPython", "distutils"}
    assert by_module["fancywords"].severity is Severity.HIGH
    assert "pip install fancywords" in by_module["fancywords"].detail
    assert by_module["installedpkg"].severity is Severity.HIGH
    assert by_module["installedpkg"].fixes == [Fix("hidden-import", "installedpkg")]
    assert by_module["IPython"].severity is Severity.MEDIUM
    assert "removed from the standard library" in by_module["distutils"].detail
    assert report.exit_code() == 1


def test_missing_warnfile_is_an_input_error(tmp_path):
    with pytest.raises(DoctorError, match="warn-<name>.txt"):
        check_warnfile(tmp_path / "nope.txt", site_packages=[tmp_path])
