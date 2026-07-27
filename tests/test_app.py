import csv
import json
from types import SimpleNamespace

from pypdf import PdfWriter
from PySide6.QtWidgets import QApplication, QGroupBox, QScrollArea
import pytest

from document_processor.app import (
    SOIL_LAB_SUMMARY_PROMPT,
    DocumentProcessorWindow,
    _calculate_batch_cost,
    _write_csv_file,
    _write_results_file,
)
from document_processor.domain import ProcessingMode, inspect_document


def test_write_results_file_creates_json_output(tmp_path) -> None:
    output_path = _write_results_file('[{"status":"completed"}]', tmp_path)

    assert output_path.parent == tmp_path
    assert output_path.name.startswith("document_processor_results_")
    assert output_path.suffix == ".json"
    assert output_path.read_text(encoding="utf-8") == '[{"status":"completed"}]'


def test_write_csv_file_flattens_each_sample_result(tmp_path) -> None:
    results = json.dumps(
        [
            {
                "document": "report.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "test_type": "Liquid and Plastic Limits",
                        "samples": [
                            {
                                "borehole": "PB-20",
                                "sample_id": "S-15",
                                "depth": "57-59 ft",
                                "key_results": [
                                    {"name": "Liquid Limit", "value": "67", "unit": "%"},
                                    {"name": "Plasticity Index", "value": "42", "unit": "%"},
                                ],
                            }
                        ],
                    }
                ),
            }
        ]
    )
    json_output_path = _write_results_file(results, tmp_path)

    csv_output_path = _write_csv_file(results, json_output_path)

    with csv_output_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert csv_output_path == json_output_path.with_suffix(".csv")
    assert rows == [
        {
            "document": "report.pdf",
            "input_mode": "pdf_images",
            "status": "completed",
            "test_type": "Liquid and Plastic Limits",
            "borehole": "PB-20",
            "sample_id": "S-15",
            "depth": "57-59 ft",
            "result_name": "Liquid Limit",
            "result_value": "67",
            "result_unit": "%",
        },
        {
            "document": "report.pdf",
            "input_mode": "pdf_images",
            "status": "completed",
            "test_type": "Liquid and Plastic Limits",
            "borehole": "PB-20",
            "sample_id": "S-15",
            "depth": "57-59 ft",
            "result_name": "Plasticity Index",
            "result_value": "42",
            "result_unit": "%",
        },
    ]


def test_window_layout_supports_compact_resizing() -> None:
    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    window.resize(800, 600)
    window.show()
    application.processEvents()

    assert window.size().width() == 800
    assert window.size().height() == 600
    assert len(window.findChildren(QScrollArea)) == 2
    assert isinstance(window.output_structure_editor.parentWidget(), QGroupBox)
    assert "Batch estimate" not in [group.title() for group in window.findChildren(QGroupBox)]
    assert window.processing_mode_combo.currentData() == ProcessingMode.PDF_IMAGES
    assert [window.model_name_combo.itemText(index) for index in range(window.model_name_combo.count())] == [
        "gpt-5-mini",
        "gpt-5.4-mini",
    ]

    window.close()


def test_soil_lab_summary_template_populates_a_compact_output_structure() -> None:
    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()

    assert window.contract_template_combo.currentData() == "soil_lab_summary"
    assert window.prompt_editor.toPlainText() == SOIL_LAB_SUMMARY_PROMPT
    output_structure = json.loads(window.output_structure_editor.toPlainText())
    assert output_structure["required"] == ["test_type", "samples"]
    assert output_structure["additionalProperties"] is False
    assert output_structure["properties"]["samples"]["type"] == "array"
    sample_structure = output_structure["properties"]["samples"]["items"]
    assert sample_structure["required"] == ["borehole", "sample_id", "depth", "key_results"]
    assert sample_structure["properties"]["key_results"]["items"]["properties"] == {
        "name": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "unit": {"type": ["string", "null"]},
    }
    assert window.contract_template_combo.count() == 2

    window.prompt_editor.setPlainText("Keep this custom prompt")
    window.output_structure_editor.setPlainText('{"type": "object"}')
    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData(None))
    window.apply_template_button.click()

    assert application is not None
    assert window.prompt_editor.toPlainText() == "Keep this custom prompt"
    assert window.output_structure_editor.toPlainText() == '{"type": "object"}'
    window.close()


def test_calculate_batch_cost_uses_cached_input_pricing() -> None:
    cost = _calculate_batch_cost("gpt-5.4-mini", prompt_tokens=200, cached_prompt_tokens=100, completion_tokens=50)

    assert cost == pytest.approx(0.0003395)


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
            return {
                "text": "{}",
                "usage": {
                    "prompt_tokens": 200,
                    "prompt_tokens_details": {"cached_tokens": 100},
                    "completion_tokens": 50,
                },
            }

    window._provider = ImageProvider()
    results: list[tuple[str, int, int, int, str]] = []
    window.batch_completed.connect(
        lambda result_text, prompt_tokens, cached_prompt_tokens, completion_tokens, model_name: results.append(
            (result_text, prompt_tokens, cached_prompt_tokens, completion_tokens, model_name)
        )
    )

    window._run_batch()

    assert application is not None
    assert len(calls) == 1
    assert calls[0][0][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert calls[0][1] == "Extract values"
    result = json.loads(results[0][0])[0]
    assert result["input_mode"] == ProcessingMode.PDF_IMAGES
    assert "usage" not in result
    assert results[0][1:] == (200, 100, 50, "gpt-5-mini")
    assert window.token_usage_label.text() == (
        "Batch token usage: input 200 | cached input 100 | output 50 | total 250 | estimated cost $0.000141"
    )
