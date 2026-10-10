"""Metadata for ``compress``.

Imported during discovery — on every ``--help`` — so it imports nothing but
``core`` and does no work at import time. PyMuPDF is not imported here;
that happens in the engine, which nobody touches until this tool runs.
"""

from __future__ import annotations

from docmax.core.models import Engine
from docmax.core.registry import Param, ToolSpec, register

#: Ghostscript's preset names, kept although Ghostscript is no longer used. A
#: user who knows `/ebook` should not have to learn a synonym, and existing
#: scripts that pass `--preset ebook` keep working. What each name means is
#: defined in `tools/_engines/compressor.py`.
PRESETS = ("screen", "ebook", "printer", "prepress", "default")

SPEC = register(
    ToolSpec(
        name="compress",
        summary="Shrink a PDF by recompressing its images and structure.",
        category="optimise",
        module=__name__.rpartition(".")[0],
        # Both, since M6. The local engine needs nothing but PyMuPDF, which
        # ships with the package; cloud remains for offloading large files.
        supported_engines=frozenset({Engine.LOCAL, Engine.CLOUD}),
        accepts_multiple_inputs=False,
        default_suffix=".pdf",
        params=(
            Param(
                name="preset",
                description="Compression quality preset.",
                type_="str",
                default="ebook",
                choices=PRESETS,
            ),
        ),
    )
)

__all__ = ["PRESETS", "SPEC"]
