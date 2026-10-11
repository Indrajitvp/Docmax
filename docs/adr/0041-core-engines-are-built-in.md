# ADR 0041 — Rendering, compression and simple conversion are built in

**Status:** Accepted · 2026-10-11

## Context

Three local engines shelled out to programs that pip cannot install:
Poppler's `pdftoppm` (`to-images`, `ocr`), Ghostscript (`compress`) and Pandoc
(`convert`). A fresh `pip install Docmax` therefore failed its first
`to-images` or `compress` with an instruction to install a system package, and
the install line differed per platform. `setup` existed to paper over that by
driving `apt-get`, `brew` and `winget`.

The Cloud Engine was the stated answer to that pain (ADR 0012, ADR 0034). It is
a good answer for people who want it; it is a poor answer for "I just want to
turn a PDF into PNGs".

## Decision

**The jobs that have a good pure-wheel equivalent are done in-process.**

| Job | Was | Is |
|---|---|---|
| Rasterise a page (`to-images`, `ocr`) | `pdftoppm` | PyMuPDF (`tools/_engines/renderer.py`) |
| Shrink a PDF (`compress`) | Ghostscript `pdfwrite` | PyMuPDF image resampling + structural clean-up (`compressor.py`) |
| Markdown/HTML to HTML or text (`convert`) | Pandoc | `markdown` + stdlib `html.parser` (`converter.py`) |

`pymupdf` and `markdown` become base dependencies. Both ship wheels for every
supported platform. Neither is imported at module scope.

**What is deliberately not replaced:**

- **Tesseract.** There is no pure-Python OCR of comparable quality. `ocr` still
  requires it locally and falls back to `--engine cloud` without it.
- **Pandoc, for rich formats.** Word, ODT, EPUB, LaTeX and reStructuredText need
  a real document model. `convert.local` sends exactly the pairs in
  `converter.NATIVE_PAIRS` to the built-in converter and everything else to
  Pandoc, raising `LocalDependencyMissingError` (which names the install line
  and the cloud engine) when Pandoc is absent. Pandoc is therefore *optional*,
  recorded as `ToolSpec.optional_binaries` / `Binary.optional_for` so nothing
  reports a working install as broken.

**Ghostscript and Poppler leave `EXTERNAL_BINARIES`.** `doctor` reports the
core engines as built in and lists only Tesseract and Pandoc. `setup` keeps its
package-manager logic for those two, and offers Pandoc only when a tool that
lists it is named (`setup convert`), so a bare `setup` never proposes something
no tool needs to run.

## Consequences

- `compress` is not Ghostscript. The preset names are kept so scripts keep
  working, but they now mean image resampling thresholds (`PROFILES` in
  `compressor.py`). Fonts are not subset, so a text-only PDF shrinks less.
  Results report real byte counts, including negative savings.
- Cancelling an in-process run cannot kill a subprocess. `compress` re-checks
  the token before committing, so a cancelled run still writes nothing; it just
  stops when the library call returns, not before.
- `to-images` TIFF output goes through Pillow (the `images` extra) because
  PyMuPDF cannot write TIFF; the error names the extra.
- **Licence.** PyMuPDF is AGPL-3.0 (commercial licences are sold by Artifex).
  It is installed beside DocMax, not bundled, but redistributors should read it.
  If that is unacceptable, `renderer.py` and `compressor.py` are the only places
  to replace.

## Enforced by

- `tests/unit/test_native_engines.py` makes `shutil.which` find nothing and runs
  `to-images`, `compress` and Markdown `convert` end to end.
- `tests/unit/test_binaries.py::test_the_binaries_the_builtin_engines_replaced_are_gone`.
- `tests/hygiene/test_no_heavy_imports.py` lists `pymupdf` and `markdown`.
