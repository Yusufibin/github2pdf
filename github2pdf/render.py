"""A navigable PDF with embedded fonts and code that wraps without losing lines."""

import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from .models import ConversionError, Document

INK = colors.HexColor("#172435")
MUTED = colors.HexColor("#62758b")
BLUE = colors.HexColor("#2872dd")
PAPER = colors.HexColor("#f3f6fb")
MARGIN = 48


def _fonts():
    assets = Path(__file__).parent / "assets"
    for name, filename in [
        ("Noto", "NotoSans-Regular.ttf"),
        ("NotoBold", "NotoSans-Bold.ttf"),
        ("NotoMono", "NotoSansMono-Regular.ttf"),
    ]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(assets / filename)))
    pdfmetrics.registerFontFamily(
        "Noto", normal="Noto", bold="NotoBold", italic="Noto", boldItalic="NotoBold"
    )


def _display(text: str, font: str = "Noto") -> str:
    """Represent unsupported characters explicitly instead of drawing missing glyphs."""
    supported = pdfmetrics.getFont(font).face.charWidths
    return "".join(c if ord(c) in supported or c in "\n\t" else f"[U+{ord(c):04X}]" for c in text)


class CodeBlock(Flowable):
    font_size = 7.4
    leading = 11
    padding = 12

    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def wrap(self, width, height):
        self.width = width
        self.height = len(self.rows) * self.leading + self.padding * 2
        return self.width, self.height

    def split(self, width, height):
        count = math.floor((height - self.padding * 2) / self.leading)
        if count < 1:
            return []
        return [CodeBlock(self.rows[:count]), CodeBlock(self.rows[count:])]

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(PAPER)
        canvas.roundRect(0, 0, self.width, self.height, 6, stroke=0, fill=1)
        canvas.setFont("NotoMono", self.font_size)
        for index, (number, segments) in enumerate(self.rows):
            y = self.height - self.padding - self.font_size - index * self.leading
            canvas.setFillColor(MUTED)
            canvas.drawRightString(32, y, str(number))
            x = 44
            for value, color in segments:
                canvas.setFillColor(color)
                canvas.drawString(x, y, value)
                x += pdfmetrics.stringWidth(value, "NotoMono", self.font_size)


def code_rows(path: str, content: str, width: float):
    content = _display(content.expandtabs(4).replace("\f", " "), "NotoMono")
    try:
        lexer = get_lexer_for_filename(path, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    style = get_style_by_name("friendly")
    columns = max(
        8, math.floor((width - 58) / pdfmetrics.stringWidth("M", "NotoMono", CodeBlock.font_size))
    )
    rows, pieces = [], []
    number, used, continuation = 1, 0, False
    for token, value in lex(content, lexer):
        color = colors.HexColor("#" + (style.style_for_token(token)["color"] or "172435"))
        for char in value:
            if char == "\n":
                rows.append(("" if continuation else number, pieces))
                number, used, continuation, pieces = number + 1, 0, False, []
                continue
            if used == columns:
                rows.append(("" if continuation else number, pieces))
                pieces, used, continuation = [], 0, True
            if pieces and pieces[-1][1] == color:
                pieces[-1] = (pieces[-1][0] + char, color)
            else:
                pieces.append((char, color))
            used += 1
    if pieces or not rows:
        rows.append(("" if continuation else number, pieces))
    return rows


class SourceDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and hasattr(flowable, "bookmark"):
            key, title = flowable.bookmark
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=0)
            self.notify("TOCEntry", (0, escape(title), self.page, key))


def write_pdf(document: Document, output: Path, page_size: str = "A4") -> Path:
    if not document.files:
        raise ConversionError("No readable files matched. Check filters and file size limits.")
    if page_size not in {"A4", "letter"}:
        raise ConversionError("Page size must be A4 or letter.")
    _fonts()
    output = Path(output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".github2pdf-", suffix=".pdf", dir=output.parent, delete=False
        ) as temporary:
            temp_path = Path(temporary.name)
    except OSError:
        raise ConversionError("Cannot write to the output directory.") from None
    try:
        _build(document, temp_path, page_size)
        os.replace(temp_path, output)
    except Exception as error:
        temp_path.unlink(missing_ok=True)
        if isinstance(error, ConversionError):
            raise
        raise ConversionError(
            f"PDF creation failed ({type(error).__name__}). Existing output was preserved."
        ) from error
    return output


def _build(document: Document, output: Path, page_size: str):
    pagesize = A4 if page_size == "A4" else letter
    width, height = pagesize
    body_width = width - 2 * MARGIN - 12
    styles = {
        "label": ParagraphStyle(
            "label",
            fontName="NotoBold",
            fontSize=10,
            textColor=colors.HexColor("#77b9ff"),
            spaceAfter=25,
        ),
        "title": ParagraphStyle(
            "title",
            fontName="NotoBold",
            fontSize=38,
            leading=46,
            textColor=colors.white,
            spaceAfter=16,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Noto",
            fontSize=16,
            leading=24,
            textColor=colors.HexColor("#b7c9de"),
            spaceAfter=28,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            fontName="Noto",
            fontSize=10,
            leading=17,
            textColor=colors.HexColor("#b7c9de"),
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName="NotoBold",
            fontSize=20,
            leading=26,
            textColor=INK,
            spaceAfter=16,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body", fontName="Noto", fontSize=9.5, leading=15, textColor=MUTED, spaceAfter=12
        ),
        "file": ParagraphStyle(
            "file",
            fontName="NotoBold",
            fontSize=16,
            leading=22,
            textColor=INK,
            spaceAfter=8,
            keepWithNext=True,
        ),
    }

    def safe(text):
        return escape(_display(str(text)))

    def cover(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#101d30"))
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(BLUE)
        canvas.rect(0, height - 12, width, 12, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#7894b4"))
        canvas.setFont("Noto", 8)
        canvas.drawString(MARGIN + 6, 34, "GITHUB2PDF  /  SOURCE EDITION")
        canvas.restoreState()

    def body(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont("Noto", 8)
        title = _display(document.title)
        while pdfmetrics.stringWidth(title, "Noto", 8) > width - 2 * MARGIN - 120:
            title = title[:-2] + "."
        canvas.drawString(MARGIN + 6, height - 28, title)
        canvas.drawRightString(width - MARGIN - 6, height - 28, "SOURCE CODE")
        canvas.setStrokeColor(colors.HexColor("#dce4ef"))
        canvas.line(MARGIN + 6, height - 36, width - MARGIN - 6, height - 36)
        canvas.setFont("Noto", 8)
        canvas.drawString(MARGIN + 6, 28, "github2pdf")
        canvas.drawRightString(width - MARGIN - 6, 28, f"{doc.page}")
        canvas.restoreState()

    doc = SourceDoc(
        str(output),
        pagesize=pagesize,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=54,
        bottomMargin=48,
        title=document.title + " - Source code",
        author="github2pdf",
    )

    def frame():
        return Frame(MARGIN, 48, width - 2 * MARGIN, height - 102, id="content")

    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[frame()], onPage=cover),
            PageTemplate(id="body", frames=[frame()], onPage=body),
        ]
    )
    total_lines = sum(file.lines for file in document.files)
    story = [
        Spacer(1, 65),
        Paragraph("REPOSITORY / SOURCE BOOK", styles["label"]),
        Paragraph(safe(document.title), styles["title"]),
        Paragraph("Your project.<br/>Ready to read.", styles["subtitle"]),
    ]
    stats = Table(
        [
            [
                f"{len(document.files)} FILES",
                f"{total_lines:,} LINES",
                f"{len(document.skipped)} SKIPPED",
            ]
        ],
        colWidths=[body_width / 3] * 3,
    )
    stats.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "NotoBold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#e3efff")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1c304b")),
                ("TOPPADDING", (0, 0), (-1, -1), 18),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
            ]
        )
    )
    story += [
        stats,
        Spacer(1, 30),
        Paragraph(safe(document.origin), styles["cover_meta"]),
        Paragraph("Ref: " + safe(document.ref), styles["cover_meta"]),
    ]
    if document.revision:
        story.append(Paragraph("Commit: " + safe(document.revision), styles["cover_meta"]))
    story += [
        Paragraph(
            "Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d UTC"), styles["cover_meta"]
        ),
        NextPageTemplate("body"),
        PageBreak(),
        Paragraph("Contents", styles["heading"]),
        Paragraph(
            "Click a filename or use the PDF bookmarks to jump to its source.", styles["body"]
        ),
    ]
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "toc",
            fontName="Noto",
            fontSize=9,
            leading=15,
            textColor=INK,
            spaceBefore=5,
            rightIndent=30,
        )
    ]
    story.append(toc)
    for index, file in enumerate(document.files):
        title = Paragraph(safe(file.path), styles["file"])
        title.bookmark = (f"source-{index}", _display(file.path))
        story += [
            PageBreak(),
            title,
            Paragraph(
                f"{file.lines:,} lines  /  {safe(Path(file.path).suffix.lstrip('.') or 'text')}",
                styles["body"],
            ),
            CodeBlock(code_rows(file.path, file.content, body_width)),
        ]
    if document.skipped:
        story += [
            PageBreak(),
            Paragraph("Export notes", styles["heading"]),
            Paragraph(
                "Files omitted by filters or limits are listed below. No file is silently truncated.",
                styles["body"],
            ),
        ]
        # Keep the appendix bounded even for very large archives.
        for path, reason in document.skipped[:500]:
            story.append(Paragraph(f"<b>{safe(path)}</b><br/>{safe(reason)}", styles["body"]))
        if len(document.skipped) > 500:
            story.append(
                Paragraph(
                    f"Plus {len(document.skipped) - 500} omitted entries. Use --verbose for the complete list.",
                    styles["body"],
                )
            )
    doc.multiBuild(story)
