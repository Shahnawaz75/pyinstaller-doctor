"""Distribution discovery, file classification, hook discovery and venv layouts."""

import pytest

from pyinstaller_doctor.environment import Environment, in_tests, is_data, is_native, site_packages_for_venv
from pyinstaller_doctor.models import DoctorError


def test_files_are_classified_and_import_names_inferred(make_dist, site):
    make_dist("Fancy-Words", {
        "fancywords/__init__.py": "", "fancywords/data/words.txt": "a", "fancywords/py.typed": "",
        "fancywords/_speed.cp312-win_amd64.pyd": "", "fancywords/LICENSE.txt": "",
        "fancywords/tests/fixture.json": "{}", "fancywords/.DS_Store": "",
        "fancywords.libs/msvcp140-abc.dll": "",
    })
    dist = Environment([site]).dist("fancy_words")
    assert dist is not None and dist.top_level == ["fancywords"]
    files = dist.files_under("fancywords")
    assert [f for f in files if is_data(f) and not in_tests(f)] == ["fancywords/data/words.txt"]
    assert [f for f in files if is_native(f)] == ["fancywords/_speed.cp312-win_amd64.pyd"]
    assert dist.outside_native() == {"fancywords.libs": ["fancywords.libs/msvcp140-abc.dll"]}


def test_top_level_txt_and_requirements(make_dist, site):
    make_dist("PyYAML", {"yaml/__init__.py": "", "_yaml/__init__.py": ""}, top_level=("_yaml", "yaml"),
              requires=("darkdetect", "packaging>=20; python_version > '3.0'", "pytest; extra == 'test'"))
    env = Environment([site])
    assert [d.name for d in env.dists_for_top("yaml")] == ["PyYAML"]
    assert env.dist("pyyaml").requires == ["darkdetect", "packaging"]
    assert env.module_exists("yaml") and not env.module_exists("yaml.missing")


def test_hooks_from_pyinstaller_contrib_and_entry_points(make_dist, site, hook):
    hook("alpha", "from PyInstaller.utils.hooks import collect_data_files\ndatas = collect_data_files('alpha')\n")
    pre_safe = site / "PyInstaller" / "hooks" / "pre_safe_import_module" / "hook-beta.py"
    pre_safe.parent.mkdir(parents=True)
    pre_safe.write_text("", encoding="utf-8")  # not a regular hook
    make_dist("pyinstaller-hooks-contrib", {
        "_pyinstaller_hooks_contrib/__init__.py": "",
        "_pyinstaller_hooks_contrib/stdhooks/hook-gamma.py": "hiddenimports = ['gamma.x']\n",
        "_pyinstaller_hooks_contrib/rthooks/hook-delta.py": "",
    }, entry_points="[pyinstaller40]\nhook-dirs = _pyinstaller_hooks_contrib:get_hook_dirs\n")
    make_dist("selfhooked", {"selfhooked/__init__.py": "",
                             "selfhooked/__pyinstaller/hook-selfhooked.py": "from x import collect_all\n"},
              entry_points="[pyinstaller40]\nhook-dirs = selfhooked.__pyinstaller:get_hook_dirs\n")
    env = Environment([site])
    alpha, gamma, own = env.hook_for("alpha"), env.hook_for("gamma"), env.hook_for("selfhooked")
    assert (alpha.provider, alpha.collects) == ("PyInstaller", {"data"})
    assert (gamma.provider, gamma.collects) == ("pyinstaller-hooks-contrib", {"submodules"})
    assert own.provider == "selfhooked" and own.collects == {"data", "binaries", "submodules", "metadata"}
    assert env.hook_for("beta") is None and env.hook_for("delta") is None


def test_site_packages_for_windows_and_posix_venvs(tmp_path):
    windows = tmp_path / "winvenv" / "Lib" / "site-packages"
    posix = tmp_path / "posixvenv" / "lib" / "python3.12" / "site-packages"
    windows.mkdir(parents=True)
    posix.mkdir(parents=True)
    assert site_packages_for_venv(tmp_path / "winvenv") == [windows]
    assert site_packages_for_venv(tmp_path / "posixvenv") == [posix]
    assert site_packages_for_venv(windows) == [windows]
    with pytest.raises(DoctorError):
        site_packages_for_venv(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    with pytest.raises(DoctorError, match="no Lib/site-packages"):
        site_packages_for_venv(tmp_path / "empty")
