"""Static analysis of one Python file: its imports, and code patterns that break frozen apps."""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass, field

FILE_RELATIVE = "file-relative"  # os.path.dirname(__file__), Path(__file__).parent
LIST_DIR = "list-dir"  # os.listdir() / glob() on the package folder
PKG_RESOURCES = "pkg-resources"  # pkg_resources.resource_filename() & co.
RESOURCES = "importlib-resources"  # importlib.resources.files() & co.
DYNAMIC_IMPORT = "dynamic-import"  # importlib.import_module(name), __import__(name), pkgutil
NATIVE_LOAD = "native-load"  # ctypes.CDLL(), os.add_dll_directory(), spec_from_file_location()
METADATA = "metadata"  # importlib.metadata.version() & co.
ENTRY_POINTS = "entry-points"  # entry_points(group=...)
RELATIVE_OPEN = "relative-open"  # open("config.json") with a relative path (your code only)
BUNDLED_FILE = "bundled-file"  # resource_path("config.json"): must be added with --add-data
FREEZE_SUPPORT = "freeze-support"  # multiprocessing.freeze_support()

#: Patterns that mean "this code reads files that live next to it".
LOADER_KINDS = (FILE_RELATIVE, LIST_DIR, PKG_RESOURCES, RESOURCES)

#: Cheap byte-level test: library files containing none of these words are not parsed at all.
PREFILTER = re.compile(rb"__file__|resource|import_module|__import__|pkgutil|ctypes|LoadLibrary|CDLL|"
                       rb"dll_directory|spec_from_file_location|dlopen|metadata|get_distribution|"
                       rb"entry_points|freeze_support")

PATH_FUNCS = {"dirname", "abspath", "realpath", "split", "normpath", "Path", "PurePath"}
LIST_FUNCS = {"listdir", "scandir", "walk", "glob", "iglob", "iterdir", "rglob"}
PKG_RESOURCE_FUNCS = {"resource_filename", "resource_string", "resource_stream", "resource_listdir",
                      "resource_exists", "resource_isdir"}
RESOURCE_MODULES = ("importlib.resources.", "importlib_resources.")
RESOURCE_FUNCS = {"files", "read_text", "read_binary", "open_text", "open_binary", "path", "contents",
                  "is_resource", "as_file"}
METADATA_MODULES = ("importlib.metadata.", "importlib_metadata.")
METADATA_FUNCS = {"version", "metadata", "distribution", "files", "requires"}
NATIVE_FUNCS = {"ctypes.CDLL", "ctypes.WinDLL", "ctypes.OleDLL", "ctypes.PyDLL", "ctypes.cdll.LoadLibrary",
                "ctypes.windll.LoadLibrary", "ctypes.oledll.LoadLibrary", "ctypes.pydll.LoadLibrary",
                "os.add_dll_directory", "importlib.util.spec_from_file_location",
                "importlib.machinery.ExtensionFileLoader"}
SYSTEM_LIBS = {"kernel32", "user32", "gdi32", "shell32", "ole32", "oleaut32", "advapi32", "ntdll", "msvcrt",
               "shcore", "dwmapi", "uxtheme", "comctl32", "comdlg32", "winmm", "ws2_32", "version", "c",
               "libc", "m", "libm", "dl", "libdl", "objc", "libobjc", "appkit", "foundation"}
OPENERS = {"open", "Path", "read_csv", "read_excel", "read_json", "read_table", "read_parquet",
           "read_pickle", "loadtxt", "genfromtxt", "load_workbook", "imread", "PhotoImage", "iconbitmap",
           "QIcon", "QPixmap", "QImage", "QMovie", "loadUi", "load_file", "truetype", "Sound", "Font",
           "load", "connect"}
PATH_KEYWORDS = {"file", "filename", "fp", "path", "fname", "default"}
GUARD_NAMES = {"ImportError", "ModuleNotFoundError", "PackageNotFoundError", "DistributionNotFound",
               "Exception", "BaseException"}
RELATIVE_RE = re.compile(r"^(?![A-Za-z]:|[\\/~])(?!.*://)[\w .\-\\/]+$")
RELATIVE_FILE_RE = re.compile(r"^(?![A-Za-z]:|[\\/~])(?!.*://)[\w .\-\\/]+\.[A-Za-z0-9]{1,5}$")


@dataclass
class Hit:
    """One risky call found in the source."""

    kind: str
    lineno: int
    code: str  # short source excerpt
    arg: str | None = None  # literal argument: module, distribution, group or path name
    module_level: bool = True  # runs at import time (not inside a function)
    guarded: bool = False  # inside a try/except that catches ImportError/Exception


@dataclass
class ImportRef:
    """One import statement, with relative imports already made absolute."""

    name: str
    lineno: int
    optional: bool = False  # inside try/except ImportError
    from_names: tuple[str, ...] = ()  # ``from name import a, b`` -> ("a", "b")


@dataclass
class ModuleAnalysis:
    """Everything found in one file."""

    imports: list[ImportRef] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    uses_multiprocessing: bool = False
    uses_meipass: bool = False  # already handles sys._MEIPASS (a resource_path() helper)
    error: str | None = None


def _dotted(node: ast.AST) -> str:
    """``os.path.join`` for a Name/Attribute chain; calls inside the chain become ``()``."""
    parts = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):
            parts.append("()")
            node = node.func
        else:
            parts.append(node.id if isinstance(node, ast.Name) else "?")
            return ".".join(reversed(parts))


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _string_prefix(node: ast.AST) -> str | None:
    """Constant start of f"pkg.{name}" or "pkg." + name."""
    if isinstance(node, ast.JoinedStr) and node.values:
        return _literal(node.values[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal(node.left)
    return None


def _mentions_file(node: ast.AST, tainted: frozenset[str] = frozenset()) -> bool:
    """True when the expression uses ``__file__`` (or a name computed from it)."""
    return any((isinstance(n, ast.Name) and (n.id == "__file__" or n.id in tainted))
               or (isinstance(n, ast.Attribute) and n.attr == "__file__") for n in ast.walk(node))


def _catches(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_dotted(t).rsplit(".", 1)[-1] in GUARD_NAMES for t in types)


def _is_system_lib(name: str) -> bool:
    if ".framework" in name.lower():
        return True
    if "/" in name or "\\" in name:
        return False
    stem = name.lower().split(".")[0]
    return stem in SYSTEM_LIBS or stem.startswith(("api-ms-win", "msvcp", "vcruntime"))


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> full dotted name, from every import in the file."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                aliases[alias.asname or head] = alias.name if alias.asname else head
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _tainted_names(tree: ast.AST) -> frozenset[str]:
    """Names assigned from ``__file__`` expressions, e.g. ``HERE = os.path.dirname(__file__)``."""
    assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None]
    tainted: set[str] = set()
    for _ in range(3):  # follow HERE -> DATA_DIR -> THEMES chains
        size = len(tainted)
        for node in assigns:
            if _mentions_file(node.value, frozenset(tainted)):  # type: ignore[arg-type]
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    elts = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
                    tainted.update(e.id for e in elts if isinstance(e, ast.Name))
        if len(tainted) == size:
            break
    return frozenset(tainted)


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str, is_package: bool, user_code: bool, tree: ast.AST) -> None:
        self.module, self.is_package, self.user_code = module, is_package, user_code
        self.aliases = _aliases(tree)
        self.tainted = _tainted_names(tree)
        self.result = ModuleAnalysis()
        self._guarded = 0
        self._in_function = 0
        self._loop_values: dict[str, list[str]] = {}
        self._seen: set[tuple[str, int, str | None]] = set()

    # -- context: try/except, TYPE_CHECKING, functions ------------------------------------------
    def visit_Try(self, node: ast.Try) -> None:
        guarded = int(any(_catches(h) for h in node.handlers))
        self._guarded += guarded
        for stmt in node.body:
            self.visit(stmt)
        self._guarded -= guarded
        for part in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(part)

    visit_TryStar = visit_Try

    def visit_If(self, node: ast.If) -> None:
        if _dotted(node.test).endswith("TYPE_CHECKING"):
            for stmt in node.orelse:
                self.visit(stmt)
        else:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.AST) -> None:
        self._in_function += 1
        self.generic_visit(node)
        self._in_function -= 1

    def visit_For(self, node: ast.For) -> None:
        items = node.iter.elts if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)) else []
        values = [_literal(item) for item in items]
        if isinstance(node.target, ast.Name) and values and all(values):
            self._loop_values[node.target.id] = values  # type: ignore[assignment]
            self.generic_visit(node)
            self._loop_values.pop(node.target.id, None)
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_Lambda = visit_FunctionDef

    # -- imports ----------------------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_import(alias.name, node.lineno, ())

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._absolute(node.module, node.level)
        if base:
            self._add_import(base, node.lineno, tuple(a.name for a in node.names if a.name != "*"))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "ProcessPoolExecutor":
            self.result.uses_multiprocessing = True
        self.result.uses_meipass |= node.attr == "_MEIPASS"
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self.result.uses_meipass |= node.value == "_MEIPASS"  # getattr(sys, "_MEIPASS", ...)

    def _add_import(self, name: str, lineno: int, names: tuple[str, ...]) -> None:
        self.result.imports.append(ImportRef(name, lineno, self._guarded > 0, names))
        if name.split(".")[0] == "multiprocessing" or "ProcessPoolExecutor" in names:
            self.result.uses_multiprocessing = True

    def _absolute(self, module: str | None, level: int) -> str | None:
        """Absolute name of a (possibly relative) import; None if it cannot be resolved."""
        if not level:
            return module
        package = self.module.split(".") if self.is_package else self.module.split(".")[:-1]
        if not package or level - 1 >= len(package):
            return None
        base = package[: len(package) - (level - 1)]
        return ".".join(base + ([module] if module else []))

    # -- calls ------------------------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        name = self._resolve(node.func)
        last = name.rsplit(".", 1)[-1]
        literal = _literal(node.args[0]) if node.args else None
        if last in PATH_FUNCS and any(_mentions_file(a) for a in node.args):
            self._hit(FILE_RELATIVE, node)
        elif last in LIST_FUNCS and self._touches_package_dir(node):
            self._hit(LIST_DIR, node)
        elif last in PKG_RESOURCE_FUNCS:
            self._hit(PKG_RESOURCES, node, literal)
        elif name.startswith(RESOURCE_MODULES) and last in RESOURCE_FUNCS:
            self._hit(RESOURCES, node, literal)
        elif name in ("importlib.import_module", "__import__", "importlib.__import__"):
            loop = self._loop_values.get(node.args[0].id) if node.args and isinstance(node.args[0], ast.Name) else None
            for value in loop or [literal]:  # for name in ("a", "b"): import_module(name)
                self._dynamic_import(node, value)
        elif name in ("pkgutil.iter_modules", "pkgutil.walk_packages"):
            self._hit(DYNAMIC_IMPORT, node)
        elif name in NATIVE_FUNCS or last == "dlopen":
            if not (literal and _is_system_lib(literal)):
                self._hit(NATIVE_LOAD, node, literal)
        elif (name.startswith(METADATA_MODULES) and last in METADATA_FUNCS) or name in (
                "pkg_resources.get_distribution", "pkg_resources.require"):
            self._hit(METADATA, node, literal)
        elif last in ("entry_points", "iter_entry_points", "select", "get"):
            group = self._entry_point_group(node, last)
            if group:
                self._hit(ENTRY_POINTS, node, group)
        elif last == "freeze_support":
            self._hit(FREEZE_SUPPORT, node)
        elif self.user_code and "resource_path" in last.lower():
            if literal and RELATIVE_RE.match(literal):
                self._hit(BUNDLED_FILE, node, literal)
        elif self.user_code and last in OPENERS:
            path = self._relative_path_arg(node)
            if path:
                self._hit(RELATIVE_OPEN, node, path)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # entry_points()["group"] (the Python 3.8/3.9 dict API)
        if isinstance(node.value, ast.Call) and self._resolve(node.value.func).endswith("entry_points"):
            group = _literal(node.slice)
            if group:
                self._hit(ENTRY_POINTS, node, group)
        self.generic_visit(node)

    def _resolve(self, func: ast.AST) -> str:
        dotted = _dotted(func)
        head, _, rest = dotted.partition(".")
        if head in self.aliases:
            return self.aliases[head] + ("." + rest if rest else "")
        return dotted

    def _touches_package_dir(self, node: ast.Call) -> bool:
        receiver = [node.func.value] if isinstance(node.func, ast.Attribute) else []
        values = [*node.args, *(k.value for k in node.keywords), *receiver]
        return any(_mentions_file(v, self.tainted) for v in values)

    def _dynamic_import(self, node: ast.Call, literal: str | None) -> None:
        """Record the module name; ``"pkg.*"`` means "some submodule of pkg" (f"pkg.{name}")."""
        if literal in ("pkg_resources", "setuptools"):  # old namespace-package boilerplate
            return
        prefix = _string_prefix(node.args[0]) if node.args and literal is None else None
        if prefix and prefix.endswith("."):
            literal = prefix + "*"
        if literal and literal.startswith("."):
            level = len(literal) - len(literal.lstrip("."))
            rest = literal[level:]
            wildcard = rest.endswith("*")
            base = self._absolute(rest.rstrip(".*") or None, level)
            literal = f"{base}.*" if base and wildcard else base
        self._hit(DYNAMIC_IMPORT, node, literal)

    def _entry_point_group(self, node: ast.Call, last: str) -> str | None:
        group = next((_literal(k.value) for k in node.keywords if k.arg == "group"), None)
        if last == "iter_entry_points":
            return group or (_literal(node.args[0]) if node.args else None)
        if last == "entry_points":
            return group
        # entry_points().select(group="x") or entry_points().get("x", [])
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if isinstance(receiver, ast.Call) and self._resolve(receiver.func).endswith("entry_points"):
            return group if last == "select" else (_literal(node.args[0]) if node.args else None)
        return None

    def _relative_path_arg(self, node: ast.Call) -> str | None:
        candidates = node.args[:1] + [k.value for k in node.keywords if k.arg in PATH_KEYWORDS]
        for candidate in candidates:
            value = _literal(candidate)
            if value and len(value) < 200 and RELATIVE_FILE_RE.match(value):
                return value
        return None

    def _hit(self, kind: str, node: ast.AST, arg: str | None = None) -> None:
        lineno = getattr(node, "lineno", 0)
        if (kind, lineno, arg) in self._seen:
            return
        self._seen.add((kind, lineno, arg))
        code = ast.unparse(node)
        code = code if len(code) <= 90 else code[:87] + "..."
        self.result.hits.append(Hit(kind, lineno, code, arg, self._in_function == 0, self._guarded > 0))


def analyze_source(source: str | bytes, filename: str = "<string>", module: str = "__main__",
                   is_package: bool = False, user_code: bool = False) -> ModuleAnalysis:
    """Parse ``source`` and return its imports and risky patterns. Never raises on bad code.

    ``module``/``is_package`` are used to resolve relative imports; ``user_code`` enables the
    checks that only make sense for your own code (relative paths passed to ``open()`` & co.).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=filename)
        visitor = _Visitor(module, is_package, user_code, tree)
        visitor.visit(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return ModuleAnalysis(error=f"{type(exc).__name__}: {exc}")
    return visitor.result
