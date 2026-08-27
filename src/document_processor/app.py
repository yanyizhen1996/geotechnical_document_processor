"""PySide6 application shell for creating a document-processing batch."""

from __future__ import annotations

import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .domain import (
    DocumentItem,
    DocumentStatus,
    ProcessingMode,
    ProviderKind,
    inspect_document,
)
from .extraction import PdfRenderingError, render_pdf_pages
from .providers import (
    MicrosoftFoundryConfiguration,
    MicrosoftFoundryProvider,
    ProviderError,
    ProviderRateLimitError,
    ProviderTransientError,
)


SOIL_LAB_SUMMARY_TEMPLATE_KEY = "soil_lab_summary"
SOIL_LAB_SUMMARY_PROMPT = (
    "Review the soil laboratory report and extract only the information needed for a geotechnical laboratory "
    "summary table. Set test_type to the reported laboratory test or standard. Add one samples item for each "
    "tested sample, with its borehole or sample location, sample ID, depth, and only its final reportable test "
    "results. Borehole or sample locations are typically labelled with a 'B' or 'P', such as 'B-13', 'PB-13', "
    "'P-3', or 'TP-12', while sample IDs typically contain an 'S' or 'MC', such as 'S-15' or 'MC-2'; use these "
    "conventions to assign each identifier to the correct field. "
    "Include classification only when it is reported as a final test result. Do not extract client, "
    "project details, report dates, personnel, intermediate weights, calculations, narrative summaries, or other "
    "metadata. Preserve reported values and units. Use null for unavailable sample identifiers and an empty results "
    "list only when a tested sample has no reportable final results."
)
SOIL_LAB_SUMMARY_STRUCTURE = {
    "type": "object",
    "properties": {
        "test_type": {"type": ["string", "null"], "description": "Reported laboratory test or standard"},
        "samples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "borehole": {"type": ["string", "null"], "description": "Borehole or sample location"},
                    "sample_id": {"type": ["string", "null"], "description": "Reported sample identifier"},
                    "depth": {"type": ["string", "null"], "description": "Reported depth or depth interval"},
                    "key_results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": ["string", "null"]},
                                "value": {"type": ["string", "null"]},
                                "unit": {"type": ["string", "null"]},
                            },
                            "required": ["name", "value", "unit"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["borehole", "sample_id", "depth", "key_results"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["test_type", "samples"],
    "additionalProperties": False,
}
BOREHOLE_LOG_TEMPLATE_1_KEY = "borehole_log_standard_1"
BOREHOLE_LOG_TEMPLATE_1_PROMPT = (
    "Digitize this borehole log page into structured data. Set borehole_id to the borehole identifier that labels "
    "the log; borehole identifiers are typically labelled with a 'B' or 'P', such as 'B-13', 'PB-13', 'P-3', or "
    "'TP-12'. This identifier "
    "applies to the whole page. Set surface_elevation to the reported ground surface elevation exactly as written, or "
    "null when none is shown. Determine the single depth unit used on the log (for example 'ft' or 'm') and set "
    "depth_unit to it; record every top_depth and bottom_depth as a plain number in that unit, with no unit suffix. "
    "Depths are shown on a vertical depth scale along the left edge and are usually not printed for each interval, so "
    "read each interval's top and bottom by aligning the edges of its sample marker or material-graphics band to that "
    "scale, using the numbered foot marks and their minor tick subdivisions to interpolate as precisely as you can. A "
    "sample interval is the vertical extent of its marker in the sample-location column; a soil stratum is the vertical "
    "extent of its band in the material-graphics or description column. Ensure top_depth is less than bottom_depth for "
    "each interval. Add one samples item for each sampled interval, with its sample_id and the top_depth and "
    "bottom_depth of its interval. Sample IDs typically contain an 'S' or 'MC', such as 'S-4' or 'MC-2'. Set blow_count to the reported "
    "blow count as text: when the log shows raw per-increment drive counts, join them with single spaces (for example "
    "'8 8 9'); when the log shows a single number, use it as written; set blow_count to null when a sample has no blow "
    "count. Add one soil_descriptions item for each described stratum, with its top_depth, bottom_depth, and "
    "description text; strata boundaries are independent of the sample intervals. Preserve reported values exactly, "
    "other than normalizing depths as described. Do not extract client, project, contractor, dates, personnel, "
    "equipment, drilling method, water levels, narrative notes, or other metadata unless it is one of the fields "
    "above. Use null for any unavailable field and an empty list only when the log has no samples or no soil "
    "descriptions."
)
BOREHOLE_LOG_STRUCTURE = {
    "type": "object",
    "properties": {
        "borehole_id": {"type": ["string", "null"], "description": "Borehole identifier for the whole page, as reported"},
        "surface_elevation": {"type": ["string", "null"], "description": "Reported ground surface elevation, as written"},
        "depth_unit": {"type": ["string", "null"], "description": "Single depth unit used across the log, e.g. 'ft' or 'm'"},
        "samples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": ["string", "null"], "description": "Sample identifier; typically contains 'S'"},
                    "top_depth": {"type": ["string", "null"], "description": "Top of the sample interval as a plain number in depth_unit, no unit suffix"},
                    "bottom_depth": {"type": ["string", "null"], "description": "Bottom of the sample interval as a plain number in depth_unit, no unit suffix"},
                    "blow_count": {"type": ["string", "null"], "description": "Reported blow count as text: space-separated raw drives like '8 8 9', or a single value; null if none"},
                },
                "required": ["sample_id", "top_depth", "bottom_depth", "blow_count"],
                "additionalProperties": False,
            },
        },
        "soil_descriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "top_depth": {"type": ["string", "null"], "description": "Top of the described stratum as a plain number in depth_unit, no unit suffix"},
                    "bottom_depth": {"type": ["string", "null"], "description": "Bottom of the described stratum as a plain number in depth_unit, no unit suffix"},
                    "description": {"type": ["string", "null"], "description": "Soil or material description for the interval"},
                },
                "required": ["top_depth", "bottom_depth", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["borehole_id", "surface_elevation", "depth_unit", "samples", "soil_descriptions"],
    "additionalProperties": False,
}
BOREHOLE_LOG_TEMPLATE_2_KEY = "borehole_log_standard_2"
BOREHOLE_LOG_TEMPLATE_2_PROMPT = (
    "Digitize this borehole log page into structured data. Set borehole_id to the borehole identifier that labels "
    "the log; borehole identifiers are typically labelled with a 'B' or 'P', such as 'B-13', 'PB-13', 'P-3', or "
    "'TP-12'. This identifier applies to the whole page. Set surface_elevation to the reported ground surface "
    "elevation exactly as written, or null "
    "when none is shown. Determine the single depth unit used on the log (for example 'ft' or 'm') and set "
    "depth_unit to it; record every top_depth and bottom_depth as a plain number in that unit, with no unit suffix. "
    "Sample interval depths are shown on a vertical depth scale and are usually not printed for each interval, so "
    "read each interval's top and bottom by aligning the edges of its sample marker or material-graphics band to "
    "that scale and interpolate as precisely as possible. A sample interval is the vertical extent of its marker in "
    "the samples column; a soil stratum is the vertical extent of its band in the material-graphics or description "
    "column. Ensure top_depth is less than bottom_depth for each interval. Add one samples item for each sampled "
    "interval, with its sample_id and the top_depth and bottom_depth of its interval. Sample IDs typically contain "
    "an 'S' or 'MC', such as 'S-4' or 'MC-2'. Blow counts are shown graphically in a zone on the right side of the "
    "log, with the horizontal blow-count scale displayed at the top of that zone. At each sample depth, a triangle "
    "marks the blow count. Align the triangle marker to the horizontal scale at the top of the zone and record its "
    "inferred value as blow_count, even when no ordinary numeric value is printed. Values at or above 50 blows per "
    "6 inches may instead be printed as a refusal notation, such as '50/4\"'; preserve that notation exactly. Set "
    "blow_count to null only when neither a readable triangle marker nor a printed refusal notation is present. Add "
    "one soil_descriptions item for each described stratum, with its top_depth, "
    "bottom_depth, and description text; strata boundaries are independent of the sample intervals. Preserve "
    "reported values exactly, other than normalizing depths as described. Do not extract client, project, contractor, "
    "dates, personnel, equipment, drilling method, water levels, narrative notes, or other metadata unless it is "
    "one of the fields above. Use null for any unavailable field and an empty list only when the log has no samples "
    "or no soil descriptions."
)
GEOTECH_LAB_REPORT_TEMPLATE_KEY = "geotech_lab_report"
GEOTECH_LAB_REPORT_PROMPT = (
    "This is a single-page geotechnical laboratory report (for example an R-value, resistivity, thermal "
    "conductivity, or compaction report). Extract two things: the report metadata and the one primary results "
    "table. Metadata: set test_type to the reported test name or ASTM/standard designation (for example "
    "'Resistance R-Value and Expansion Pressure - ASTM D2844' or 'Thermal Conductivity - ASTM D5334'); set "
    "location to the boring or sample location (typically labelled with a 'B' or 'P', such as 'PB-1' or 'P-3'); "
    "set sample_number to the reported sample or specimen number; set project_number, project, and report_date "
    "to their reported values; set summary to any single-line headline result (for example "
    "'R-value at 300 psi exudation pressure = 64.1'), or null when none. The primary results table is the main "
    "numeric per-specimen results table (the block of measured test values), not a chart and not a label box. "
    "Set result_columns to that table's column headers in left-to-right order, exactly as printed, joining a "
    "header that wraps onto several lines into one string. Set result_rows to its data rows top-to-bottom, where "
    "each row is a list of cell values aligned one-to-one with result_columns; use null for an empty cell and "
    "keep every value exactly as printed, including units and decimals. Do NOT treat the 'Sample Information', "
    "'Soil Parameters', 'Test Parameters', client/project heading boxes, personnel boxes, remarks, logos, page "
    "headers/footers, or the plotted chart as the results table. Do not invent, reorder, summarize, or calculate "
    "values, and use null for any metadata field that is not shown."
)
GEOTECH_LAB_REPORT_STRUCTURE = {
    "type": "object",
    "properties": {
        "test_type": {"type": ["string", "null"], "description": "Reported test name or ASTM/standard designation"},
        "location": {"type": ["string", "null"], "description": "Boring or sample location, e.g. 'PB-1'"},
        "sample_number": {"type": ["string", "null"], "description": "Reported sample or specimen number"},
        "project_number": {"type": ["string", "null"], "description": "Reported project number"},
        "project": {"type": ["string", "null"], "description": "Reported project name"},
        "report_date": {"type": ["string", "null"], "description": "Reported report or test date, as written"},
        "summary": {"type": ["string", "null"], "description": "Single-line headline result, or null"},
        "result_columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Primary results table column headers, left-to-right, exactly as printed",
        },
        "result_rows": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": ["string", "null"]},
            },
            "description": "Primary results table data rows; each row aligns one-to-one with result_columns",
        },
    },
    "required": ["test_type", "location", "sample_number", "result_columns", "result_rows"],
    "additionalProperties": False,
}
PDF_MARKDOWN_TEMPLATE_KEY = "pdf_markdown"
PDF_MARKDOWN_PROMPT = "Preserve all visible content faithfully, including tables, handwriting, and form fields."
EXTRACTION_TEMPLATES: dict[str, tuple[str, dict[str, object]]] = {
    SOIL_LAB_SUMMARY_TEMPLATE_KEY: (SOIL_LAB_SUMMARY_PROMPT, SOIL_LAB_SUMMARY_STRUCTURE),
    GEOTECH_LAB_REPORT_TEMPLATE_KEY: (GEOTECH_LAB_REPORT_PROMPT, GEOTECH_LAB_REPORT_STRUCTURE),
    BOREHOLE_LOG_TEMPLATE_1_KEY: (BOREHOLE_LOG_TEMPLATE_1_PROMPT, BOREHOLE_LOG_STRUCTURE),
    BOREHOLE_LOG_TEMPLATE_2_KEY: (BOREHOLE_LOG_TEMPLATE_2_PROMPT, BOREHOLE_LOG_STRUCTURE),
}
MODEL_PRICING_PER_MILLION_TOKENS = {
    "gpt-5-mini": {"input": 0.28, "cached_input": 0.03, "output": 2.20},
    "gpt-5.4-mini": {"input": 0.83, "cached_input": 0.09, "output": 4.95},
    "gpt-5.6-luna": {"input": 1.00, "cached_input": 0.10, "output": 6.00},
}
# Batch concurrency: number of documents sent to the provider simultaneously by default.
DEFAULT_CONCURRENCY = 5
MAX_CONCURRENCY = 32
# Retry throttled and transient network failures with exponential backoff between attempts.
MAX_REQUEST_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


class DocumentDropGroupBox(QGroupBox):
    """Group box that accepts external file drops and reports their local paths."""

    paths_dropped = Signal(list)

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class DocumentProcessorWindow(QMainWindow):
    """Desktop batch UI using Microsoft Foundry endpoint credentials."""

    batch_completed = Signal(str, int, int, int, str)
    batch_failed = Signal(str)
    batch_progress = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Document Processor")
        self.setMinimumSize(800, 600)
        self.resize(1180, 760)
        self._documents: list[DocumentItem] = []
        self._structured_prompt_before_markdown: tuple[str, str] | None = None
        self._provider = MicrosoftFoundryProvider()
        self._build_ui()
        self.batch_completed.connect(self._on_batch_completed)
        self.batch_failed.connect(self._on_batch_failed)
        self.batch_progress.connect(self._on_batch_progress)
        self._refresh_provider_state()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QLabel("Document Processor")
        header.setObjectName("title")
        layout.addWidget(header)
        description = QLabel(
            "Process each document in an isolated request. No documents are sent until a provider is configured."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._scrollable_panel(self._build_document_panel()))
        splitter.addWidget(self._scrollable_panel(self._build_configuration_panel()))
        splitter.setSizes([470, 650])
        layout.addWidget(splitter, 1)
        layout.addWidget(self._build_queue_panel())
        self.setStyleSheet(
            "QWidget { font-size: 13px; }"
            "QLabel#title { font-size: 24px; font-weight: 600; }"
            "QGroupBox { font-weight: 600; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }"
        )

    def _scrollable_panel(self, panel: QWidget) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(panel)
        return scroll_area

    def _build_document_panel(self) -> QWidget:
        panel = DocumentDropGroupBox("1. Document set")
        layout = QVBoxLayout(panel)
        supported_formats = QLabel(
            "Supported: PDF. Drag and drop files here or use Add documents. "
            "Pages are rendered locally and sent only after a provider is configured."
        )
        supported_formats.setWordWrap(True)
        layout.addWidget(supported_formats)

        self.document_table = QTableWidget(0, 3)
        self.document_table.setHorizontalHeaderLabels(["Document", "Status", "Details"])
        self.document_table.horizontalHeader().setStretchLastSection(True)
        self.document_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.document_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.document_table, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("Add documents…")
        add_button.clicked.connect(self._select_documents)
        buttons.addWidget(add_button)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected_documents)
        buttons.addWidget(remove_button)
        buttons.addStretch()
        self.document_count_label = QLabel("0 ready")
        buttons.addWidget(self.document_count_label)
        layout.addLayout(buttons)
        panel.paths_dropped.connect(self._add_document_paths)
        return panel

    def _build_configuration_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        prompt_group = QGroupBox("2. Extraction instructions")
        prompt_layout = QVBoxLayout(prompt_group)
        mode_layout = QFormLayout()
        self.contract_template_combo = QComboBox()
        self.contract_template_combo.addItem("Geotechnical Lab Reports (Extract Values)", SOIL_LAB_SUMMARY_TEMPLATE_KEY)
        self.contract_template_combo.addItem("Geotechnical Lab Reports (Extract Tables)", GEOTECH_LAB_REPORT_TEMPLATE_KEY)
        self.contract_template_combo.addItem("Borehole Log Digitization (Standard Template 1)", BOREHOLE_LOG_TEMPLATE_1_KEY)
        self.contract_template_combo.addItem("Borehole Log Digitization (Standard Template 2)", BOREHOLE_LOG_TEMPLATE_2_KEY)
        self.contract_template_combo.addItem("General PDF Text transcription", PDF_MARKDOWN_TEMPLATE_KEY)
        self.contract_template_combo.addItem("Custom (edit task and output structure)", None)
        self.contract_template_combo.currentIndexChanged.connect(self._on_template_selected)
        mode_layout.addRow("Extraction template", self.contract_template_combo)
        prompt_layout.addLayout(mode_layout)
        self.prompt_instruction_label = QLabel("Task instructions (applied independently to every document)")
        prompt_layout.addWidget(self.prompt_instruction_label)
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setPlaceholderText("Describe the information to identify in each document.")
        self.prompt_editor.setMinimumHeight(105)
        prompt_layout.addWidget(self.prompt_editor)
        self.output_structure_label = QLabel("Output structure (editable JSON)")
        prompt_layout.addWidget(self.output_structure_label)
        self.output_structure_editor = QPlainTextEdit()
        self.output_structure_editor.setMinimumHeight(185)
        prompt_layout.addWidget(self.output_structure_editor)
        self._apply_selected_template()
        self._update_template_controls()
        layout.addWidget(prompt_group)

        provider_group = QGroupBox("3. Provider and API configuration")
        provider_layout = QFormLayout(provider_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Microsoft Foundry (primary)", ProviderKind.MICROSOFT_FOUNDRY)
        self.provider_combo.addItem("OpenAI (policy-gated; unavailable)", ProviderKind.OPENAI)
        self.provider_combo.currentIndexChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("Provider", self.provider_combo)
        self.provider_status = QLabel()
        self.provider_status.setWordWrap(True)
        provider_layout.addRow("Readiness", self.provider_status)
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("https://<resource>/.../chat/completions?... ")
        self.endpoint_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("Endpoint", self.endpoint_input)
        self.model_name_combo = QComboBox()
        self.model_name_combo.addItem("gpt-5-mini")
        self.model_name_combo.addItem("gpt-5.4-mini")
        self.model_name_combo.addItem("gpt-5.6-luna")
        self.model_name_combo.setCurrentText("gpt-5.6-luna")
        self.model_name_combo.currentIndexChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("Model name", self.model_name_combo)
        self.api_version_input = QLineEdit()
        self.api_version_input.setPlaceholderText("Optional, e.g. 2025-04-01-preview")
        self.api_version_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("API version", self.api_version_input)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("API key")
        self.api_key_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("API key", self.api_key_input)
        self.provider_note = QLabel("API key, endpoint, and model name are used in memory for this session and are not written to disk.")
        self.provider_note.setWordWrap(True)
        provider_layout.addRow("Configuration", self.provider_note)
        layout.addWidget(provider_group)

        layout.addStretch()
        return panel

    def _apply_selected_template(self) -> None:
        template_key = self.contract_template_combo.currentData()
        if template_key == PDF_MARKDOWN_TEMPLATE_KEY:
            if self._structured_prompt_before_markdown is None:
                self._structured_prompt_before_markdown = (
                    self.prompt_editor.toPlainText(),
                    self.output_structure_editor.toPlainText(),
                )
            self.prompt_editor.setPlainText(PDF_MARKDOWN_PROMPT)
            return
        if template_key is None:
            if self._structured_prompt_before_markdown is not None:
                prompt, output_structure = self._structured_prompt_before_markdown
                self.prompt_editor.setPlainText(prompt)
                self.output_structure_editor.setPlainText(output_structure)
                self._structured_prompt_before_markdown = None
            return
        prompt, output_structure = EXTRACTION_TEMPLATES[template_key]
        self.prompt_editor.setPlainText(prompt)
        self.output_structure_editor.setPlainText(json.dumps(output_structure, indent=2))
        self._structured_prompt_before_markdown = None

    def _on_template_selected(self, _index: int) -> None:
        """Apply named templates immediately when the user selects them."""
        self._apply_selected_template()
        self._update_template_controls()

    def _processing_mode(self) -> ProcessingMode:
        """Choose the internal vision workflow from the selected extraction template."""
        if self.contract_template_combo.currentData() == PDF_MARKDOWN_TEMPLATE_KEY:
            return ProcessingMode.PDF_MARKDOWN
        return ProcessingMode.PDF_IMAGES

    def _update_template_controls(self) -> None:
        """Show structured-extraction controls only for modes that produce JSON results."""
        is_markdown_mode = self._processing_mode() is ProcessingMode.PDF_MARKDOWN
        self.output_structure_editor.setEnabled(not is_markdown_mode)
        self.output_structure_label.setVisible(not is_markdown_mode)
        self.output_structure_editor.setVisible(not is_markdown_mode)
        if is_markdown_mode:
            self.prompt_instruction_label.setText("Additional page-transcription instructions")
        else:
            self.prompt_instruction_label.setText("Task instructions (applied independently to every document)")

    def _build_queue_panel(self) -> QWidget:
        panel = QGroupBox("4. Results queue")
        layout = QVBoxLayout(panel)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("Output folder"))
        self.output_dir_input = QLineEdit(str(_default_output_dir()))
        self.output_dir_input.setPlaceholderText("Folder for JSON, CSV, and Markdown results")
        settings.addWidget(self.output_dir_input, 1)
        browse_output_button = QPushButton("Browse…")
        browse_output_button.clicked.connect(self._select_output_dir)
        settings.addWidget(browse_output_button)
        settings.addSpacing(16)
        settings.addWidget(QLabel("Max concurrent requests"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, MAX_CONCURRENCY)
        self.concurrency_spin.setValue(DEFAULT_CONCURRENCY)
        self.concurrency_spin.setToolTip(
            "How many documents are sent to the provider at the same time. "
            "Lower this if the provider returns rate-limit errors (HTTP 429)."
        )
        settings.addWidget(self.concurrency_spin)
        layout.addLayout(settings)

        actions = QHBoxLayout()
        self.queue_status = QLabel("Draft batch — no provider requests have been made.")
        actions.addWidget(self.queue_status)
        actions.addStretch()
        validate_button = QPushButton("Validate batch")
        validate_button.clicked.connect(self._validate_batch)
        actions.addWidget(validate_button)
        self.process_button = QPushButton("Process batch")
        self.process_button.setEnabled(False)
        self.process_button.setToolTip("Provide endpoint, model name, and API key before processing.")
        self.process_button.clicked.connect(self._start_batch)
        actions.addWidget(self.process_button)
        layout.addLayout(actions)
        self.token_usage_label = QLabel("Batch token usage and estimated cost will appear after processing.")
        layout.addWidget(self.token_usage_label)
        layout.addWidget(QLabel("Progress log"))
        # Live per-document progress so long batches show activity instead of a silent wait.
        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setPlaceholderText("Per-document progress will appear here while the batch runs.")
        self.progress_log.setMaximumHeight(120)
        layout.addWidget(self.progress_log)
        return panel

    def _select_documents(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select documents",
            str(Path.home()),
            "PDF documents (*.pdf);;All files (*.*)",
        )
        self._add_document_paths([Path(path) for path in paths])

    def _select_output_dir(self) -> None:
        current = self.output_dir_input.text().strip()
        start_dir = current or str(_default_output_dir())
        directory = QFileDialog.getExistingDirectory(self, "Select output folder", start_dir)
        if directory:
            self.output_dir_input.setText(directory)

    def _add_document_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        seen_paths = {item.path for item in self._documents if item.status is not DocumentStatus.DUPLICATE}
        self._documents.extend(inspect_document(path, seen_paths) for path in paths)
        self._refresh_document_table()

    def _remove_selected_documents(self) -> None:
        rows = sorted({index.row() for index in self.document_table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self._documents[row]
        self._refresh_document_table()

    def _refresh_document_table(self) -> None:
        self.document_table.setRowCount(len(self._documents))
        for row, item in enumerate(self._documents):
            self.document_table.setItem(row, 0, QTableWidgetItem(item.path.name))
            self.document_table.setItem(row, 1, QTableWidgetItem(item.status.value.replace("_", " ").title()))
            self.document_table.setItem(row, 2, QTableWidgetItem(self._document_detail(item)))
        ready_count = sum(item.is_ready for item in self._documents)
        self.document_count_label.setText(f"{ready_count} ready")

    def _document_detail(self, item: DocumentItem) -> str:
        return item.message or "Ready for vision processing"

    def _refresh_provider_state(self) -> None:
        kind = self.provider_combo.currentData()
        if kind is ProviderKind.OPENAI:
            self.provider_status.setText("Unavailable: OpenAI is disabled until an organization policy explicitly enables it.")
            self.process_button.setEnabled(False)
            return
        self._provider.configure(
            MicrosoftFoundryConfiguration(
                endpoint=self.endpoint_input.text().strip(),
                api_key=self.api_key_input.text().strip(),
                model_id=self.model_name_combo.currentText(),
                api_version=self.api_version_input.text().strip(),
            )
        )
        readiness = self._provider.readiness()
        self.provider_status.setText(readiness.message)
        self.process_button.setEnabled(readiness.ready)

    def _validate_batch(self, show_success: bool = True) -> bool:
        prompt = self.prompt_editor.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Task prompt required", "Enter the prompt to apply to every document.")
            return False
        if not any(item.is_ready for item in self._documents):
            QMessageBox.warning(self, "Documents required", "Add at least one supported document.")
            return False
        mode = self._processing_mode()
        non_pdf_documents = [item.path.name for item in self._documents if item.is_ready and item.extension != ".pdf"]
        if non_pdf_documents:
            QMessageBox.warning(
                self,
                "Vision processing requires PDF documents",
                "Only PDFs can be processed. Remove the following files: " + ", ".join(non_pdf_documents),
            )
            return False
        if mode is ProcessingMode.PDF_MARKDOWN:
            if show_success:
                self.queue_status.setText("Batch is valid. Configure Microsoft Foundry to enable processing.")
            return True
        try:
            output_structure = json.loads(self.output_structure_editor.toPlainText())
        except json.JSONDecodeError as error:
            QMessageBox.warning(self, "Invalid output structure", f"The output structure cannot be parsed: {error.msg}")
            return False
        if output_structure.get("type") != "object":
            QMessageBox.warning(self, "Invalid output structure", "The output structure must define a JSON object.")
            return False
        if show_success:
            self.queue_status.setText("Batch is valid. Configure Microsoft Foundry to enable processing.")
        return True

    def _start_batch(self) -> None:
        if not self._validate_batch(show_success=False):
            return
        if not self._provider.readiness().ready:
            QMessageBox.warning(self, "Provider configuration required", self._provider.readiness().message)
            return
        self.process_button.setEnabled(False)
        mode = self._processing_mode()
        if mode is ProcessingMode.PDF_MARKDOWN:
            self.queue_status.setText("Transcribing each PDF page in an independent Microsoft Foundry request…")
        else:
            self.queue_status.setText("Processing each document in an independent Microsoft Foundry request…")
        self.token_usage_label.setText("Calculating batch token usage…")
        self.progress_log.clear()
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _run_batch(self) -> None:
        prompt = self.prompt_editor.toPlainText().strip()
        mode = self._processing_mode()
        if mode is ProcessingMode.PDF_MARKDOWN:
            output_structure: dict[str, object] = {}
        else:
            try:
                output_structure = json.loads(self.output_structure_editor.toPlainText())
            except json.JSONDecodeError as error:
                self.batch_failed.emit(str(error))
                return
        ready_documents = [item for item in self._documents if item.is_ready]
        total = len(ready_documents)
        if total == 0:
            self.batch_failed.emit("No ready documents to process.")
            return
        max_workers = max(1, min(self.concurrency_spin.value(), total))
        self.batch_progress.emit(f"Starting batch: {total} document(s), up to {max_workers} at a time.")

        # Results are stored by original document index so the output order is stable
        # regardless of which concurrent request finishes first.
        results: list[dict[str, object]] = [{} for _ in range(total)]
        prompt_tokens = 0
        completion_tokens = 0
        cached_prompt_tokens = 0
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self._process_single_document, document, mode, prompt, output_structure): index
                for index, document in enumerate(ready_documents)
            }
            # Token totals accumulate here in this single thread, so no extra locking is required.
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result, usage = future.result()
                except Exception as error:
                    result = {
                        "document": ready_documents[index].path.name,
                        "input_mode": mode.value,
                        "status": "failed",
                        "error": f"Unexpected processing failure ({type(error).__name__}): {error}",
                    }
                    usage = {}
                results[index] = result
                prompt_tokens += _token_count(usage, "prompt_tokens")
                completion_tokens += _token_count(usage, "completion_tokens")
                cached_prompt_tokens += _cached_token_count(usage)
                completed += 1
                remaining = total - completed
                status = str(result.get("status", "processed")).replace("_", " ").title()
                self.batch_progress.emit(
                    f"{status} {completed}/{total}: {ready_documents[index].path.name} ({remaining} remaining)"
                )
        self.batch_completed.emit(
            json.dumps(results, indent=2, ensure_ascii=False),
            prompt_tokens,
            cached_prompt_tokens,
            completion_tokens,
            self.model_name_combo.currentText(),
        )

    def _process_single_document(
        self,
        document: DocumentItem,
        mode: ProcessingMode,
        prompt: str,
        output_structure: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Process one document in a worker thread, retrying only on rate limits.

        Returns the per-document result row and its token usage. A single document's
        failure is captured as a ``failed`` result row so the rest of the batch continues.
        """
        if mode is ProcessingMode.PDF_MARKDOWN:
            return self._process_pdf_markdown_document(document, prompt)

        last_error: Exception | None = None
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                self.batch_progress.emit(
                    f"Processing {document.path.name}: attempt {attempt + 1}/{MAX_REQUEST_ATTEMPTS}."
                )
                response = self._provider.process_pdf_images(render_pdf_pages(document), prompt, output_structure)
                usage = response.pop("usage", {})
                return (
                    {"document": document.path.name, "input_mode": mode.value, "status": "completed", **response},
                    usage if isinstance(usage, dict) else {},
                )
            except (ProviderRateLimitError, ProviderTransientError) as error:
                last_error = error
                if attempt < MAX_REQUEST_ATTEMPTS - 1:
                    retry_delay = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                    self.batch_progress.emit(
                        f"Transient provider failure for {document.path.name}: retrying in {retry_delay:.0f}s."
                    )
                    time.sleep(retry_delay)
            except (PdfRenderingError, ProviderError, json.JSONDecodeError) as error:
                last_error = error
                break
        return (
            {"document": document.path.name, "input_mode": mode.value, "status": "failed", "error": str(last_error)},
            {},
        )

    def _process_pdf_markdown_document(self, document: DocumentItem, prompt: str) -> tuple[dict[str, object], dict[str, object]]:
        """Transcribe one PDF in ordered, isolated page requests and combine its Markdown output."""
        try:
            page_images = render_pdf_pages(document)
        except PdfRenderingError as error:
            return (
                {
                    "document": document.path.name,
                    "input_mode": ProcessingMode.PDF_MARKDOWN.value,
                    "status": "failed",
                    "error": str(error),
                },
                {},
            )

        page_sections: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        cached_prompt_tokens = 0
        page_count = len(page_images)
        for page_number, page_image in enumerate(page_images, start=1):
            response: dict[str, object] | None = None
            last_error: Exception | None = None
            for attempt in range(MAX_REQUEST_ATTEMPTS):
                self.batch_progress.emit(
                    f"Transcribing {document.path.name}: page {page_number}/{page_count}, "
                    f"attempt {attempt + 1}/{MAX_REQUEST_ATTEMPTS}."
                )
                try:
                    candidate = self._provider.process_pdf_page_markdown(page_image, prompt)
                    response = candidate if isinstance(candidate, dict) else None
                    if response is None:
                        raise ProviderError("Microsoft Foundry returned an unexpected page-transcription response.")
                    break
                except (ProviderRateLimitError, ProviderTransientError) as error:
                    last_error = error
                    if attempt < MAX_REQUEST_ATTEMPTS - 1:
                        retry_delay = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                        self.batch_progress.emit(
                            f"Transient provider failure for {document.path.name}, page {page_number}/{page_count}: "
                            f"retrying in {retry_delay:.0f}s."
                        )
                        time.sleep(retry_delay)
                except ProviderError as error:
                    last_error = error
                    break
            if response is None:
                message = str(last_error) if last_error is not None else "Page transcription did not return a response."
                return (
                    {
                        "document": document.path.name,
                        "input_mode": ProcessingMode.PDF_MARKDOWN.value,
                        "status": "failed",
                        "error": f"Page {page_number}: {message}",
                    },
                    _markdown_usage(prompt_tokens, cached_prompt_tokens, completion_tokens),
                )
            markdown = response.get("text")
            if not isinstance(markdown, str):
                return (
                    {
                        "document": document.path.name,
                        "input_mode": ProcessingMode.PDF_MARKDOWN.value,
                        "status": "failed",
                        "error": f"Page {page_number}: Microsoft Foundry returned non-text Markdown content.",
                    },
                    _markdown_usage(prompt_tokens, cached_prompt_tokens, completion_tokens),
                )
            page_sections.append(f"## Page {page_number}\n\n{_remove_markdown_code_fence(markdown).strip()}")
            response_usage = response.get("usage")
            prompt_tokens += _token_count(response_usage, "prompt_tokens")
            completion_tokens += _token_count(response_usage, "completion_tokens")
            cached_prompt_tokens += _cached_token_count(response_usage)

        return (
            {
                "document": document.path.name,
                "input_mode": ProcessingMode.PDF_MARKDOWN.value,
                "status": "completed",
                "text": "\n\n".join(page_sections) + "\n",
            },
            _markdown_usage(prompt_tokens, cached_prompt_tokens, completion_tokens),
        )

    def _on_batch_completed(
        self,
        results: str,
        prompt_tokens: int,
        cached_prompt_tokens: int,
        completion_tokens: int,
        model_name: str,
    ) -> None:
        estimated_cost = _calculate_batch_cost(model_name, prompt_tokens, cached_prompt_tokens, completion_tokens)
        self.token_usage_label.setText(
            f"Batch token usage: input {prompt_tokens:,} | cached input {cached_prompt_tokens:,} | "
            f"output {completion_tokens:,} | total {prompt_tokens + completion_tokens:,} | "
            f"estimated cost ${estimated_cost:.6f}"
        )
        try:
            output_text = self.output_dir_input.text().strip()
            output_dir = Path(output_text) if output_text else None
            output_path = _write_results_file(results, output_dir)
            batch_results = json.loads(results)
            if _is_pdf_markdown_batch(batch_results):
                additional_output_paths = _write_markdown_outputs(batch_results, output_path)
            else:
                additional_output_paths = _write_csv_outputs(results, output_path)
        except (OSError, TypeError, json.JSONDecodeError) as error:
            self.queue_status.setText(f"Batch completed, but results could not be written to disk: {error}")
        else:
            written = ", ".join(str(path) for path in (output_path, *additional_output_paths))
            self.queue_status.setText(f"Batch completed. Results written to {written}")
        self._refresh_provider_state()

    def _on_batch_progress(self, message: str) -> None:
        """Append a timestamped progress line and mirror it in the queue status label."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.progress_log.appendPlainText(f"[{timestamp}] {message}")
        self.queue_status.setText(message)

    def _on_batch_failed(self, error: str) -> None:
        self.queue_status.setText("Batch failed. No provider response was written to disk.")
        self.token_usage_label.setText("Batch token usage unavailable because processing did not complete.")
        self._refresh_provider_state()
        QMessageBox.warning(self, "Batch processing failed", error)


def main() -> None:
    application = QApplication(sys.argv)
    application.setApplicationName("Document Processor")
    window = DocumentProcessorWindow()
    window.show()
    raise SystemExit(application.exec())


def _default_output_dir() -> Path:
    """Default folder for JSON, CSV, and Markdown results, relative to the current working directory."""
    return Path.cwd() / "outputs"


def _write_results_file(results: str, output_dir: Path | None = None) -> Path:
    directory = output_dir or _default_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    output_path = directory / f"document_processor_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(results, encoding="utf-8")
    return output_path


def _remove_markdown_code_fence(markdown: str) -> str:
    """Remove one outer Markdown fence that a provider returned despite the transcription instruction."""
    lines = markdown.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return markdown


def _markdown_usage(prompt_tokens: int, cached_prompt_tokens: int, completion_tokens: int) -> dict[str, object]:
    """Return accumulated page-level usage in the same shape used by the batch cost display."""
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_tokens_details": {"cached_tokens": cached_prompt_tokens},
    }


def _is_pdf_markdown_batch(batch_results: list[object]) -> bool:
    """Identify batches that use the page-by-page PDF Markdown processing mode."""
    return any(
        isinstance(batch_result, dict)
        and batch_result.get("input_mode") == ProcessingMode.PDF_MARKDOWN.value
        for batch_result in batch_results
    )


def _write_markdown_outputs(batch_results: list[object], json_output_path: Path) -> tuple[Path, ...]:
    """Write one consolidated Markdown file for every successfully transcribed PDF in a batch."""
    output_paths: list[Path] = []
    for source_index, batch_result in enumerate(batch_results, start=1):
        if not isinstance(batch_result, dict):
            continue
        if batch_result.get("input_mode") != ProcessingMode.PDF_MARKDOWN.value:
            continue
        if batch_result.get("status") != "completed":
            continue
        markdown = batch_result.get("text")
        if not isinstance(markdown, str):
            continue
        document_name = batch_result.get("document")
        source_stem = Path(document_name).stem if isinstance(document_name, str) and document_name else "document"
        safe_stem = "".join(character if character.isalnum() or character in "-_" else "_" for character in source_stem).strip("._")
        output_path = json_output_path.with_name(f"{json_output_path.stem}_{source_index:03d}_{safe_stem or 'document'}.md")
        output_path.write_text(markdown, encoding="utf-8")
        output_paths.append(output_path)
    return tuple(output_paths)


def _token_count(usage: object, field_name: str) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get(field_name)
    return value if isinstance(value, int) and value >= 0 else 0


def _cached_token_count(usage: object) -> int:
    if not isinstance(usage, dict):
        return 0
    return _token_count(usage.get("prompt_tokens_details"), "cached_tokens")


def _calculate_batch_cost(model_name: str, prompt_tokens: int, cached_prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate batch cost from returned token counts and the selected model's USD rates per million tokens."""
    pricing = MODEL_PRICING_PER_MILLION_TOKENS[model_name]
    cached_tokens = min(cached_prompt_tokens, prompt_tokens)
    uncached_prompt_tokens = prompt_tokens - cached_tokens
    return (
        (uncached_prompt_tokens * pricing["input"])
        + (cached_tokens * pricing["cached_input"])
        + (completion_tokens * pricing["output"])
    ) / 1_000_000


CSV_FIELDNAMES = (
    "document",
    "input_mode",
    "status",
    "test_type",
    "borehole",
    "sample_id",
    "depth",
    "result_name",
    "result_value",
    "result_unit",
)


def _write_csv_file(results: str, json_output_path: Path) -> Path:
    """Flatten completed soil laboratory results into one CSV row per reported result."""
    batch_results = json.loads(results)
    csv_output_path = json_output_path.with_suffix(".csv")
    with csv_output_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for batch_result in batch_results:
            batch_context = {
                "document": batch_result.get("document"),
                "input_mode": batch_result.get("input_mode"),
                "status": batch_result.get("status"),
            }
            extracted_result = json.loads(batch_result.get("text", "{}"))
            result_context = {**batch_context, "test_type": extracted_result.get("test_type")}
            samples = extracted_result.get("samples", [])
            if not samples:
                writer.writerow(result_context)
                continue
            for sample in samples:
                sample_context = {
                    **result_context,
                    "borehole": sample.get("borehole"),
                    "sample_id": sample.get("sample_id"),
                    "depth": sample.get("depth"),
                }
                key_results = sample.get("key_results", [])
                if not key_results:
                    writer.writerow(sample_context)
                    continue
                for key_result in key_results:
                    writer.writerow(
                        {
                            **sample_context,
                            "result_name": key_result.get("name"),
                            "result_value": key_result.get("value"),
                            "result_unit": key_result.get("unit"),
                        }
                    )
    return csv_output_path


BOREHOLE_SAMPLE_CSV_FIELDNAMES = (
    "document",
    "input_mode",
    "status",
    "borehole_id",
    "surface_elevation",
    "depth_unit",
    "sample_id",
    "top_depth",
    "bottom_depth",
    "blow_count",
)
BOREHOLE_SOIL_CSV_FIELDNAMES = (
    "document",
    "input_mode",
    "status",
    "borehole_id",
    "surface_elevation",
    "depth_unit",
    "top_depth",
    "bottom_depth",
    "description",
)


def _write_csv_outputs(results: str, json_output_path: Path) -> tuple[Path, ...]:
    """Write template-appropriate CSV(s): borehole logs split into sample and soil-description files; other templates keep one CSV."""
    batch_results = json.loads(results)
    if _is_borehole_log_batch(batch_results):
        return _write_borehole_log_csv_files(batch_results, json_output_path)
    if _is_geotech_lab_report_batch(batch_results):
        return (_write_geotech_lab_report_csv_file(batch_results, json_output_path),)
    return (_write_csv_file(results, json_output_path),)


def _is_borehole_log_batch(batch_results: list[dict[str, object]]) -> bool:
    """Detect the borehole-log schema by its page-level borehole_id or soil_descriptions fields."""
    for batch_result in batch_results:
        if not isinstance(batch_result, dict):
            continue
        try:
            extracted = json.loads(batch_result.get("text", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(extracted, dict) and ("borehole_id" in extracted or "soil_descriptions" in extracted):
            return True
    return False


GEOTECH_LAB_REPORT_BASE_FIELDNAMES = (
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
)


def _is_geotech_lab_report_batch(batch_results: list[dict[str, object]]) -> bool:
    """Detect the geotechnical lab report schema by its 'result_columns'/'result_rows' fields."""
    for batch_result in batch_results:
        if not isinstance(batch_result, dict):
            continue
        try:
            extracted = json.loads(batch_result.get("text", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(extracted, dict) and ("result_columns" in extracted or "result_rows" in extracted):
            return True
    return False


def _normalize_header(header: str) -> str:
    """Canonical key for a table header: lowercase, punctuation stripped, whitespace collapsed.

    Lets vision-model header variants like 'Exud. Pressure psi' and 'Exud- Pressure psi'
    merge into a single CSV column instead of splitting on punctuation differences.
    """
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in header)
    return " ".join(cleaned.split())


def _write_geotech_lab_report_csv_file(batch_results: list[dict[str, object]], json_output_path: Path) -> Path:
    """Flatten geotechnical lab reports into one CSV row per results-table row.

    Report metadata (test type, location, sample number, etc.) goes into fixed leading columns.
    The results table differs by report type, so the trailing columns are the union of every
    result column seen across the batch, in first-seen order; unused cells stay blank. Headers
    that differ only in punctuation, spacing, or case are merged into the first-seen spelling.
    """
    column_order: list[str] = []
    canonical_to_display: dict[str, str] = {}
    base_canonicals = {_normalize_header(name) for name in GEOTECH_LAB_REPORT_BASE_FIELDNAMES}
    parsed_documents: list[tuple[dict[str, object], dict[str, object]]] = []
    # First pass: parse each document once and collect the union of result columns by canonical key.
    for batch_result in batch_results:
        try:
            extracted = json.loads(batch_result.get("text", "{}"))
        except (TypeError, json.JSONDecodeError):
            extracted = {}
        if not isinstance(extracted, dict):
            extracted = {}
        parsed_documents.append((batch_result, extracted))
        for column in extracted.get("result_columns", []) or []:
            canonical = _normalize_header(column)
            if not canonical or canonical in base_canonicals or canonical in canonical_to_display:
                continue
            canonical_to_display[canonical] = column
            column_order.append(column)
    fieldnames = (*GEOTECH_LAB_REPORT_BASE_FIELDNAMES, *column_order)
    csv_output_path = json_output_path.with_suffix(".csv")
    with csv_output_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for batch_result, extracted in parsed_documents:
            metadata = {
                "document": batch_result.get("document"),
                "input_mode": batch_result.get("input_mode"),
                "status": batch_result.get("status"),
                "test_type": extracted.get("test_type"),
                "location": extracted.get("location"),
                "sample_number": extracted.get("sample_number"),
                "project_number": extracted.get("project_number"),
                "project": extracted.get("project"),
                "report_date": extracted.get("report_date"),
                "summary": extracted.get("summary"),
            }
            columns = extracted.get("result_columns", []) or []
            rows = extracted.get("result_rows", []) or []
            if not rows:
                writer.writerow(metadata)
                continue
            for row_number, row in enumerate(rows, start=1):
                # Route each cell to the merged first-seen header via its canonical key.
                cell_map = {
                    canonical_to_display.get(_normalize_header(column), column): value
                    for column, value in zip(columns, row)
                }
                writer.writerow({**metadata, "row_number": row_number, **cell_map})
    return csv_output_path


def _write_borehole_log_csv_files(batch_results: list[dict[str, object]], json_output_path: Path) -> tuple[Path, Path]:
    """Flatten borehole logs into one sample-per-row CSV and one soil-description-per-row CSV."""
    samples_path = json_output_path.with_name(f"{json_output_path.stem}_samples.csv")
    soil_path = json_output_path.with_name(f"{json_output_path.stem}_soil_descriptions.csv")
    with (
        samples_path.open("w", encoding="utf-8-sig", newline="") as samples_target,
        soil_path.open("w", encoding="utf-8-sig", newline="") as soil_target,
    ):
        samples_writer = csv.DictWriter(samples_target, fieldnames=BOREHOLE_SAMPLE_CSV_FIELDNAMES)
        soil_writer = csv.DictWriter(soil_target, fieldnames=BOREHOLE_SOIL_CSV_FIELDNAMES)
        samples_writer.writeheader()
        soil_writer.writeheader()
        for batch_result in batch_results:
            extracted = json.loads(batch_result.get("text", "{}"))
            log_context = {
                "document": batch_result.get("document"),
                "input_mode": batch_result.get("input_mode"),
                "status": batch_result.get("status"),
                "borehole_id": extracted.get("borehole_id"),
                "surface_elevation": extracted.get("surface_elevation"),
                "depth_unit": extracted.get("depth_unit"),
            }
            samples = extracted.get("samples", [])
            if not samples:
                samples_writer.writerow(log_context)
            for sample in samples:
                samples_writer.writerow(
                    {
                        **log_context,
                        "sample_id": sample.get("sample_id"),
                        "top_depth": sample.get("top_depth"),
                        "bottom_depth": sample.get("bottom_depth"),
                        "blow_count": sample.get("blow_count"),
                    }
                )
            soil_descriptions = extracted.get("soil_descriptions", [])
            if not soil_descriptions:
                soil_writer.writerow(log_context)
            for soil_description in soil_descriptions:
                soil_writer.writerow(
                    {
                        **log_context,
                        "top_depth": soil_description.get("top_depth"),
                        "bottom_depth": soil_description.get("bottom_depth"),
                        "description": soil_description.get("description"),
                    }
                )
    return (samples_path, soil_path)
