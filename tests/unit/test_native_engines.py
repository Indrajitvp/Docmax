"""The built-in engines: what `pip install` alone is enough to run.

These tests exist to hold one promise: **rendering, compression and the simple
conversions work with no system binary on the machine.** Every test here makes
`shutil.which` find nothing at all, so a regression that quietly reintroduces a
dependency on Ghostscript, Poppler or Pandoc fails here rather than on a user's
first run.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from docmax.core.cancellation import NEVER_CANCELLED
from docmax.core.config import Config
from docmax.core.errors import CorruptDocumentError, LocalDependencyMissingError
from docmax.core.models import DocumentRef, OutputTarget
from docmax.core.protocols import NULL_PROGRESS
from docmax.core.router import EngineRouter
from docmax.tools._engines import converter, renderer


@pytest.fixture(autouse=True)
def no_system_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The machine under test has none of the programs pip cannot install."""
    monkeypatch.setattr(shutil, "which", lambda name, *args, **kwargs: None)


@pytest.fixture
def router() -> EngineRouter:
    return EngineRouter(config=Config())


def run(router: EngineRouter, tool: str, source: Path, destination: Path, **params: Any) -> Any:
    return router.run(
        tool,
        [DocumentRef.from_path(source)],
        OutputTarget(destination=destination, force=True),
        progress=NULL_PROGRESS,
        cancellation=NEVER_CANCELLED,
        **params,
    )


def write_pdf(path: Path, pages: int = 2) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


# ---------------------------------------------------------------------------
# The whole tools, with nothing installed
# ---------------------------------------------------------------------------


def test_to_images_works_with_no_system_binary(router: EngineRouter, tmp_path: Path) -> None:
    out = tmp_path / "pages"

    result = run(router, "to-images", write_pdf(tmp_path / "doc.pdf"), out)

    assert sorted(p.name for p in out.glob("*.png")) == ["doc-0001.png", "doc-0002.png"]
    assert result.engine_version.startswith("pymupdf/")


def test_compress_works_with_no_system_binary(router: EngineRouter, tmp_path: Path) -> None:
    out = tmp_path / "small.pdf"

    result = run(router, "compress", write_pdf(tmp_path / "doc.pdf", 3), out)

    assert out.is_file()
    assert result.details["pages"] == 3


@pytest.mark.parametrize(
    ("target", "expected"),
    [("html", "<h1>Title</h1>"), ("txt", "Title")],
)
def test_convert_markdown_works_with_no_system_binary(
    router: EngineRouter, tmp_path: Path, target: str, expected: str
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Title\n\nSome *words* here.\n", encoding="utf-8")
    out = tmp_path / f"notes.{target}"

    result = run(router, "convert", source, out, to=target)

    assert expected in out.read_text(encoding="utf-8")
    assert result.engine_version.startswith("markdown/")


def test_a_pandoc_only_target_names_pandoc_when_it_is_absent(
    router: EngineRouter, tmp_path: Path
) -> None:
    """The honest edge of "zero binaries": Word needs a real converter."""
    source = tmp_path / "notes.md"
    source.write_text("# Title\n", encoding="utf-8")

    with pytest.raises(LocalDependencyMissingError) as caught:
        run(router, "convert", source, tmp_path / "notes.docx", to="docx")

    assert caught.value.dependency == "pandoc"
    assert caught.value.remedy


def test_a_non_utf8_source_is_a_typed_error(router: EngineRouter, tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_bytes(b"\xff\xfe\x00bad")
    out = tmp_path / "notes.html"

    with pytest.raises(CorruptDocumentError):
        run(router, "convert", source, out, to="html")

    assert not out.exists()


# ---------------------------------------------------------------------------
# converter
# ---------------------------------------------------------------------------


def test_supports_only_the_documented_pairs() -> None:
    assert converter.supports("md", "html")
    assert converter.supports("md", "txt")
    assert converter.supports("html", "txt")
    assert not converter.supports("md", "docx")
    assert not converter.supports("html", "md")
    assert not converter.supports("docx", "html")


def test_an_unsupported_pair_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="no built-in conversion"):
        converter.convert("x", source="md", target="docx")


def test_markdown_tables_and_fences_render() -> None:
    text = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n"

    html = converter.convert(text, source="md", target="html", standalone=False)

    assert "<table>" in html
    assert "<code>code" in html


def test_standalone_wraps_a_complete_document() -> None:
    complete = converter.convert("hi", source="md", target="html", standalone=True)
    fragment = converter.convert("hi", source="md", target="html", standalone=False)

    assert complete.startswith("<!DOCTYPE html>")
    assert "<body>" in complete
    assert "<html" not in fragment


def test_plain_text_drops_markup_but_keeps_structure() -> None:
    text = "# Heading\n\nFirst paragraph.\n\n- one\n- two\n"

    plain = converter.convert(text, source="md", target="txt")

    assert "<" not in plain
    assert "#" not in plain
    lines = plain.splitlines()
    assert lines[0] == "Heading"
    assert "First paragraph." in lines
    assert "one" in lines
    assert "two" in lines


def test_plain_text_from_html_skips_scripts_and_styles() -> None:
    html = "<html><head><style>p{}</style><title>T</title></head><body><script>x()</script><p>Hi &amp; bye</p></body></html>"

    plain = converter.convert(html, source="html", target="txt")

    assert plain == "Hi & bye\n"


def test_plain_text_never_has_two_blank_lines_in_a_row() -> None:
    plain = converter.convert("a\n\n\n\n\nb\n", source="md", target="txt")

    assert "\n\n\n" not in plain


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------


def test_the_renderer_declares_what_it_can_write() -> None:
    assert set(renderer.supported_formats()) == {"png", "jpeg", "tiff"}


def test_an_unsupported_format_is_a_programming_error(tmp_path: Path) -> None:
    document = renderer.open_document(write_pdf(tmp_path / "doc.pdf", 1))
    try:
        with pytest.raises(ValueError, match="unsupported"):
            renderer.render_page(document, 0, tmp_path / "x.bmp", dpi=72, format_name="bmp")
    finally:
        document.close()


def test_opening_a_damaged_pdf_is_a_typed_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")

    with pytest.raises(CorruptDocumentError):
        renderer.open_document(broken)


def test_tiff_without_pillow_names_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def refuse_pillow(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no Pillow")
        return real_import(name, *args, **kwargs)

    document = renderer.open_document(write_pdf(tmp_path / "doc.pdf", 1))
    monkeypatch.setattr(builtins, "__import__", refuse_pillow)
    try:
        with pytest.raises(LocalDependencyMissingError) as caught:
            renderer.render_page(document, 0, tmp_path / "x.tif", dpi=72, format_name="tiff")
    finally:
        monkeypatch.undo()
        document.close()

    assert "images" in (caught.value.remedy or "")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_json_reports_the_core_engines_as_built_in() -> None:
    import json

    from typer.testing import CliRunner

    from docmax.cli import json_output
    from docmax.cli.main import app

    json_output.set_enabled(False)
    try:
        result = CliRunner().invoke(app, ["--json", "doctor"])
    finally:
        json_output.set_enabled(False)

    body = json.loads(result.stdout)["result"]
    assert body["core_engines"] == {"builtin": True, "pymupdf": True}
    assert {b["name"] for b in body["binaries"]} == {"tesseract", "pandoc"}
    pandoc = next(b for b in body["binaries"] if b["name"] == "pandoc")
    assert pandoc["used_by"] == []
    assert pandoc["optional_for"] == ["convert"]
