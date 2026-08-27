from pathlib import Path

from document_processor.domain import DocumentStatus, inspect_document


def test_inspect_document_marks_supported_existing_file_ready(tmp_path: Path) -> None:
    document = tmp_path / "report.pdf"
    document.touch()

    item = inspect_document(document)

    assert item.status is DocumentStatus.READY
    assert item.is_ready


def test_inspect_document_rejects_unsupported_extension(tmp_path: Path) -> None:
    document = tmp_path / "results.csv"
    document.write_text("value\n1\n", encoding="utf-8")

    item = inspect_document(document)

    assert item.status is DocumentStatus.UNSUPPORTED


def test_inspect_document_marks_repeated_path_as_duplicate(tmp_path: Path) -> None:
    document = tmp_path / "report.pdf"
    document.touch()
    seen_paths: set[Path] = set()

    assert inspect_document(document, seen_paths).status is DocumentStatus.READY
    assert inspect_document(document, seen_paths).status is DocumentStatus.DUPLICATE
