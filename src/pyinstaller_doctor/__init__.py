"""pyinstaller-doctor: find out why your PyInstaller exe fails, and get the exact fix.

Python API::

    from pyinstaller_doctor import scan
    report = scan("app.py")
    print(report.pyinstaller_command())
"""

__version__ = "0.1.0"

from .distcheck import check_dist  # noqa: E402
from .models import DoctorError, Finding, Fix, Report, Severity  # noqa: E402
from .scanner import scan  # noqa: E402
from .warnfile import check_warnfile, parse_warnfile  # noqa: E402

__all__ = ["scan", "check_dist", "check_warnfile", "parse_warnfile", "Report", "Finding", "Fix",
           "Severity", "DoctorError", "__version__"]
