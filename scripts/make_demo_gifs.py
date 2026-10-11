"""Render the README demo GIFs from *real* DocMax output.

Nothing on screen is scripted: each scene builds throwaway PDFs, runs the
installed ``docmax`` command, captures what it printed, and animates exactly
that text. If a command's behaviour changes, re-running this changes the GIF.

    pip install -e . pillow
    python scripts/make_demo_gifs.py

Outputs ``docs/assets/demo.gif`` and ``docs/assets/safety.gif``. Lives outside
``src/`` on purpose: it is a dev tool, and the hygiene suite governs the library.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "docs" / "assets"
WORK = Path(os.environ.get("DEMO_WORKDIR", "C:/demo"))

COLS, ROWS = 80, 22
FONT_SIZE = 15
FONT_PATHS = [
    "C:/Windows/Fonts/CascadiaMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]

BG, BAR = (13, 17, 23), (22, 27, 34)
FG, DIM = (201, 209, 217), (125, 133, 144)
GREEN, RED, BLUE, YELLOW = (63, 185, 80), (248, 81, 73), (88, 166, 255), (210, 153, 34)


def load_font() -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, FONT_SIZE)
    raise SystemExit("No monospace font found; set FONT_PATHS in make_demo_gifs.py")


FONT = load_font()
CW = int(FONT.getlength("M"))
CH = FONT_SIZE + 6
PAD, BAR_H = 18, 34
W = CW * COLS + PAD * 2
H = CH * ROWS + PAD * 2 + BAR_H


def colour_for(line: str) -> tuple[int, int, int]:
    s = line.strip(" │┌┐└┘─")
    if line.startswith("$ "):
        return FG
    if s.startswith(("Wrote", "OK")) or '"ok": true' in line:
        return GREEN
    if s.startswith("→"):
        return YELLOW
    if " output." in line or "error" in s.lower():
        return RED
    if s.startswith(("local engine", "  local engine")):
        return DIM
    return FG


def frame(lines: list[tuple[str, tuple[int, int, int]]], cursor: bool, title: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, BAR_H], fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([PAD + i * 22, 11, PAD + i * 22 + 12, 23], fill=c)
    d.text((W // 2, 17), title, font=FONT, fill=DIM, anchor="mm")
    shown = lines[-ROWS:]
    for row, (text, col) in enumerate(shown):
        y = BAR_H + PAD + row * CH
        if text.startswith("$ "):
            d.text((PAD, y), "$", font=FONT, fill=GREEN)
            d.text((PAD + CW * 2, y), text[2:], font=FONT, fill=FG)
        else:
            d.text((PAD, y), text, font=FONT, fill=col)
    if cursor:
        row = min(len(shown), ROWS) - 1
        last = shown[-1][0] if shown else ""
        x = PAD + CW * len(last)
        y = BAR_H + PAD + row * CH
        d.rectangle([x, y + 2, x + CW - 2, y + CH - 3], fill=FG)
    return img


@dataclass
class Step:
    cmd: str  # typed after "$ " and run exactly as written
    pause_after: int = 1100

    @property
    def argv(self) -> list[str]:
        return shlex.split(self.cmd)


def run(argv: list[str]) -> list[str]:
    exe = shutil.which("docmax") or str(Path(sys.executable).with_name("docmax"))
    env = {**os.environ, "COLUMNS": str(COLS), "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}
    p = subprocess.run(  # noqa: S603 - argv comes from this file, not from input
        [exe, *argv[1:]], cwd=WORK, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    out = (p.stdout + p.stderr).replace("\r", "")
    return [ln.rstrip() for ln in out.split("\n") if ln.strip() != "" or True][:-1] if out else []


def build_fixtures() -> None:
    import pymupdf

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    for name in ("q1", "q2"):
        doc = pymupdf.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 110), f"Quarterly report {name.upper()}", fontsize=26)
            page.insert_text((72, 150), f"Page {i + 1}", fontsize=14)
        doc.save(WORK / f"report_{name}.pdf")


def animate(steps: list[Step], title: str, out: Path) -> None:
    frames: list[Image.Image] = []
    durs: list[int] = []
    lines: list[tuple[str, tuple[int, int, int]]] = []

    def push(img: Image.Image, ms: int) -> None:
        frames.append(img)
        durs.append(ms)

    push(frame([*lines, ("$ ", FG)], True, title), 600)
    for step in steps:
        for n in range(0, len(step.cmd) + 1, 2):
            push(frame([*lines, ("$ " + step.cmd[:n], FG)], True, title), 45)
        push(frame([*lines, ("$ " + step.cmd, FG)], True, title), 350)
        lines.append(("$ " + step.cmd, FG))
        out_lines = run(step.argv)
        # Reveal output in small chunks so long panels do not read as a flash.
        for i in range(0, len(out_lines), 3):
            chunk = out_lines[i : i + 3]
            lines.extend((ln, colour_for(ln)) for ln in chunk)
            push(frame(lines, False, title), 90)
        push(frame([*lines, ("$ ", FG)], True, title), step.pause_after)
        lines.append(("", FG))
    durs[-1] = 3500
    ASSETS.mkdir(parents=True, exist_ok=True)
    pal = [
        f.quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for f in frames
    ]
    pal[0].save(
        out, save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=2
    )
    print(f"{out.relative_to(REPO)}  {len(frames)} frames  {out.stat().st_size // 1024} KiB")  # noqa: T201


def main() -> None:
    build_fixtures()
    animate(
        [
            Step("docmax merge report_q1.pdf report_q2.pdf -o annual.pdf"),
            Step("docmax compress annual.pdf -o small.pdf --preset ebook"),
            Step('docmax watermark small.pdf -o final.pdf --text "CONFIDENTIAL"'),
            Step("docmax get-info final.pdf --json", 2200),
        ],
        "docmax: no Ghostscript, no Poppler, no Docker",
        ASSETS / "demo.gif",
    )
    build_fixtures()
    animate(
        [
            Step("docmax merge report_q1.pdf report_q2.pdf -o report_q1.pdf", 1800),
            Step("docmax merge report_q1.pdf report_q2.pdf -o annual.pdf"),
            Step("docmax merge report_q1.pdf report_q2.pdf -o annual.pdf", 1800),
            Step("docmax merge report_q1.pdf report_q2.pdf -o annual.pdf --force"),
        ],
        "docmax: it refuses to destroy your files",
        ASSETS / "safety.gif",
    )
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
