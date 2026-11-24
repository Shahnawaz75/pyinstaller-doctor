"""Every code-pattern detector, fed with small source snippets."""

from textwrap import dedent

from pyinstaller_doctor import analysis as A
from pyinstaller_doctor.analysis import analyze_source


def hits(source: str, kind: str, **kwargs) -> list[A.Hit]:
    return [h for h in analyze_source(dedent(source), **kwargs).hits if h.kind == kind]


def test_dirname_of_file_is_detected_once_per_line():
    found = hits("import os\nHERE = os.path.dirname(os.path.abspath(__file__))\n", A.FILE_RELATIVE)
    assert [(h.lineno, h.code) for h in found] == [(2, "os.path.dirname(os.path.abspath(__file__))")]


def test_pathlib_file_parent_is_detected():
    assert hits("from pathlib import Path\nDATA = Path(__file__).parent / 'data.json'\n", A.FILE_RELATIVE)


def test_listdir_on_package_folder_follows_assigned_names():
    source = """
    import os, glob
    HERE = os.path.dirname(__file__)
    THEMES = os.path.join(HERE, "themes")
    names = os.listdir(THEMES)
    icons = glob.glob(os.path.join(HERE, "*.ico"))
    cwd_files = os.listdir(".")
    """
    assert [h.lineno for h in hits(source, A.LIST_DIR)] == [5, 6]


def test_pkg_resources_and_importlib_resources_with_aliases():
    source = """
    import pkg_resources
    from importlib import resources as res
    from importlib.resources import files
    a = pkg_resources.resource_filename(__name__, "a.json")
    b = res.read_text("mypkg", "b.txt")
    c = files("mypkg").joinpath("c.txt")
    """
    assert [h.arg for h in hits(source, A.PKG_RESOURCES)] == [None]
    assert [h.arg for h in hits(source, A.RESOURCES)] == ["mypkg", "mypkg"]


def test_dynamic_imports_literal_relative_computed_and_pkgutil():
    source = """
    import importlib, pkgutil
    a = importlib.import_module("plugins.csv_export")
    b = importlib.import_module(".backend", __package__)
    c = __import__(name)
    for info in pkgutil.iter_modules(__path__):
        pass
    __import__("pkg_resources").declare_namespace(__name__)
    """
    found = hits(source, A.DYNAMIC_IMPORT, module="pkg.loader")
    assert [h.arg for h in found] == ["plugins.csv_export", "pkg.backend", None, None]
    looped = hits("for name in ('urllib3', 'idna'):\n    __import__(name)\n", A.DYNAMIC_IMPORT)
    assert [h.arg for h in looped] == ["urllib3", "idna"]


def test_native_loading_skips_system_libraries():
    source = """
    import ctypes, os, importlib.util
    from ctypes import cdll
    engine = ctypes.CDLL(os.path.join(HERE, "engine.dll"))
    other = cdll.LoadLibrary("libfoo.so")
    os.add_dll_directory(HERE)
    spec = importlib.util.spec_from_file_location("ddbc_bindings", pyd_path)
    user32 = ctypes.WinDLL("user32")
    libc = ctypes.CDLL("libc.so.6")
    """
    assert [h.lineno for h in hits(source, A.NATIVE_LOAD)] == [4, 5, 6, 7]


def test_metadata_calls_record_argument_level_and_guard():
    source = """
    from importlib.metadata import version, PackageNotFoundError
    __version__ = version(__name__)
    try:
        other = version("requests")
    except PackageNotFoundError:
        other = None
    def later():
        return version(__package__)
    import pkg_resources
    dist = pkg_resources.get_distribution("mypkg")
    """
    found = [(h.arg, h.module_level, h.guarded) for h in hits(source, A.METADATA)]
    assert found == [(None, True, False), ("requests", True, True), (None, False, False),
                     ("mypkg", True, False)]


def test_entry_point_group_lookups_in_all_api_styles():
    source = """
    from importlib.metadata import entry_points
    import pkg_resources
    a = entry_points(group="app.plugins")
    b = entry_points().select(group="select.plugins")
    c = list(pkg_resources.iter_entry_points("legacy.plugins"))
    d = entry_points()["dict.plugins"]
    e = entry_points().get("get.plugins", [])
    f = {}.get("not.a.group")
    """
    assert sorted(h.arg for h in hits(source, A.ENTRY_POINTS)) == [
        "app.plugins", "dict.plugins", "get.plugins", "legacy.plugins", "select.plugins"]


def test_multiprocessing_and_freeze_support_detection():
    with_support = analyze_source("import multiprocessing\nif __name__ == '__main__':\n"
                                  "    multiprocessing.freeze_support()\n")
    assert with_support.uses_multiprocessing
    assert [h.kind for h in with_support.hits] == [A.FREEZE_SUPPORT]
    assert analyze_source("from concurrent.futures import ProcessPoolExecutor\n").uses_multiprocessing
    assert not analyze_source("import threading\n").uses_multiprocessing


def test_relative_paths_are_flagged_only_in_user_code():
    source = r"""
    from PIL import Image
    import tkinter as tk
    cfg = open("config.json")
    logo = Image.open("assets/logo.png")
    icon = tk.PhotoImage(file="icon.png")
    absolute = open("/etc/hosts")
    windows = open("C:\\data\\x.csv")
    helper = open(resource_path("config.json"))
    url = open("https://example.com/a.json")
    no_ext = open("README")
    """
    assert [h.arg for h in hits(source, A.RELATIVE_OPEN, user_code=True)] == [
        "config.json", "assets/logo.png", "icon.png"]
    assert hits(source, A.RELATIVE_OPEN, user_code=False) == []


def test_imports_optional_type_checking_and_relative():
    source = """
    import os, requests
    from typing import TYPE_CHECKING
    try:
        import ujson as json
    except ImportError:
        import json
    if TYPE_CHECKING:
        import pandas
    from . import sibling
    from ..core import engine
    """
    imports = analyze_source(dedent(source), module="pkg.sub.mod").imports
    found = {(i.name, i.optional) for i in imports}
    assert {("requests", False), ("ujson", True), ("pkg.sub", False), ("pkg.core", False)} <= found
    assert not any(i.name == "pandas" for i in imports)
    assert next(i for i in imports if i.name == "pkg.sub").from_names == ("sibling",)


def test_bad_source_is_reported_not_raised():
    result = analyze_source("def broken(:\n")
    assert result.error and result.error.startswith("SyntaxError")
    assert result.imports == [] and result.hits == []
