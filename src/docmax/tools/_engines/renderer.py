"""Page rasterisation with PyMuPDF -- the replacement for Poppler's ``pdftoppm``.

Used by ``to-images`` and by ``ocr`` (which needs a bitmap to hand Tesseract).
In-process, so a thousand-page render is a thousand function calls rather than a
thousand process launches, and a missing system package can no longer be the
reason it fails.

PyMuPDF writes PNG and JPEG itself. It cannot write TIFF, so that one format
goes through Pillow when the ``images`` extra is installed, and says so when it
is not -- the same shape every optional dependency in this project has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docmax.core.branding import DIST_NAME
from docmax.core.errors import CorruptDocumentError, LocalDependencyMissingError

if TYPE_CHECKING:
    from pathlib import Path

#: PyMuPDF's own output names for the formats it writes without help.
_NATIVE_OUTPUT = {"png": "png", "jpeg": "jpeg"}

#: Formats that need Pillow, and the Pillow name for each.
_VIA_PILLOW = {"tiff": "TIFF"}


def supported_formats() -> tuple[str, ...]:
    """The ``ImageFormat.name`` values this renderer can write."""
    return (*_NATIVE_OUTPUT, *_VIA_PILLOW)


def open_document(path: Path) -> Any:
    """Open ``path`` with PyMuPDF, or raise the typed error for a damaged file.

    Returns PyMuPDF's ``Document``; typed ``Any`` because the package is
    imported lazily and is untyped from this project's point of view.
    """
    import pymupdf

    try:
        return pymupdf.open(str(path))
    except Exception as exc:
        raise CorruptDocumentError(
            f"{path.name} could not be rendered: {exc}",
            context={"path": str(path)},
        ) from exc


def render_page(
    document: Any, index: int, destination: Path, *, dpi: int, format_name: str
) -> None:
    """Draw page ``index`` (zero-based) into ``destination`` as ``format_name``.

    ``destination`` is written directly: callers hand in a path inside a
    directory staged by ``atomic_dir`` or a ``TemporaryDirectory``, never a
    user's file.
    """
    if format_name not in _NATIVE_OUTPUT and format_name not in _VIA_PILLOW:
        raise ValueError(f"unsupported image format: {format_name}")

    try:
        pixmap = document[index].get_pixmap(dpi=dpi, alpha=False)
    except Exception as exc:
        raise CorruptDocumentError(
            f"Page {index + 1} could not be rendered: {exc}",
            context={"page": index + 1},
        ) from exc

    native = _NATIVE_OUTPUT.get(format_name)
    if native is not None:
        pixmap.save(str(destination), output=native)
        return

    try:
        from PIL import Image
    except ImportError as exc:
        raise LocalDependencyMissingError(
            f"Writing {format_name.upper()} needs Pillow, which is not installed.",
            dependency="Pillow",
            install_hint=f'Install it with: pip install "{DIST_NAME}[images]"',
            context={"format": format_name},
        ) from exc

    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    image.save(str(destination), format=_VIA_PILLOW[format_name])


def version() -> str:
    """``pymupdf/<version>`` -- the same ``engine/version`` form every engine reports."""
    import pymupdf

    return f"pymupdf/{pymupdf.__version__}"


__all__ = ["open_document", "render_page", "supported_formats", "version"]
