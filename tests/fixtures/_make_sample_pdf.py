"""Reproducible generator for ``tests/fixtures/sample.pdf``.

PR-5 ingestion tests need a small PDF with non-trivial structure to
exercise markitdown. We generate it via reportlab so the fixture has no
copyright concerns and can be regenerated identically when reportlab
output changes.

Run from repo root::

    python tests/fixtures/_make_sample_pdf.py

The committed PDF should be a few KB. Re-run if the layout drifts.

Content (1 page):
* Title (English)
* English paragraph mentioning "OpsPilot" and "ingestion test"
* A small data table
* A code block (monospace)
* A Chinese paragraph (loaded via DejaVu / system CJK font if available;
  falls back to ASCII transliteration if CJK font is unavailable, which
  keeps the test reproducible across CI environments).
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent / "sample.pdf"

# Try to register a CJK-capable font; fall back gracefully.
_CJK_CANDIDATES = [
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
CJK_FONT = "Helvetica"
for candidate in _CJK_CANDIDATES:
    if Path(candidate).is_file():
        try:
            pdfmetrics.registerFont(TTFont("CJK", candidate))
            CJK_FONT = "CJK"
            break
        except Exception:  # noqa: BLE001 — fontTools error variants
            continue


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="OpsPilot ingestion test fixture",
        author="OpsPilot test suite",
    )

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    body = styles["BodyText"]
    cjk_body = ParagraphStyle(
        "CJKBody",
        parent=body,
        fontName=CJK_FONT,
        fontSize=10,
        leading=14,
    )
    code = ParagraphStyle(
        "Code",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=9,
        leading=12,
        backColor=colors.lightgrey,
        leftIndent=8,
        rightIndent=8,
    )

    flow: list = []

    flow.append(Paragraph("OpsPilot Ingestion Test Document", h1))
    flow.append(Spacer(1, 0.1 * inch))

    flow.append(
        Paragraph(
            "This is a deterministic test fixture used by the OpsPilot "
            "ingestion pipeline to verify that the markitdown adapter can "
            "round-trip a non-trivial PDF into chunks searchable through "
            "<b>kb_search</b>. Keywords for retrieval tests: "
            "<i>OpsPilot</i>, <i>ingestion</i>, <i>fixture</i>, "
            "<i>markitdown</i>.",
            body,
        )
    )
    flow.append(Spacer(1, 0.15 * inch))

    flow.append(Paragraph("Sample data table", styles["Heading2"]))
    table_data = [
        ["Component", "Stage", "Status"],
        ["redaction", "PR-2", "shipped"],
        ["ollama_provider", "PR-3", "shipped"],
        ["sqlite_store", "PR-4", "shipped"],
        ["lance_store", "PR-4", "shipped"],
        ["ingestion", "PR-5", "in progress"],
    ]
    t = Table(table_data, colWidths=[1.6 * inch, 0.8 * inch, 1.2 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    flow.append(t)
    flow.append(Spacer(1, 0.2 * inch))

    flow.append(Paragraph("Sample code block", styles["Heading2"]))
    flow.append(
        Preformatted(
            "from opspilot.memory import kb_search, init_sqlite\n"
            "conn = init_sqlite('/tmp/kb.db')\n"
            "hits = kb_search('OpsPilot ingestion fixture', ...)\n"
            "assert hits[0].chunk_id is not None",
            code,
        )
    )
    flow.append(Spacer(1, 0.2 * inch))

    flow.append(Paragraph("中文段落 (Chinese paragraph)", styles["Heading2"]))
    if CJK_FONT == "CJK":
        flow.append(
            Paragraph(
                "OpsPilot 的摄取流水线（ingestion pipeline）会把 PDF 里的中文段落"
                "抽出，经过脱敏、切片、向量化后落地到知识库。检索关键词："
                "<font name='CJK'>故障排查</font>、"
                "<font name='CJK'>认证失败</font>、"
                "<font name='CJK'>摄取测试</font>。",
                cjk_body,
            )
        )
    else:
        # No CJK font available — keep ASCII surrogate so test fixture
        # is still useful (markitdown still gets a paragraph to chunk).
        flow.append(
            Paragraph(
                "[chinese-fallback] OpsPilot ingestion pipeline parses "
                "Chinese text. Keywords: gushi paichu, renzheng shibai, "
                "sheke ceshi.",
                body,
            )
        )

    doc.build(flow)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes; cjk_font={CJK_FONT})")


if __name__ == "__main__":
    sys.exit(build())
