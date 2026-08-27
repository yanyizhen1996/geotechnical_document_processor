"""Versioned, provider-independent domain records for document batches."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ProviderKind(StrEnum):
    MICROSOFT_FOUNDRY = "microsoft_foundry"
    OPENAI = "openai"


class ProcessingMode(StrEnum):
    PDF_IMAGES = "pdf_images"
    PDF_MARKDOWN = "pdf_markdown"


class DocumentStatus(StrEnum):
    READY = "ready"
    EXCLUDED = "excluded"
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


@dataclass(frozen=True, slots=True)
class PromptContract:
    task_prompt: str
    output_schema: dict[str, Any]
    version: int = 1


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    kind: ProviderKind = ProviderKind.MICROSOFT_FOUNDRY
    model: str = "foundry-model-id"
    openai_enabled: bool = False

    def is_enabled(self) -> bool:
        return self.kind is ProviderKind.MICROSOFT_FOUNDRY or self.openai_enabled


@dataclass(frozen=True, slots=True)
class BatchSpec:
    documents: tuple[DocumentItem, ...]
    contract: PromptContract
    provider: ProviderConfiguration = field(default_factory=ProviderConfiguration)
    schema_version: int = 1

    @property
    def ready_document_count(self) -> int:
        return sum(document.is_ready for document in self.documents)


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
