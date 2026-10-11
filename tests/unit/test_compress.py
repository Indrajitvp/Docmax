"""`compress` -- PDF compression with the built-in PyMuPDF engine.

Two layers, deliberately:

* **Behaviour around the engine** -- atomic output, validators, error mapping,
  progress, cancellation -- is tested by swapping `compressor.compress_pdf` for a
  stand-in that copies, lies, or breaks. What is being checked is not "does
  PyMuPDF compress" -- that is Artifex's problem -- but "does DocMax behave when
  the engine writes nothing, loses pages, or is cancelled", and a real engine
  makes those cases hard to produce on demand.
* **Real compression** runs the real engine on a PDF with a large image in it,
  because a test that only ever uses a fake would pass with a broken engine.
  There is no skip: PyMuPDF is a base dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from docmax.core.cancellation import NEVER_CANCELLED, CancellationToken
from docmax.core.config import Config
from docmax.core.errors import (
    CancelledError,
    CorruptDocumentError,
    InvalidParameterError,
    OutputValidationError,
    UnsupportedFormatError,
)
from docmax.core.models import DocumentRef, Engine, OutputTarget
from docmax.core.protocols import NULL_PROGRESS
from docmax.core.registry import get_tool
from docmax.core.router import EngineRouter
from docmax.tools._engines import compressor
from docmax.tools.compress.tool import PRESETS
from docmax.tools.compress.validators import is_readable_pdf, page_count_is

if TYPE_CHECKING:
    from collections.abc import Callable

    from docmax.core.models import ToolResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def write_pdf(path: Path, pages: int = 3) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def write_image_pdf(path: Path) -> Path:
    """A one-page PDF carrying a large, high-resolution, noisy photo-like image."""
    import random

    import pymupdf

    rng = random.Random(7)
    width = height = 1200
    samples = bytes(rng.randrange(256) for _ in range(width * height * 3))
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, width, height, samples, False)

    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    page.insert_image(page.rect, pixmap=pixmap)
    document.save(str(path))
    document.close()
    return path


def page_count(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def staged(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob(".*"))


def install_engine(
    monkeypatch: pytest.MonkeyPatch, body: Callable[[Path, Path, str], None]
) -> None:
    """Replace the engine with `body(source, destination, preset)`."""

    def fake(source: Path, destination: Path, *, preset: str) -> None:
        body(source, destination, preset)

    monkeypatch.setattr(compressor, "compress_pdf", fake)


def copies_input(source: Path, destination: Path, preset: str) -> None:
    destination.write_bytes(source.read_bytes())


@pytest.fixture
def router() -> EngineRouter:
    return EngineRouter(config=Config())


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return write_pdf(tmp_path / "doc.pdf", 3)


def run(
    router: EngineRouter,
    source: Path,
    destination: Path,
    *,
    progress: Any = NULL_PROGRESS,
    cancellation: Any = NEVER_CANCELLED,
    **params: Any,
) -> ToolResult:
    return router.run(
        "compress",
        [DocumentRef.from_path(source)],
        OutputTarget(destination=destination, force=True),
        progress=progress,
        cancellation=cancellation,
        **params,
    )


# ---------------------------------------------------------------------------
# Registry and router
# ---------------------------------------------------------------------------


def test_compress_is_discoverable() -> None:
    spec = get_tool("compress")

    assert spec.name == "compress"
    assert spec.supports(Engine.LOCAL)
    assert spec.default_suffix == ".pdf"


def test_compress_has_both_engines() -> None:
    spec = get_tool("compress")

    assert spec.supports(Engine.LOCAL)
    assert spec.supports(Engine.CLOUD)
    assert spec.load_strategy(Engine.CLOUD) is not None


def test_compress_needs_no_external_binary() -> None:
    """The point of the built-in engine: nothing for `setup` to install."""
    assert get_tool("compress").requires_binaries == ()


def test_the_router_loads_the_local_strategy() -> None:
    from docmax.tools.compress.local import CompressLocal

    assert isinstance(get_tool("compress").load_strategy(Engine.LOCAL), CompressLocal)


def test_every_preset_has_a_profile() -> None:
    """`PRESETS` (the CLI's choices) and `PROFILES` (the engine) must not drift."""
    assert set(PRESETS) == set(compressor.PROFILES)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_availability_follows_pymupdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from docmax.tools import _engines
    from docmax.tools.compress.local import CompressLocal

    strategy = CompressLocal()
    assert strategy.is_available() is True
    assert strategy.unavailable_reason() is None

    monkeypatch.setattr(_engines, "has_pymupdf", lambda: False)
    monkeypatch.setattr("docmax.tools.compress.local.has_pymupdf", lambda: False)

    assert strategy.is_available() is False
    reason = strategy.unavailable_reason()
    assert reason is not None
    assert "PyMuPDF" in reason


# ---------------------------------------------------------------------------
# Behaviour, against a stand-in engine
# ---------------------------------------------------------------------------


def test_compress_produces_an_output(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, copies_input)
    out = tmp_path / "small.pdf"

    result = run(router, source, out)

    assert out.is_file()
    assert page_count(out) == 3
    assert result.outputs == (out,)
    assert result.engine_used is Engine.LOCAL


def test_the_result_reports_the_saving(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, copies_input)
    out = tmp_path / "small.pdf"

    result = run(router, source, out)

    details = result.details
    assert details["original_bytes"] == source.stat().st_size
    assert details["compressed_bytes"] == out.stat().st_size
    assert details["saved_bytes"] == details["original_bytes"] - details["compressed_bytes"]
    assert details["pages"] == 3
    assert details["preset"] == "ebook"


def test_a_negative_saving_is_reported_rather_than_hidden(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compression can make an already-optimised file larger. Say so."""

    def pads(src: Path, dst: Path, preset: str) -> None:
        dst.write_bytes(src.read_bytes() + b"%" + b"padding" * 500)

    install_engine(monkeypatch, pads)

    result = run(router, source, tmp_path / "bigger.pdf")

    assert result.details["saved_bytes"] < 0


@pytest.mark.parametrize("preset", PRESETS)
def test_every_preset_is_accepted(
    router: EngineRouter,
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preset: str,
) -> None:
    install_engine(monkeypatch, copies_input)

    result = run(router, source, tmp_path / f"{preset}.pdf", preset=preset)

    assert result.details["preset"] == preset


def test_the_preset_reaches_the_engine(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def records(src: Path, dst: Path, preset: str) -> None:
        seen.append(preset)
        copies_input(src, dst, preset)

    install_engine(monkeypatch, records)

    run(router, source, tmp_path / "out.pdf", preset="screen")

    assert seen == ["screen"]


@pytest.mark.parametrize("preset", ["tiny", "", "SCREEN!", 5])
def test_an_unknown_preset_is_refused(
    router: EngineRouter,
    source: Path,
    tmp_path: Path,
    preset: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_engine(monkeypatch, copies_input)

    with pytest.raises(InvalidParameterError) as caught:
        run(router, source, tmp_path / "out.pdf", preset=preset)

    assert "ebook" in (caught.value.remedy or ""), "the real presets are listed"


# ---------------------------------------------------------------------------
# When the engine misbehaves
# ---------------------------------------------------------------------------


def test_an_engine_that_writes_nothing_is_caught(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delivering nothing as success would be worse than failing."""
    install_engine(monkeypatch, lambda src, dst, preset: None)

    with pytest.raises(OutputValidationError):
        run(router, source, tmp_path / "out.pdf")


def test_an_empty_output_is_caught(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, lambda src, dst, preset: dst.write_bytes(b""))

    with pytest.raises(OutputValidationError):
        run(router, source, tmp_path / "out.pdf")


def test_losing_pages_is_caught(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure a user would be least likely to notice: smaller, and wrong."""

    def keeps_one_page(src: Path, dst: Path, preset: str) -> None:
        write_pdf(dst, 1)

    install_engine(monkeypatch, keeps_one_page)

    with pytest.raises(OutputValidationError) as caught:
        run(router, source, tmp_path / "out.pdf")

    assert caught.value.context["expected"] == 3
    assert caught.value.context["actual"] == 1


def test_garbage_output_is_caught(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, lambda src, dst, preset: dst.write_bytes(b"not a pdf"))

    with pytest.raises(OutputValidationError):
        run(router, source, tmp_path / "out.pdf")


# ---------------------------------------------------------------------------
# Atomic output
# ---------------------------------------------------------------------------


def test_a_failure_leaves_the_previous_output_untouched(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(src: Path, dst: Path, preset: str) -> None:
        raise CorruptDocumentError("engine blew up")

    install_engine(monkeypatch, fails)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"a previous run's output")

    with pytest.raises(CorruptDocumentError):
        run(router, source, out)

    assert out.read_bytes() == b"a previous run's output"
    assert staged(tmp_path) == []


def test_a_failure_creates_no_output_at_all(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(src: Path, dst: Path, preset: str) -> None:
        raise CorruptDocumentError("engine blew up")

    install_engine(monkeypatch, fails)
    out = tmp_path / "out.pdf"

    with pytest.raises(CorruptDocumentError):
        run(router, source, out)

    assert not out.exists()
    assert staged(tmp_path) == []


def test_a_rejected_output_leaves_nothing_behind(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validators run against the staged file, so a bad result is never delivered."""
    install_engine(monkeypatch, lambda src, dst, preset: dst.write_bytes(b"not a pdf"))
    out = tmp_path / "out.pdf"
    out.write_bytes(b"the original")

    with pytest.raises(OutputValidationError):
        run(router, source, out)

    assert out.read_bytes() == b"the original"
    assert staged(tmp_path) == []


def test_no_staged_file_survives_success(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, copies_input)

    run(router, source, tmp_path / "out.pdf")

    assert staged(tmp_path) == []


# ---------------------------------------------------------------------------
# Input validation, progress and cancellation
# ---------------------------------------------------------------------------


def test_a_non_pdf_is_refused_before_the_engine_runs(
    router: EngineRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(src: Path, dst: Path, preset: str) -> None:
        raise AssertionError("the engine should not have run")

    install_engine(monkeypatch, must_not_run)
    notes = tmp_path / "notes.txt"
    notes.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        run(router, notes, tmp_path / "out.pdf")


def test_a_corrupt_input_is_refused(
    router: EngineRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, copies_input)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\ngarbage")

    with pytest.raises(CorruptDocumentError):
        run(router, broken, tmp_path / "out.pdf")


def test_progress_is_reported(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Indeterminate: the engine reports nothing usable, and a made-up percentage
    would be a number the user cannot check."""
    install_engine(monkeypatch, copies_input)
    events: list[tuple[str, Any]] = []

    class Recording:
        def start(self, description: str, *, total: int | None = None) -> None:
            events.append(("start", total))

        def advance(self, amount: int = 1) -> None:
            events.append(("advance", amount))

        def finish(self) -> None:
            events.append(("finish", None))

    run(router, source, tmp_path / "out.pdf", progress=Recording())

    assert ("start", None) in events, "no fabricated total"
    assert any(name == "advance" for name, _ in events)


def test_an_already_cancelled_run_produces_nothing(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(monkeypatch, copies_input)
    out = tmp_path / "out.pdf"
    token = CancellationToken()
    token.cancel()

    with pytest.raises(CancelledError):
        run(router, source, out, cancellation=token)

    assert not out.exists()
    assert staged(tmp_path) == []


def test_cancelling_during_the_work_leaves_the_destination_untouched(
    router: EngineRouter, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process work cannot be killed, so the cancellation is honoured before commit."""
    token = CancellationToken()

    def cancelled_midway(src: Path, dst: Path, preset: str) -> None:
        copies_input(src, dst, preset)
        token.cancel()

    install_engine(monkeypatch, cancelled_midway)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"a previous run")

    with pytest.raises(CancelledError):
        run(router, source, out, cancellation=token)

    assert out.read_bytes() == b"a previous run"
    assert staged(tmp_path) == []


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def test_is_readable_pdf_accepts_a_real_pdf(tmp_path: Path) -> None:
    is_readable_pdf(write_pdf(tmp_path / "ok.pdf", 1))


def test_is_readable_pdf_rejects_rubbish(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")

    with pytest.raises(OutputValidationError):
        is_readable_pdf(bad)


def test_page_count_is_reports_the_mismatch(tmp_path: Path) -> None:
    produced = write_pdf(tmp_path / "ok.pdf", 2)

    with pytest.raises(OutputValidationError) as caught:
        page_count_is(5)(produced)

    assert caught.value.context["expected"] == 5
    assert caught.value.context["actual"] == 2


# ---------------------------------------------------------------------------
# The real engine
# ---------------------------------------------------------------------------


def test_the_real_engine_compresses_a_document(router: EngineRouter, tmp_path: Path) -> None:
    src = write_image_pdf(tmp_path / "photo.pdf")
    out = tmp_path / "small.pdf"

    result = run(router, src, out, preset="screen")

    assert out.is_file()
    assert page_count(out) == 1
    assert result.engine_version is not None
    assert result.engine_version.startswith("pymupdf/")
    assert result.details["saved_bytes"] > 0, "a 1200px noise image shown at 4in must shrink"
    assert staged(tmp_path) == []


def test_a_lower_preset_saves_more_than_a_higher_one(router: EngineRouter, tmp_path: Path) -> None:
    src = write_image_pdf(tmp_path / "photo.pdf")

    screen = run(router, src, tmp_path / "screen.pdf", preset="screen").details
    printer = run(router, src, tmp_path / "printer.pdf", preset="printer").details

    assert screen["compressed_bytes"] < printer["compressed_bytes"]


def test_lossless_presets_keep_the_pages(
    router: EngineRouter, source: Path, tmp_path: Path
) -> None:
    out = tmp_path / "default.pdf"

    run(router, source, out, preset="default")

    assert page_count(out) == 3
