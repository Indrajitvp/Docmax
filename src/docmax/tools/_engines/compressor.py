"""PDF compression with PyMuPDF -- the replacement for Ghostscript's ``pdfwrite``.

Two levers, applied in order:

1. **Image resampling** for the presets that ask for it. This is where nearly
   all the saving is, and it is what Ghostscript's ``/screen`` and ``/ebook``
   presets actually do. The preset names are Ghostscript's, kept so a user who
   knows ``--preset ebook`` loses nothing and existing scripts keep working.
2. **Structural clean-up** on every preset: unreferenced objects dropped, object
   streams, and every stream deflated. Lossless, so ``prepress`` and ``default``
   do only this.

The honest limit: this does not subset or substitute fonts the way Ghostscript
can, so a text-only PDF with embedded fonts shrinks less here. The result
reports the real byte counts rather than promising a ratio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from docmax.core.errors import CorruptDocumentError

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class Profile:
    """How hard to squeeze images. ``None`` for the threshold means leave them alone."""

    #: Images above this resolution are resampled down to ``target_dpi``.
    threshold_dpi: int | None
    target_dpi: int
    #: JPEG quality for the images that are re-encoded.
    quality: int


#: Keyed by Ghostscript's preset names; ``PRESETS`` in ``compress/tool.py`` must
#: match, which ``tests/unit/test_compress.py`` asserts.
PROFILES: dict[str, Profile] = {
    "screen": Profile(threshold_dpi=110, target_dpi=72, quality=40),
    "ebook": Profile(threshold_dpi=225, target_dpi=150, quality=65),
    "printer": Profile(threshold_dpi=450, target_dpi=300, quality=85),
    "prepress": Profile(threshold_dpi=None, target_dpi=0, quality=0),
    "default": Profile(threshold_dpi=None, target_dpi=0, quality=0),
}


def compress_pdf(source: Path, destination: Path, *, preset: str) -> None:
    """Write a compressed copy of ``source`` to ``destination``.

    ``destination`` is a path staged by ``atomic_path``; the caller validates
    it and swaps it into place.
    """
    import pymupdf

    profile = PROFILES[preset]

    try:
        document = pymupdf.open(str(source))
    except Exception as exc:
        raise CorruptDocumentError(
            f"{source.name} could not be compressed: {exc}",
            context={"path": str(source)},
        ) from exc

    with document:
        if profile.threshold_dpi is not None:
            document.rewrite_images(
                dpi_threshold=profile.threshold_dpi,
                dpi_target=profile.target_dpi,
                quality=profile.quality,
            )
        document.save(
            str(destination),
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=True,
        )


def version() -> str:
    """``pymupdf/<version>`` -- the same ``engine/version`` form every engine reports."""
    import pymupdf

    return f"pymupdf/{pymupdf.__version__}"


__all__ = ["PROFILES", "Profile", "compress_pdf", "version"]
