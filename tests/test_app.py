import json
from types import SimpleNamespace

from pypdf import PdfWriter
from PySide6.QtWidgets import QApplication

from document_processor.app import DocumentProcessorWindow, _write_results_file
from document_processor.domain import ProcessingMode, inspect_document


def test_write_results_file_creates_json_output(tmp_path) -> None:
    output_path = _write_results_file('[{"status":"completed"}]', tmp_path)

    assert output_path.parent == tmp_path
    assert output_path.name.startswith("document_processor_results_")
    assert output_path.suffix == ".json"
    assert output_path.read_text(encoding="utf-8") == '[{"status":"completed"}]'


def test_image_mode_renders_a_pdf_and_uses_the_image_provider(tmp_path) -> None:
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as target:
        writer.write(target)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    window._documents = [inspect_document(path)]
    window.processing_mode_combo.setCurrentIndex(window.processing_mode_combo.findData(ProcessingMode.PDF_IMAGES))
    window.prompt_editor.setPlainText("Extract values")
    calls: list[tuple[tuple[bytes, ...], str, dict[str, object]]] = []

    class ImageProvider:
        def configure(self, _configuration: object) -> None:
            return None

        def readiness(self) -> SimpleNamespace:
            return SimpleNamespace(ready=False, message="Test provider is not configured.")

        def process_pdf_images(self, pages: tuple[bytes, ...], prompt: str, schema: dict[str, object]) -> dict[str, object]:
            calls.append((pages, prompt, schema))
            return {"text": "{}", "usage": {}}

    window._provider = ImageProvider()
    results: list[str] = []
    window.batch_completed.connect(results.append)

    window._run_batch()

    assert application is not None
    assert len(calls) == 1
    assert calls[0][0][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert calls[0][1] == "Extract values"
    assert json.loads(results[0])[0]["input_mode"] == ProcessingMode.PDF_IMAGES
