"""The pre-build scan against fake site-packages folders."""

import os

from conftest import LOADER

from pyinstaller_doctor import Fix, Severity, scan


def finding(report, code, package=None):
    matches = [f for f in report.findings if f.code == code and package in (None, f.package)]
    assert matches, f"no {code} finding in {[f.code for f in report.findings]}"
    return matches[0]


def test_data_files_loaded_from_package_folder_are_high(make_dist, site, write):
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": "a b"})
    app = write("proj/app.py", "import fancywords\nprint(fancywords.WORDS)\n")
    report = scan(app, site_packages=[site])
    found = finding(report, "data-files")
    assert found.severity is Severity.HIGH
    assert found.fixes == [Fix("collect-data", "fancywords")]
    assert found.evidence[0].startswith("fancywords/__init__.py:2")
    assert report.pyinstaller_command().endswith("app.py --collect-data fancywords")
    assert "datas += collect_data_files('fancywords')" in report.spec_snippet()
    assert report.exit_code() == 1


def test_hook_that_collects_data_marks_finding_covered(make_dist, site, write, hook):
    hook("fancywords", "from PyInstaller.utils.hooks import collect_data_files\n"
                       "datas = collect_data_files('fancywords')\n")
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": "a"})
    report = scan(write("proj/app.py", "import fancywords\n"), site_packages=[site])
    found = finding(report, "data-files")
    assert found.severity is Severity.LOW and "hook-fancywords.py" in found.covered_by
    assert report.pyinstaller_command() == "" and report.exit_code() == 0


def test_hook_without_datas_only_lowers_one_level(make_dist, site, write, hook):
    hook("fancywords", "hiddenimports = ['fancywords.extra']\n")
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": "a"})
    found = finding(scan(write("proj/app.py", "import fancywords\n"), site_packages=[site]), "data-files")
    assert found.severity is Severity.MEDIUM and found.covered_by is None


def test_native_code_loaded_by_path_needs_collect_binaries(make_dist, site, write):
    make_dist("sqldriver", {
        "sqldriver/__init__.py": "import importlib.util, os\nHERE = os.path.dirname(__file__)\n"
                                 "spec = importlib.util.spec_from_file_location('ddbc', os.path.join(HERE, 'x.pyd'))\n",
        "sqldriver/ddbc_bindings.cp312-win_amd64.pyd": "", "sqldriver/libs/msodbcsql18.dll": "",
    })
    report = scan(write("proj/app.py", "import sqldriver\n"), site_packages=[site])
    found = finding(report, "native-binaries")
    assert found.severity is Severity.HIGH and found.fixes == [Fix("collect-binaries", "sqldriver")]


def test_own_metadata_lookup_needs_copy_metadata_with_distribution_name(make_dist, site, write):
    make_dist("nice-version", {"nicever/__init__.py": "from importlib.metadata import version\n"
                                                      "__version__ = version(__name__)\n"})
    report = scan(write("proj/app.py", "import nicever\n"), site_packages=[site])
    found = finding(report, "metadata")
    assert found.severity is Severity.HIGH and found.fixes == [Fix("copy-metadata", "nice-version")]


def test_dynamic_imports_inside_a_library(make_dist, site, write):
    make_dist("pluggy-ish", {
        "loader/__init__.py": "import importlib\nBACKENDS = [importlib.import_module(f'loader.backends.{n}') "
                              "for n in NAMES]\nFAST = importlib.import_module('loader.fast')\n"
                              "try:\n    json = importlib.import_module(json_name)\nexcept ImportError:\n"
                              "    json = None\nfor dep in ('urllib3', 'idna'):\n    __import__(dep)\n",
        "loader/fast.py": "", "loader/backends/__init__.py": "", "loader/backends/sqlite.py": "",
    })
    found = finding(scan(write("proj/app.py", "import loader\n"), site_packages=[site]), "dynamic-imports")
    assert found.severity is Severity.MEDIUM
    assert found.fixes == [Fix("collect-submodules", "loader.backends"), Fix("hidden-import", "loader.fast")]


def test_entry_point_plugins_name_the_providers(make_dist, site, write):
    make_dist("hostapp", {"hostapp/__init__.py": "from importlib.metadata import entry_points\n"
                                                 "PLUGINS = [e.load() for e in entry_points(group='hostapp.plugins')]\n"})
    make_dist("hostapp-csv", {"hostapp_csv/__init__.py": "", "hostapp_csv/plugin.py": ""},
              entry_points="[hostapp.plugins]\ncsv = hostapp_csv.plugin:CsvPlugin\n")
    found = finding(scan(write("proj/app.py", "import hostapp\n"), site_packages=[site]), "entry-point-plugins")
    assert found.severity is Severity.MEDIUM
    assert set(found.fixes) == {Fix("copy-metadata", "hostapp-csv"), Fix("hidden-import", "hostapp_csv.plugin")}


def test_dependencies_are_followed_and_marked(make_dist, site, write):
    make_dist("frontend", {"frontend/__init__.py": "import themes_pkg\n"}, requires=("themes-pkg>=1",))
    make_dist("themes-pkg", {"themes_pkg/__init__.py": LOADER, "themes_pkg/words.txt": ""})
    app = write("proj/app.py", "import frontend\n")
    report = scan(app, site_packages=[site])
    assert "needed by frontend" in finding(report, "data-files", "themes_pkg").title
    assert "themes-pkg 1.0 (via frontend)" in report.checked
    assert not scan(app, site_packages=[site], follow_dependencies=False).findings


def test_user_code_mistakes(site, write):
    app = write("proj/app.py", "import importlib, json, multiprocessing\n"
                               "cfg = json.load(open('settings.json'))\n"
                               "fmt = importlib.import_module(f'exporters.{cfg[\"name\"]}')\n"
                               "pdf = importlib.import_module('plugins.pdf')\n")
    write("proj/settings.json", "{}")
    write("proj/exporters/__init__.py", "")
    write("proj/exporters/csv_out.py", "")
    write("proj/exporters/office/__init__.py", "")
    write("proj/exporters/office/xlsx_out.py", "")
    report = scan(app, site_packages=[site])
    assert finding(report, "freeze-support").severity is Severity.HIGH
    relative = finding(report, "relative-path")
    assert relative.severity is Severity.MEDIUM and report.needs_resource_helper
    assert relative.fixes[0].option == "add-data"
    assert relative.fixes[0].value.endswith(f"settings.json{os.pathsep}.")
    # a local package is listed module by module (--collect-submodules finds nothing for it)
    assert finding(report, "dynamic-imports").fixes == [
        Fix("hidden-import", "exporters.csv_out"), Fix("hidden-import", "exporters.office"),
        Fix("hidden-import", "exporters.office.xlsx_out"), Fix("hidden-import", "plugins.pdf")]
    assert "resource_path_helper" in report.to_dict()["fix"]


def test_files_loaded_through_resource_path_get_add_data(site, write):
    app = write("proj/app.py", "import os, sys\n"
                               "def resource_path(rel):\n"
                               "    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))\n"
                               "    return os.path.join(base, rel)\n"
                               "logo = resource_path('assets/logo.png')\nicons = resource_path('icons')\n"
                               "gone = resource_path('not_there.json')\n")
    write("proj/assets/logo.png", "png")
    write("proj/icons/app.ico", "ico")
    report = scan(app, site_packages=[site])
    assert [f.code for f in report.findings] == ["bundle-files"]  # the helper itself is not reported
    found = report.findings[0]
    assert [fix.value.rsplit(os.pathsep, 1)[1] for fix in found.fixes] == ["assets", "icons"]
    assert found.fixes[0].value.endswith(os.path.join("assets", "logo.png") + os.pathsep + "assets")


def test_freeze_support_in_entry_script_is_fine(site, write):
    app = write("proj/app.py", "import multiprocessing\nif __name__ == '__main__':\n"
                               "    multiprocessing.freeze_support()\n")
    assert not scan(app, site_packages=[site]).findings


def test_missing_and_optional_imports(site, write):
    app = write("proj/app.py", "import cv2\ntry:\n    import ujson\nexcept ImportError:\n    ujson = None\n")
    report = scan(app, site_packages=[site])
    cv2, ujson = finding(report, "not-installed", "cv2"), finding(report, "not-installed", "ujson")
    assert cv2.severity is Severity.HIGH and "pip install opencv-python" in cv2.detail
    assert ujson.severity is Severity.LOW


def test_local_modules_are_followed_not_reported(make_dist, site, write):
    make_dist("fancywords", {"fancywords/__init__.py": LOADER, "fancywords/words.txt": ""})
    write("proj/mypkg/__init__.py", "")
    write("proj/mypkg/helpers.py", "from . import config\n")
    write("proj/mypkg/config.py", "import fancywords\n")
    report = scan(write("proj/app.py", "from mypkg import helpers\n"), site_packages=[site])
    assert {f.code for f in report.findings} == {"data-files"}
    assert report.checked == ["fancywords 1.0"]
