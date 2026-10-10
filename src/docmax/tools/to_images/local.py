"""The local engine for ``to-images``.

## PyMuPDF draws the page, in-process

This used to run Poppler's ``pdftoppm``, which pip cannot install: a fresh
``pip install`` failed its first ``to-images`` with a system-package instruction.
PyMuPDF ships as a wheel on every supported platform, so the engine is now
available whenever the package is, and the install story is one command.

It is also cheaper. ``pdftoppm`` took a contiguous page range, so an arbitrary
selection like ``1-3,7`` meant one process launch per page -- a thousand-page
document was perhaps twenty seconds of pure overhead. A function call per page
keeps everything that choice bought (arbitrary selections, a progress bar that
advances per page, cancellation that takes effect within one page) and drops the
cost.

PyMuPDF writes PNG and JPEG itself; TIFF goes through Pillow when the ``images``
extra is installed. See ``tools/_engines/renderer.py``.

## The output is a directory

Staged through ``atomic_dir`` and swapped in as a unit, so a run interrupted
after forty of a thousand pages leaves the destination exactly as it was rather
than a directory holding the first forty. ``split`` was the first consumer of
that guarantee; this is the second.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docmax.core.branding import DIST_NAME
from docmax.core.errors import InvalidParameterError
from docmax.core.models import Engine, ToolResult
from docmax.tools import _dpi, _pagespec
from docmax.tools._engines import has_pymupdf, renderer
from docmax.tools._pdf import open_pdf, page_count
from docmax.tools.to_images.validators import image_format_for, renders_images

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from docmax.core.cancellation import CancellationToken
    from docmax.core.models import DocumentRef, OutputTarget
    from docmax.core.protocols import EngineStrategy, ProgressSink

#: Zero-padded so a directory listing sorts the way the document reads. Matches
#: ``split``, because two tools that both number their outputs should not number
#: them differently.
_MIN_DIGITS = 4

#: What this tool renders at when nothing is asked for. The *bounds* live in
#: ``tools/_dpi.py``, shared with ``ocr``: a user who learns what ``--dpi``
#: accepts here must not find that the other tool spells it differently. The
#: default is not shared — this renders for viewing, ``ocr`` feeds a recogniser.
_DEFAULT_DPI = 150


class ToImagesLocal:
    """Render pages to image files with PyMuPDF."""

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
        """Render the selected pages of ``docs[0]`` into the directory ``target``."""
        import time

        from docmax.core.atomic import atomic_dir

        if not docs:
            raise InvalidParameterError(
                "To-images needs a document.",
                remedy="Pass the PDF to render.",
            )

        image_format = image_format_for(params)
        if image_format.name not in renderer.supported_formats():
            raise InvalidParameterError(
                f"`to-images` cannot write {image_format.label}.",
                remedy=f"Use one of: {', '.join(renderer.supported_formats())}.",
                context={"parameter": "format", "format": image_format.name},
            )
        dpi = _dpi.parse(params.get("dpi"), default=_DEFAULT_DPI)

        document = docs[0]

        # The document is read, and the selection resolved, before anything is
        # rendered -- so a bad `--pages` is reported as a bad selection.
        reader = open_pdf(document)
        total = page_count(reader)
        selected = _pagespec.parse(params.get("pages"), total=total)

        started = time.monotonic()

        stem = document.path.stem
        width = max(_MIN_DIGITS, len(str(total)))
        written: list[Path] = []

        progress.start(f"Rendering {len(selected)} of {total} page(s)", total=len(selected))

        pdf = renderer.open_document(document.path)
        try:
            with atomic_dir(
                target, validators=(renders_images(len(selected), image_format),)
            ) as staged:
                for index in selected:
                    # Between pages: nothing is at the destination yet, and the
                    # staged directory is discarded wholesale on the way out.
                    cancellation.raise_if_cancelled(operation="to-images")

                    name = f"{stem}-{index + 1:0{width}d}{image_format.suffix}"
                    renderer.render_page(
                        pdf, index, staged / name, dpi=dpi, format_name=image_format.name
                    )
                    written.append(target.destination / name)
                    progress.advance()
        finally:
            pdf.close()

        return ToolResult(
            outputs=tuple(written),
            engine_used=Engine.LOCAL,
            duration_ms=int((time.monotonic() - started) * 1000),
            engine_version=renderer.version(),
            details={
                "files": len(written),
                "pages": len(selected),
                "format": image_format.name,
                "dpi": dpi,
                "selection": _pagespec.describe(selected),
            },
        )


def build() -> EngineStrategy:
    """Factory the registry calls. Every strategy module exposes exactly this."""
    return ToImagesLocal()


__all__ = ["ToImagesLocal", "build"]
