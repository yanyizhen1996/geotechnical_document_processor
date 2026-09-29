"""Provider-independent domain records for document batches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ProviderKind(StrEnum):
    MICROSOFT_FOUNDRY = "microsoft_foundry"
    OPENAI = "openai"


class ProcessingMode(StrEnum):
    PDF_IMAGES = "pdf_images"
    PDF_MARKDOWN = "pdf_markdown"


class DocumentStatus(StrEnum):
    READY = "ready"
    UNSUPPORTED = "unsupported"
    DUPLICATE = "duplicate"
    ERROR = "error"


SUPPORTED_EXTENSIONS = frozenset({".pdf"})


@dataclass(frozen=True, slots=True)
class DocumentItem:
    path: Path
    status: DocumentStatus
    message: str = ""

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def is_ready(self) -> bool:
        return self.status is DocumentStatus.READY


def inspect_document(path: str | Path, seen_paths: set[Path] | None = None) -> DocumentItem:
    """Classify a selected path without reading its content."""
    document_path = Path(path).expanduser().resolve()
    seen_paths = seen_paths if seen_paths is not None else set()

    if document_path in seen_paths:
        return DocumentItem(document_path, DocumentStatus.DUPLICATE, "Already selected")
    if document_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return DocumentItem(document_path, DocumentStatus.UNSUPPORTED, "Unsupported file type")
    if not document_path.is_file():
        return DocumentItem(document_path, DocumentStatus.ERROR, "File was not found")

    seen_paths.add(document_path)
    return DocumentItem(document_path, DocumentStatus.READY)
