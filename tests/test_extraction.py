from pathlib import Path

import pymupdf

from document_processor.domain import inspect_document
from document_processor.extraction import PdfRenderingError, render_pdf_pages


def _write_pdf(path: Path, page_count: int) -> None:
    source = pymupdf.open()
    try:
        for _ in range(page_count):
            source.new_page(width=200, height=200)
        source.save(path)
    finally:
        source.close()


def test_render_pdf_pages_returns_a_png_for_each_page(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=2)

    pages = render_pdf_pages(inspect_document(path))

    assert len(pages) == 2
    assert all(page.startswith(b"\x89PNG\r\n\x1a\n") for page in pages)


def test_render_malformed_pdf_returns_normalized_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_text("not a PDF", encoding="utf-8")

    try:
        render_pdf_pages(inspect_document(path))
    except PdfRenderingError as error:
        assert "broken.pdf" in str(error)
    else:
        raise AssertionError("Malformed PDF should fail rendering")