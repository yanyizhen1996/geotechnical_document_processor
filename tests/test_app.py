import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from PySide6.QtCore import Qt, QMimeData, QPointF, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QGroupBox, QScrollArea
import pytest

from document_processor.app import (
    DocumentDropGroupBox,
    DocumentProcessorWindow,
    _calculate_batch_cost,
    _write_csv_outputs,
    _write_markdown_outputs,
    _write_results_file,
    _write_soil_lab_summary_csv_file,
)
from document_processor.domain import ProcessingMode, inspect_document
from document_processor.providers import ProviderRequestError, ProviderTransientError
from document_processor.templates import (
    BOREHOLE_LOG_TEMPLATE_1_KEY,
    BOREHOLE_LOG_TEMPLATE_1_PROMPT,
    BOREHOLE_LOG_TEMPLATE_2_KEY,
    BOREHOLE_LOG_TEMPLATE_2_PROMPT,
    PDF_MARKDOWN_PROMPT,
    PDF_MARKDOWN_TEMPLATE_KEY,
    SOIL_LAB_SUMMARY_PROMPT,
)


def _write_pdf(path: Path, page_count: int) -> None:
    source = pymupdf.open()
    try:
        for _ in range(page_count):
            source.new_page(width=200, height=200)
        source.save(path)
    finally:
        source.close()


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

    csv_output_path = _write_soil_lab_summary_csv_file(json.loads(results), json_output_path)

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
    assert window.contract_template_combo.currentData() == "soil_lab_summary"
    assert window.contract_template_combo.findData(PDF_MARKDOWN_TEMPLATE_KEY) >= 0
    assert not hasattr(window, "processing_mode_combo")
    assert not hasattr(window, "apply_template_button")
    assert [window.contract_template_combo.itemText(index) for index in range(window.contract_template_combo.count())] == [
        "Geotechnical Lab Reports (Extract Values)",
        "Geotechnical Lab Reports (Extract Tables)",
        "Borehole Log Digitization (Standard Template 1)",
        "Borehole Log Digitization (Standard Template 2)",
        "General PDF Text transcription",
        "Custom (edit task and output structure)",
    ]
    assert [window.model_name_combo.itemText(index) for index in range(window.model_name_combo.count())] == [
        "gpt-5-mini",
        "gpt-5.4-mini",
        "gpt-5.6-luna",
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
    assert window.contract_template_combo.count() == 6

    window.prompt_editor.setPlainText("Keep this custom prompt")
    window.output_structure_editor.setPlainText('{"type": "object"}')
    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData(None))

    assert application is not None
    assert window.prompt_editor.toPlainText() == "Keep this custom prompt"
    assert window.output_structure_editor.toPlainText() == '{"type": "object"}'
    window.close()


def test_borehole_log_template_populates_structure() -> None:
    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()

    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData(BOREHOLE_LOG_TEMPLATE_1_KEY))

    assert application is not None
    assert window.prompt_editor.toPlainText() == BOREHOLE_LOG_TEMPLATE_1_PROMPT
    output_structure = json.loads(window.output_structure_editor.toPlainText())
    assert output_structure["required"] == ["borehole_id", "surface_elevation", "depth_unit", "samples", "soil_descriptions"]
    sample_structure = output_structure["properties"]["samples"]["items"]
    assert sample_structure["required"] == ["sample_id", "top_depth", "bottom_depth", "blow_count"]
    assert sample_structure["properties"]["blow_count"]["type"] == ["string", "null"]
    soil_structure = output_structure["properties"]["soil_descriptions"]["items"]
    assert soil_structure["required"] == ["top_depth", "bottom_depth", "description"]
    window.close()


def test_borehole_log_standard_template_two_applies_borehole_identifier_prompt() -> None:
    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()

    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData(BOREHOLE_LOG_TEMPLATE_2_KEY))

    assert application is not None
    assert window.prompt_editor.toPlainText() == BOREHOLE_LOG_TEMPLATE_2_PROMPT
    assert "borehole identifiers are typically labelled with a 'B' or 'P', such as 'B-13', 'PB-13', 'P-3', or 'TP-12'." in window.prompt_editor.toPlainText()
    assert "This identifier applies to the whole page." in window.prompt_editor.toPlainText()
    assert "horizontal blow-count scale displayed at the top of that zone" in window.prompt_editor.toPlainText()
    assert "a triangle marks the blow count" in window.prompt_editor.toPlainText()
    assert "Align the triangle marker to the horizontal scale" in window.prompt_editor.toPlainText()
    assert "even when no ordinary numeric value is printed" in window.prompt_editor.toPlainText()
    assert "50/4\"" in window.prompt_editor.toPlainText()
    assert "Otherwise, set blow_count to null" not in window.prompt_editor.toPlainText()
    output_structure = json.loads(window.output_structure_editor.toPlainText())
    assert output_structure["required"] == ["borehole_id", "surface_elevation", "depth_unit", "samples", "soil_descriptions"]
    window.close()


def test_write_csv_outputs_splits_borehole_samples_and_soil_descriptions(tmp_path) -> None:
    results = json.dumps(
        [
            {
                "document": "log.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "borehole_id": "PB-13",
                        "surface_elevation": "512.3 ft",
                        "depth_unit": "ft",
                        "samples": [
                            {
                                "sample_id": "S-1",
                                "top_depth": "5",
                                "bottom_depth": "6.5",
                                "blow_count": "8 8 9",
                            },
                            {
                                "sample_id": "S-2",
                                "top_depth": "10",
                                "bottom_depth": "11.5",
                                "blow_count": "18",
                            },
                        ],
                        "soil_descriptions": [
                            {"top_depth": "0", "bottom_depth": "4", "description": "Brown silty CLAY"},
                        ],
                    }
                ),
            }
        ]
    )
    json_output_path = _write_results_file(results, tmp_path)

    csv_paths = _write_csv_outputs(json.loads(results), json_output_path)

    samples_path = json_output_path.with_name(f"{json_output_path.stem}_samples.csv")
    soil_path = json_output_path.with_name(f"{json_output_path.stem}_soil_descriptions.csv")
    assert csv_paths == (samples_path, soil_path)
    with samples_path.open(encoding="utf-8-sig", newline="") as source:
        sample_rows = list(csv.DictReader(source))
    with soil_path.open(encoding="utf-8-sig", newline="") as source:
        soil_rows = list(csv.DictReader(source))
    assert sample_rows == [
        {
            "document": "log.pdf",
            "input_mode": "pdf_images",
            "status": "completed",
            "borehole_id": "PB-13",
            "surface_elevation": "512.3 ft",
            "depth_unit": "ft",
            "sample_id": "S-1",
            "top_depth": "5",
            "bottom_depth": "6.5",
            "blow_count": "8 8 9",
        },
        {
            "document": "log.pdf",
            "input_mode": "pdf_images",
            "status": "completed",
            "borehole_id": "PB-13",
            "surface_elevation": "512.3 ft",
            "depth_unit": "ft",
            "sample_id": "S-2",
            "top_depth": "10",
            "bottom_depth": "11.5",
            "blow_count": "18",
        },
    ]
    assert soil_rows == [
        {
            "document": "log.pdf",
            "input_mode": "pdf_images",
            "status": "completed",
            "borehole_id": "PB-13",
            "surface_elevation": "512.3 ft",
            "depth_unit": "ft",
            "top_depth": "0",
            "bottom_depth": "4",
            "description": "Brown silty CLAY",
        },
    ]


def test_write_csv_outputs_flattens_geotech_lab_reports_with_metadata(tmp_path) -> None:
    results = json.dumps(
        [
            {
                "document": "r_value.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "test_type": "Resistance R-Value - ASTM D2844",
                        "location": "PB-41",
                        "sample_number": "G-26-0016",
                        "project_number": "A26173.00276",
                        "project": "RNO92 On-Call Lab Testing",
                        "report_date": "7/25/2026",
                        "summary": "R-value at 300 psi exudation pressure = 75.3",
                        "result_columns": ["No.", "Density pcf", "R Value"],
                        "result_rows": [
                            ["1", "108.0", "67.2"],
                            ["2", "107.8", "77.0"],
                        ],
                    }
                ),
            },
            {
                "document": "thermal.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "test_type": "Thermal Conductivity - ASTM D5334",
                        "location": "PB-31",
                        "sample_number": "G-26-0016",
                        "project_number": "A26173.00276.000",
                        "project": "RNO92 On-Call Lab Testing",
                        "report_date": "7/16-7/20/2026",
                        "summary": None,
                        "result_columns": ["Sample ID", "Temp. (C)"],
                        "result_rows": [["PB-31", "23.5"]],
                    }
                ),
            },
        ]
    )
    json_output_path = _write_results_file(results, tmp_path)

    csv_paths = _write_csv_outputs(json.loads(results), json_output_path)

    assert csv_paths == (json_output_path.with_suffix(".csv"),)
    with csv_paths[0].open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames
        rows = list(reader)
    # Fixed metadata columns first, then the union of result columns across both report types.
    assert fieldnames == [
        "document",
        "input_mode",
        "status",
        "test_type",
        "location",
        "sample_number",
        "project_number",
        "project",
        "report_date",
        "summary",
        "row_number",
        "No.",
        "Density pcf",
        "R Value",
        "Sample ID",
        "Temp. (C)",
    ]
    assert rows[0]["document"] == "r_value.pdf"
    assert rows[0]["test_type"] == "Resistance R-Value - ASTM D2844"
    assert rows[0]["location"] == "PB-41"
    assert rows[0]["summary"] == "R-value at 300 psi exudation pressure = 75.3"
    assert rows[0]["row_number"] == "1"
    assert rows[0]["Density pcf"] == "108.0"
    assert rows[0]["Sample ID"] == ""
    assert rows[2]["document"] == "thermal.pdf"
    assert rows[2]["location"] == "PB-31"
    assert rows[2]["Sample ID"] == "PB-31"
    assert rows[2]["Temp. (C)"] == "23.5"
    assert rows[2]["No."] == ""


def test_geotech_lab_report_merges_headers_differing_only_by_punctuation(tmp_path) -> None:
    results = json.dumps(
        [
            {
                "document": "pb_1.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "test_type": "R-Value - ASTM D2844",
                        "location": "PB-1",
                        "sample_number": "G-26-0016",
                        "result_columns": ["No.", "Exud. Pressure psi", "R Value"],
                        "result_rows": [["1", "207", "58.9"]],
                    }
                ),
            },
            {
                "document": "pb_7.pdf",
                "input_mode": "pdf_images",
                "status": "completed",
                "text": json.dumps(
                    {
                        "test_type": "R-Value - ASTM D2844",
                        "location": "PB-7",
                        "sample_number": "G-26-0016",
                        # Vision model read the period as a hyphen for this document.
                        "result_columns": ["No.", "Exud- Pressure psi", "R Value"],
                        "result_rows": [["1", "491", "68.8"]],
                    }
                ),
            },
        ]
    )
    json_output_path = _write_results_file(results, tmp_path)

    csv_paths = _write_csv_outputs(json.loads(results), json_output_path)

    with csv_paths[0].open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames
        rows = list(reader)
    # The two punctuation variants merge into one column using the first-seen spelling.
    assert fieldnames.count("Exud. Pressure psi") == 1
    assert "Exud- Pressure psi" not in fieldnames
    assert rows[0]["Exud. Pressure psi"] == "207"
    assert rows[1]["Exud. Pressure psi"] == "491"


def test_drag_and_drop_adds_documents(tmp_path) -> None:
    path = tmp_path / "dropped.pdf"
    _write_pdf(path, page_count=1)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    drop_box = window.findChild(DocumentDropGroupBox)
    assert drop_box is not None
    assert drop_box.acceptDrops() is True

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop_box.dropEvent(event)

    assert application is not None
    assert [item.path.name for item in window._documents] == ["dropped.pdf"]
    assert window.document_table.rowCount() == 1
    window.close()


def test_calculate_batch_cost_uses_cached_input_pricing() -> None:
    cost = _calculate_batch_cost("gpt-5.4-mini", prompt_tokens=200, cached_prompt_tokens=100, completion_tokens=50)

    assert cost == pytest.approx(0.0003395)


def test_vision_mode_renders_a_pdf_and_retries_transient_provider_errors(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=1)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    window._documents = [inspect_document(path)]
    window.prompt_editor.setPlainText("Extract values")
    calls: list[tuple[tuple[bytes, ...], str, dict[str, object]]] = []

    class ImageProvider:
        def configure(self, _configuration: object) -> None:
            return None

        def readiness(self) -> SimpleNamespace:
            return SimpleNamespace(ready=False, message="Test provider is not configured.")

        def process_pdf_images(self, pages: tuple[bytes, ...], prompt: str, schema: dict[str, object]) -> dict[str, object]:
            calls.append((pages, prompt, schema))
            if len(calls) == 1:
                raise ProviderTransientError("The read operation timed out")
            return {
                "text": "{}",
                "usage": {
                    "prompt_tokens": 200,
                    "prompt_tokens_details": {"cached_tokens": 100},
                    "completion_tokens": 50,
                },
            }

    window._provider = ImageProvider()
    monkeypatch.setattr("document_processor.app.RETRY_BACKOFF_SECONDS", 0)
    results: list[tuple[str, int, int, int, str]] = []
    window.batch_completed.connect(
        lambda result_text, prompt_tokens, cached_prompt_tokens, completion_tokens, model_name: results.append(
            (result_text, prompt_tokens, cached_prompt_tokens, completion_tokens, model_name)
        )
    )

    window._run_batch()

    assert application is not None
    assert len(calls) == 2
    assert calls[0][0][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert calls[0][1] == "Extract values"
    result = json.loads(results[0][0])[0]
    assert result["input_mode"] == ProcessingMode.PDF_IMAGES
    assert "usage" not in result
    assert results[0][1:] == (200, 100, 50, "gpt-5.6-luna")
    assert window.token_usage_label.text() == (
        "Batch token usage: input 200 | cached input 100 | output 50 | total 250 | estimated cost $0.000410"
    )


def test_markdown_mode_hides_structured_controls_and_skips_json_validation(tmp_path) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=1)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    structured_prompt = window.prompt_editor.toPlainText()
    structured_output_structure = window.output_structure_editor.toPlainText()
    window._documents = [inspect_document(path)]
    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData(PDF_MARKDOWN_TEMPLATE_KEY))

    assert application is not None
    assert window.prompt_editor.toPlainText() == PDF_MARKDOWN_PROMPT
    assert window.contract_template_combo.isEnabled() is True
    assert window.output_structure_editor.isEnabled() is False
    assert window.output_structure_editor.isHidden() is True
    window.output_structure_editor.setPlainText("not valid JSON")
    assert window._validate_batch(show_success=False) is True

    window.contract_template_combo.setCurrentIndex(window.contract_template_combo.findData("soil_lab_summary"))
    assert window.contract_template_combo.isEnabled() is True
    assert window.output_structure_editor.isEnabled() is True
    assert window.output_structure_editor.isHidden() is False
    assert window.prompt_editor.toPlainText() == structured_prompt
    assert window.output_structure_editor.toPlainText() == structured_output_structure
    window.close()


def test_markdown_mode_transcribes_each_pdf_page_in_order_and_aggregates_usage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=2)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    calls: list[bytes] = []

    class MarkdownProvider:
        def process_pdf_page_markdown(self, page_image: bytes, _prompt: str) -> dict[str, object]:
            calls.append(page_image)
            if len(calls) == 1:
                raise ProviderTransientError("The read operation timed out")
            if len(calls) == 2:
                return {
                    "text": "```markdown\n# First page\n```",
                    "usage": {
                        "prompt_tokens": 200,
                        "prompt_tokens_details": {"cached_tokens": 100},
                        "completion_tokens": 50,
                    },
                }
            return {
                "text": "# Second page",
                "usage": {
                    "prompt_tokens": 300,
                    "prompt_tokens_details": {"cached_tokens": 120},
                    "completion_tokens": 70,
                },
            }

    monkeypatch.setattr("document_processor.app.RETRY_BACKOFF_SECONDS", 0)
    window._provider = MarkdownProvider()

    result, usage = window._process_single_document(
        inspect_document(path),
        ProcessingMode.PDF_MARKDOWN,
        "Preserve annotations.",
        {},
    )

    assert application is not None
    assert len(calls) == 3
    assert result == {
        "document": "scan.pdf",
        "input_mode": "pdf_markdown",
        "status": "completed",
        "text": "## Page 1\n\n# First page\n\n## Page 2\n\n# Second page\n",
    }
    assert usage == {
        "prompt_tokens": 500,
        "completion_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 220},
    }
    window.close()


def test_markdown_mode_fails_the_pdf_without_silently_discarding_prior_page_usage(tmp_path) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=2)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    call_count = 0

    class FailingMarkdownProvider:
        def process_pdf_page_markdown(self, _page_image: bytes, _prompt: str) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ProviderRequestError("page could not be transcribed")
            return {"text": "# First page", "usage": {"prompt_tokens": 200, "completion_tokens": 50}}

    window._provider = FailingMarkdownProvider()

    result, usage = window._process_single_document(
        inspect_document(path),
        ProcessingMode.PDF_MARKDOWN,
        "",
        {},
    )

    assert application is not None
    assert result["status"] == "failed"
    assert result["error"] == "Page 2: page could not be transcribed"
    assert "text" not in result
    assert usage == {
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    window.close()


def test_write_markdown_outputs_writes_completed_pdf_transcriptions_only(tmp_path) -> None:
    json_output_path = _write_results_file("[]", tmp_path)
    batch_results = [
        {
            "document": "report one.pdf",
            "input_mode": ProcessingMode.PDF_MARKDOWN.value,
            "status": "completed",
            "text": "## Page 1\n\n# Results\n",
        },
        {
            "document": "failed.pdf",
            "input_mode": ProcessingMode.PDF_MARKDOWN.value,
            "status": "failed",
            "error": "Page 2 failed",
        },
        {
            "document": "structured.pdf",
            "input_mode": ProcessingMode.PDF_IMAGES.value,
            "status": "completed",
            "text": "{}",
        },
    ]

    output_paths = _write_markdown_outputs(batch_results, json_output_path)

    assert output_paths == (json_output_path.with_name(f"{json_output_path.stem}_001_report_one.md"),)
    assert output_paths[0].read_text(encoding="utf-8") == "## Page 1\n\n# Results\n"
    assert json_output_path.with_suffix(".csv").exists() is False


def test_batch_completion_routes_markdown_results_away_from_csv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    window.output_dir_input.setText(str(tmp_path))
    csv_calls: list[object] = []

    def unexpected_csv_export(*arguments: object) -> tuple[Path, ...]:
        csv_calls.append(arguments)
        return ()

    monkeypatch.setattr("document_processor.app._write_csv_outputs", unexpected_csv_export)
    window._on_batch_completed(
        json.dumps(
            [
                {
                    "document": "report.pdf",
                    "input_mode": ProcessingMode.PDF_MARKDOWN.value,
                    "status": "completed",
                    "text": "## Page 1\n\n# Results\n",
                }
            ]
        ),
        0,
        0,
        0,
        "gpt-5.6-luna",
    )

    assert application is not None
    assert csv_calls == []
    markdown_paths = tuple(tmp_path.glob("document_processor_results_*_001_report.md"))
    assert len(markdown_paths) == 1
    assert markdown_paths[0].read_text(encoding="utf-8") == "## Page 1\n\n# Results\n"
    window.close()


def test_batch_records_unexpected_worker_failure_instead_of_leaving_the_queue_stuck(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, page_count=1)

    application = QApplication.instance() or QApplication([])
    window = DocumentProcessorWindow()
    window._documents = [inspect_document(path)]
    completed_batches: list[str] = []

    def unexpected_worker_failure(*_arguments: object) -> tuple[dict[str, object], dict[str, object]]:
        raise ConnectionResetError("The connection was reset by the remote host")

    monkeypatch.setattr(window, "_process_single_document", unexpected_worker_failure)
    window.batch_completed.connect(lambda results, *_arguments: completed_batches.append(results))

    window._run_batch()

    assert application is not None
    assert len(completed_batches) == 1
    result = json.loads(completed_batches[0])[0]
    assert result == {
        "document": "scan.pdf",
        "input_mode": ProcessingMode.PDF_IMAGES.value,
        "status": "failed",
        "error": "Unexpected processing failure (ConnectionResetError): The connection was reset by the remote host",
    }
    window.close()
