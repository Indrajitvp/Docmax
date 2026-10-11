"""The local engine for ``compress``.

## PyMuPDF does the work, in-process

This used to rewrite the file through Ghostscript, which pip cannot install. The
engine now resamples images by preset and rewrites the file structure with
PyMuPDF (``tools/_engines/compressor.py``), so ``compress`` works on a fresh
``pip install`` with nothing else on the machine. The preset names are still
Ghostscript's -- ``screen``, ``ebook``, ``printer``, ``prepress``, ``default`` --
so a script that passes ``--preset ebook`` keeps working.

Two properties survive the change because they were never about Ghostscript:

**Output goes through ``atomic_path``.** The staged path is handed to the
compressor, validated, and only then renamed over the destination.

**A smaller broken file is worse than a failure.** The validators reopen the
output and check the page count while the destination is still untouched.

Compression can make a file *larger* -- an already-optimised PDF does -- and the
result says so rather than hiding it.

Nothing is touched at import time: discovery happens on every ``--help``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docmax.core.branding import DIST_NAME
from docmax.core.errors import InvalidParameterError
from docmax.core.models import Engine, ToolResult
from docmax.tools._engines import compressor, has_pymupdf
from docmax.tools._pdf import open_pdf, page_count
from docmax.tools.compress.tool import PRESETS
from docmax.tools.compress.validators import page_count_is

if TYPE_CHECKING:
    from collections.abc import Sequence

    from docmax.core.cancellation import CancellationToken
    from docmax.core.models import DocumentRef, OutputTarget
    from docmax.core.protocols import EngineStrategy, ProgressSink


class CompressLocal:
    """Shrink a PDF by resampling its images and rewriting its structure."""

    def is_available(self) -> bool:
        # `find_spec`, not an import: availability is asked on every routing
        # decision, including the ones that choose a different engine.
        return has_pymupdf()

    def unavailable_reason(self) -> str | None:
        """Why not, including how to fix it."""
        if self.is_available():
            return None
        return (
            f'PyMuPDF is not installed. Install it with: pip install "{DIST_NAME}" '
            "(it is a base dependency, so a broken environment is the likely cause)."
        )

    def run(
        self,
        docs: Sequence[DocumentRef],
        target: OutputTarget,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
        **params: Any,
    ) -> ToolResult:
        """Compress ``docs[0]`` into ``target``."""
        import time

        from docmax.core.atomic import atomic_path

        if not docs:
            raise InvalidParameterError(
                "Compress needs a document.",
                remedy="Pass the PDF to compress.",
            )

        preset = _preset(params)
        document = docs[0]

        # Validated before any work, so a typo in --preset is reported as a typo.
        reader = open_pdf(document)
        pages = page_count(reader)
        original_bytes = document.size_bytes

        started = time.monotonic()

        # One step, not per-page: the library reports nothing usable about its
        # own progress, and inventing a percentage would be a lie the user
        # cannot check. An indeterminate spinner is the honest rendering.
        progress.start(f"Compressing {pages} page(s)", total=None)
        cancellation.raise_if_cancelled(operation="compress")

        with atomic_path(target, validators=(page_count_is(pages),)) as staged:
            compressor.compress_pdf(document.path, staged, preset=preset)
            # In-process work cannot be interrupted mid-call, so a cancellation
            # that arrived during it is honoured here, before anything is
            # committed: the staged file is discarded and the destination is
            # exactly as it was.
            cancellation.raise_if_cancelled(operation="compress")
            progress.advance()

        compressed_bytes = target.destination.stat().st_size
        return ToolResult(
            outputs=(target.destination,),
            engine_used=Engine.LOCAL,
            duration_ms=int((time.monotonic() - started) * 1000),
            engine_version=compressor.version(),
            details={
                "pages": pages,
                "preset": preset,
                "original_bytes": original_bytes,
                "compressed_bytes": compressed_bytes,
                # Reported rather than judged. Compression can make a file
                # *larger* -- an already-optimised PDF does -- and saying so is
                # more useful than hiding it.
                "saved_bytes": original_bytes - compressed_bytes,
            },
        )


def _preset(params: dict[str, Any]) -> str:
    """The preset to use, or an error listing the real ones."""
    value = params.get("preset", "ebook")
    if value is None:
        return "ebook"
    if not isinstance(value, str) or value.lstrip("/") not in PRESETS:
        raise InvalidParameterError(
            f"{value!r} is not a compression preset.",
            remedy=f"Use one of: {', '.join(PRESETS)}.",
            context={"parameter": "preset"},
        )
    return value.lstrip("/")


def build() -> EngineStrategy:
    """Factory the registry calls. Every strategy module exposes exactly this."""
    return CompressLocal()


__all__ = ["CompressLocal", "build"]
