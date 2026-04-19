"""Root conftest: verify the nanobot runtime is reachable before collection.

Eleven test modules in this suite transitively import nanobot.agent.tools.
If pytest is invoked with an interpreter whose site-packages lacks nanobot,
collection fails eleven times with a cryptic ModuleNotFoundError. We fail
once here instead, with a message that names the interpreter and the fix.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _ensure_nanobot_importable() -> None:
    try:
        importlib.import_module("nanobot")
    except ImportError as exc:
        raise ImportError(
            "nanobot package not importable from "
            f"{sys.executable}. Activate .venv (.venv/Scripts/activate on "
            "Windows, source .venv/bin/activate on macOS/Linux) or run: "
            "pip install -r requirements-dev.txt. "
            f"Original error: {exc}"
        ) from exc


def _ensure_vendor_syncall_on_syspath() -> None:
    """Make ``import syncall`` resolve from ``vendor/syncall/`` for tests.

    See ``vendor/syncall/.vendor-source.md`` for why syncall is loaded via
    sys.path rather than pip install.
    """
    repo_root = Path(__file__).resolve().parent
    vendor_syncall = repo_root / "vendor" / "syncall"
    if vendor_syncall.is_dir():
        vendor_str = str(vendor_syncall)
        if vendor_str not in sys.path:
            sys.path.insert(0, vendor_str)


_ensure_nanobot_importable()
_ensure_vendor_syncall_on_syspath()
