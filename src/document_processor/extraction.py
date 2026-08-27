"""PDF page rendering for vision-based document processing."""

from __future__ import annotations

import pymupdf

from .domain import DocumentItem


class PdfRenderingError(RuntimeError):
    """The selected PDF cannot be rendered into page images locally."""


# Rasterization scale for PDF page images; higher improves fine-print legibility at higher token cost.
PDF_RENDER_SCALE = 2.5


def render_pdf_pages(document: DocumentItem) -> tuple[bytes, ...]:
    """Render every page of a ready PDF to in-memory PNG bytes."""
    if not document.is_ready:
        raise PdfRenderingError(f"Cannot render a document with status '{document.status.value}'.")
    if document.extension != ".pdf":
        raise PdfRenderingError("Vision processing is available only for PDF documents.")

    try:
        with pymupdf.open(document.path) as source:
            pages = tuple(
                page.get_pixmap(matrix=pymupdf.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE), alpha=False).tobytes("png")
                for page in source
            )
    except (OSError, RuntimeError, ValueError) as error:
        raise PdfRenderingError(f"Could not render '{document.path.name}': {error}") from error

    if not pages:
        raise PdfRenderingError(f"Could not render '{document.path.name}': the PDF has no pages.")
    return pages