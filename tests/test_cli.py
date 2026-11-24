"""CLI exit codes, JSON output and text output."""

import json
import subprocess
import sys

import pytest
from conftest import LOADER

from pyinstaller_doctor import __version__
from pyinstaller_doctor.cli import main


@pytest.fixture
def app(make_dist, site, write):
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": "a"})
    return write("proj/app.py", "import fancywords\n")


def test_scan_json_and_exit_code(app, site, capsys):
    code = main(["scan", str(app), "--site-packages", str(site), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["command"] == "scan" and data["version"] == __version__
    assert data["summary"] == {"HIGH": 1, "MEDIUM": 0, "LOW": 0}
    assert data["findings"][0]["flags"] == ["--collect-data fancywords"]
    assert data["fix"]["command"].endswith("--collect-data fancywords")


def test_fail_on_controls_the_exit_code(app, site, write, capsys):
    assert main(["scan", str(app), "--site-packages", str(site), "--fail-on", "never"]) == 0
    clean = write("proj/clean.py", "import json\nprint(json.dumps({}))\n")
    assert main(["scan", str(clean), "--site-packages", str(site), "--fail-on", "low"]) == 0
    assert "No problems found." in capsys.readouterr().out


def test_text_output_is_plain_when_not_a_terminal(app, site, capsys):
    main(["scan", str(app), "--site-packages", str(site)])
    out = capsys.readouterr().out
    assert "\033[" not in out
    assert "HIGH    fancywords" in out and "Suggested fix" in out and "collect_data_files" in out


def test_warnfile_command(tmp_path, site, capsys):
    warn = tmp_path / "warn-app.txt"
    warn.write_text("missing module named pwd - imported by shutil (delayed, optional)\n"
                    "missing module named fancy - imported by C:\\proj\\app.py (top-level)\n", encoding="utf-8")
    assert main(["warnfile", str(warn), "--site-packages", str(site), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [f["package"] for f in data["findings"]] == ["fancy"]
    assert [i["module"] for i in data["ignored"]] == ["pwd"]


def test_bad_input_exits_with_code_2(tmp_path, capsys):
    assert main(["dist", str(tmp_path / "missing")]) == 2
    assert "folder not found" in capsys.readouterr().err
    assert main(["scan", str(tmp_path / "nope.py"), "--venv", str(tmp_path / "novenv")]) == 2


def test_version_via_python_m():
    out = subprocess.run([sys.executable, "-m", "pyinstaller_doctor", "--version"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"pyinstaller-doctor {__version__}"
