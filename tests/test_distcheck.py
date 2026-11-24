"""The post-build check against fake bundle trees."""

import pytest
from conftest import LOADER

from pyinstaller_doctor import DoctorError, Fix, Severity, check_dist


@pytest.fixture
def bundle(tmp_path):
    """A PyInstaller 6 onedir layout: dist/app/app.exe + dist/app/_internal/."""

    def make(files=(), internal=True):
        root = tmp_path / "dist" / "app"
        inner = root / "_internal" if internal else root
        inner.mkdir(parents=True, exist_ok=True)
        (root / "app.exe").write_text("", encoding="utf-8")
        (inner / "base_library.zip").write_text("", encoding="utf-8")
        for rel in files:
            (inner / rel).parent.mkdir(parents=True, exist_ok=True)
            (inner / rel).write_text("", encoding="utf-8")
        return root

    return make


@pytest.fixture
def words(make_dist, write):
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": "a",
                             "fancywords/themes/blue.json": "{}"})
    return write("proj/app.py", "import fancywords\n")


def test_missing_data_files_are_listed_with_the_flag(site, words, bundle):
    report = check_dist(bundle(["fancywords/themes/blue.json"]), script=words, site_packages=[site])
    [found] = report.findings
    assert found.severity is Severity.HIGH and found.evidence == ["fancywords/words.txt"]
    assert found.fixes == [Fix("collect-data", "fancywords")]
    assert report.exit_code() == 1


def test_complete_bundle_passes(site, words, bundle):
    report = check_dist(bundle(["fancywords/words.txt", "fancywords/themes/blue.json"]), script=words,
                        site_packages=[site])
    assert report.findings == [] and report.exit_code() == 0
    assert report.checked == ["fancywords 1.0 (2/2 files present)"]


def test_pyinstaller5_layout_and_package_list_from_pyz_toc(site, words, bundle, tmp_path):
    root = bundle(internal=False)
    toc = tmp_path / "build" / "app" / "PYZ-00.toc"
    toc.parent.mkdir(parents=True)
    toc.write_text(repr(("PYZ-00.pyz", [("fancywords", "C:\\x\\fancywords\\__init__.py", "PYMODULE"),
                                        ("json", "C:\\py\\json\\__init__.py", "PYMODULE")])), encoding="utf-8")
    report = check_dist(root, site_packages=[site])
    assert [f.code for f in report.findings] == ["missing-data"]
    assert any("PYZ-00.toc" in note for note in report.notes)


def test_native_files_found_elsewhere_count_as_present(make_dist, site, write, bundle):
    make_dist("engine", {"engine/__init__.py": "import ctypes\nLIB = ctypes.CDLL(path)\n",
                         "engine/bin/engine.dll": ""})
    app = write("proj/app.py", "import engine\n")
    [found] = check_dist(bundle(["other.dll"]), script=app, site_packages=[site]).findings
    assert found.code == "missing-binaries" and found.severity is Severity.HIGH
    assert check_dist(bundle(["engine.dll"]), script=app, site_packages=[site]).findings == []


def test_missing_metadata_is_reported(make_dist, site, write, bundle):
    make_dist("nice-version", {"nicever/__init__.py": "from importlib.metadata import version\n"
                                                      "__version__ = version(__name__)\n"})
    app = write("proj/app.py", "import nicever\n")
    [found] = check_dist(bundle(), script=app, site_packages=[site]).findings
    assert found.code == "missing-metadata" and found.fixes == [Fix("copy-metadata", "nice-version")]
    assert check_dist(bundle(["nice_version-1.0.dist-info/METADATA"]), script=app,
                      site_packages=[site]).findings == []


def test_onefile_build_is_rejected_with_advice(tmp_path, site):
    exe = tmp_path / "dist" / "app.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    for target in (exe, tmp_path / "dist" / "app"):
        with pytest.raises(DoctorError, match="onefile"):
            check_dist(target, site_packages=[site])
