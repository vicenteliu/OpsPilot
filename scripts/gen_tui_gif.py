"""Generate docs/assets/tui.gif — a scripted tour of the OpsPilot TUI.

Drives the Textual app headlessly (Pilot), exports one SVG frame per
screen, rasterises the frames with headless Chrome, and assembles an
animated GIF with Pillow. No terminal emulator or recording involved;
each frame is captured only after the command's worker has finished, so
rendering is deterministic (frame *content* still reflects whatever live
data sits in ~/.opspilot on this machine).

Usage (from repo root, venv active, Google Chrome installed):

    python scripts/gen_tui_gif.py
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_GIF = REPO_ROOT / "docs" / "assets" / "tui.gif"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TERM_SIZE = (110, 30)  # cols, rows
FRAME_MS = 2200  # per-frame duration

# (slash command to type, frame label)
TOUR: list[tuple[str, str]] = [
    ("/help", "help"),
    ("/sessions", "sessions"),
    ("/kb list", "kb-list"),
    ("/wiki list", "wiki-list"),
    ("/providers", "providers"),
]


async def capture_frames(svg_dir: Path) -> list[Path]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from opspilot.tui.app import OpsPilotApp

    frames: list[Path] = []
    async with OpsPilotApp().run_test(size=TERM_SIZE) as pilot:
        # Headless, the app's Rich console defaults to 80 cols and RichLog
        # measures content against it, wrapping lines that would fit the
        # terminal. Real ttys don't hit this; align the console explicitly.
        pilot.app.console.width = TERM_SIZE[0]
        await pilot.pause(0.5)
        for i, (command, label) in enumerate(TOUR):
            for ch in command:
                await pilot.press("space" if ch == " " else ch)
            await pilot.press("enter")
            # Commands run as thread workers; wait for them instead of
            # guessing a settle time, then let the queued writes render.
            await pilot.app.workers.wait_for_complete()
            await pilot.pause(0.2)
            svg = pilot.app.export_screenshot(title=f"OpsPilot TUI — {command}")
            path = svg_dir / f"{i:02d}-{label}.svg"
            path.write_text(svg, encoding="utf-8")
            frames.append(path)
    return frames


def svg_size(svg_path: Path) -> tuple[int, int]:
    text = svg_path.read_text(encoding="utf-8")
    w = re.search(r'width="([\d.]+)"', text)
    h = re.search(r'height="([\d.]+)"', text)
    if w and h:
        return round(float(w.group(1))), round(float(h.group(1)))
    vb = re.search(r'viewBox="[\d.\s-]*?([\d.]+)\s+([\d.]+)"', text)
    if vb:
        return round(float(vb.group(1))), round(float(vb.group(2)))
    raise RuntimeError(f"no width/height or viewBox in {svg_path}")


def rasterise(svg_path: Path, png_path: Path) -> None:
    w, h = svg_size(svg_path)
    html = svg_path.with_suffix(".html")
    html.write_text(
        f'<!doctype html><body style="margin:0">{svg_path.read_text(encoding="utf-8")}</body>',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            CHROME,
            "--headless",
            "--disable-gpu",
            f"--screenshot={png_path}",
            f"--window-size={w},{h}",
            "--hide-scrollbars",
            f"file://{html}",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"chrome failed on {svg_path.name} (exit {proc.returncode}): {stderr}")


def assemble_gif(pngs: list[Path]) -> None:
    images = [Image.open(p).convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for p in pngs]
    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        OUT_GIF,
        save_all=True,
        append_images=images[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
    )
    print(f"wrote {OUT_GIF} ({OUT_GIF.stat().st_size // 1024} KiB, {len(images)} frames)")


def main() -> None:
    if not Path(CHROME).exists():
        sys.exit(f"Google Chrome not found at {CHROME} — install it (or edit CHROME) first.")
    with tempfile.TemporaryDirectory(prefix="tui-frames-") as tmp:
        svg_dir = Path(tmp)
        frames = asyncio.run(capture_frames(svg_dir))
        pngs = []
        for svg in frames:
            png = svg.with_suffix(".png")
            rasterise(svg, png)
            pngs.append(png)
        assemble_gif(pngs)


if __name__ == "__main__":
    main()
