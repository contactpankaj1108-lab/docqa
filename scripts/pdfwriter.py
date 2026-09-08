"""A minimal text-only PDF writer.

Used to build the sample PDF without pulling a PDF generation library into the
project's dependency list. It emits Helvetica text pages that pypdf can read
back, which is exactly what the sample corpus needs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 in points
MARGIN = 56
FONT_SIZE = 11
LEADING = 15
LINES_PER_PAGE = int((PAGE_HEIGHT - 2 * MARGIN) / LEADING)
WRAP_WIDTH = 92


def _escape(text: str) -> bytes:
    ascii_text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", "-")
        .replace("–", "-")
        .replace("•", "-")
    )
    escaped = ascii_text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("latin-1", "replace")


def _layout(lines: list[str]) -> list[list[str]]:
    """Wrap source lines and paginate them."""
    wrapped: list[str] = []
    for line in lines:
        if not line.strip():
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=WRAP_WIDTH) or [""])
    return [wrapped[i : i + LINES_PER_PAGE] for i in range(0, len(wrapped), LINES_PER_PAGE)] or [
        [""]
    ]


def _content_stream(page_lines: list[str]) -> bytes:
    parts = [
        b"BT\n",
        b"/F1 %d Tf\n" % FONT_SIZE,
        b"%d TL\n" % LEADING,
        b"%d %d Td\n" % (MARGIN, PAGE_HEIGHT - MARGIN),
    ]
    for line in page_lines:
        parts.append(b"(" + _escape(line) + b") Tj T*\n")
    parts.append(b"ET")
    return b"".join(parts)


def write_pdf(path: Path, lines: list[str], title: str = "") -> Path:
    pages = _layout(lines)
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-indexed object number

    catalog_id = add(b"")  # placeholder, filled once the pages tree exists
    pages_id = add(b"")
    font_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    page_ids: list[int] = []
    for page_lines in pages:
        stream = _content_stream(page_lines)
        content_id = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_id = add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, PAGE_WIDTH, PAGE_HEIGHT, font_id, content_id)
        )
        page_ids.append(page_id)

    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id

    info_id = add(b"<< /Title (" + _escape(title) + b") /Producer (docqa-samples) >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog_id,
        info_id,
        xref_offset,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path
