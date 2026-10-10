"""The built-in engines: what ``pip install`` alone is enough to run.

Before this package existed, three of the local engines shelled out to programs
pip cannot install -- Poppler's ``pdftoppm``, Ghostscript and Pandoc -- and a
fresh install failed its first ``to-images`` or ``compress`` with an install
instruction for a system package. These modules do the same jobs with libraries
that arrive as wheels (PyMuPDF, ``markdown``) so the failure mode is gone, not
documented.

Each module is a set of plain functions over paths and strings. They know
nothing about ``ToolResult``, progress or staging: the strategy in each tool's
``local.py`` keeps owning those (rule 4: only ``core/atomic.py`` commits a
destination), and calls down into here for the actual work.

Private to ``tools``, like ``_pdf``. The directory has no ``tool.py``, so the
registry's walk never mistakes it for a tool, and **nothing here imports its
library at module scope** -- ``tests/hygiene/test_no_heavy_imports.py`` holds
that line.
"""

from __future__ import annotations

import importlib.util


def has_pymupdf() -> bool:
    """Whether PyMuPDF can be imported, without importing it.

    ``find_spec`` rather than ``import``: availability is asked on every routing
    decision, including ``--help``.
    """
    return importlib.util.find_spec("pymupdf") is not None


__all__ = ["has_pymupdf"]
