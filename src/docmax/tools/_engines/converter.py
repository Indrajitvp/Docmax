"""Lightweight document conversion in pure Python -- no Pandoc.

Covers the pairs that need no real document model: Markdown to HTML, and
Markdown or HTML to plain text. Everything richer (Word, OpenDocument, EPUB,
LaTeX, reStructuredText) needs a genuine converter, and stays with Pandoc when
it is installed; :func:`supports` is how ``convert/local.py`` decides which path
a request takes, so the two never disagree about the boundary.

Plain text from Markdown goes through HTML first, then tag-stripping, rather
than regex-stripping Markdown syntax: that way tables, lists and fenced code
come out as text instead of as leftover pipes and backticks.
"""

from __future__ import annotations

from html.parser import HTMLParser

#: ``(source, target)`` format names, as ``tools/_formats.py`` spells them.
NATIVE_PAIRS = frozenset({("md", "html"), ("md", "txt"), ("html", "txt")})

#: Elements after which a line break belongs, so paragraphs and list items do not
#: run together in the plain-text output.
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "hr"}
)
#: Content that is never text a reader sees.
_SKIPPED_TAGS = frozenset({"script", "style", "head", "title"})


def supports(source: str, target: str) -> bool:
    """Whether the built-in converter handles ``source`` -> ``target``."""
    return (source, target) in NATIVE_PAIRS


def convert(text: str, *, source: str, target: str, standalone: bool = True) -> str:
    """Convert ``text`` between two formats in :data:`NATIVE_PAIRS`."""
    if not supports(source, target):
        raise ValueError(f"no built-in conversion from {source} to {target}")

    html = _markdown_to_html(text) if source == "md" else text
    if target == "html":
        return _wrap(html) if standalone else html
    return _html_to_text(html)


def _markdown_to_html(text: str) -> str:
    import markdown

    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def _wrap(fragment: str) -> str:
    """A complete document around a fragment -- what ``--standalone`` asks for."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title></title>\n</head>\n<body>\n"
        f"{fragment}\n</body>\n</html>\n"
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()

    lines = [line.rstrip() for line in "".join(extractor.parts).splitlines()]
    collapsed: list[str] = []
    for line in lines:
        # At most one blank line in a row: block tags each add a break, and two
        # adjacent ones should read as one paragraph gap.
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip() + "\n"


def version() -> str:
    """``markdown/<version>`` -- the same ``engine/version`` form every engine reports."""
    import markdown

    return f"markdown/{markdown.__version__}"


__all__ = ["NATIVE_PAIRS", "convert", "supports", "version"]
