"""PySide6 application shell for creating a document-processing batch."""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .domain import (
    DocumentItem,
    DocumentStatus,
    ExtractionArtifact,
    ExtractionStatus,
    ProcessingMode,
    ProviderKind,
    inspect_document,
)
from .extraction import ExtractionError, extract_document, render_pdf_pages
from .providers import (
    MicrosoftFoundryConfiguration,
    MicrosoftFoundryProvider,
    ProviderError,
)


DEFAULT_SCHEMA = {
    "type": "object",
    "properties": {
        "pi": {"type": "number", "description": "Plasticity index"},
        "ll": {"type": "number", "description": "Liquid limit"},
        "pl": {"type": "number", "description": "Plastic limit"},
        "source_citation": {"type": "string"},
    },
    "required": ["pi", "ll", "pl", "source_citation"],
    "additionalProperties": False,
}


class DocumentProcessorWindow(QMainWindow):
    """Desktop batch UI using Microsoft Foundry endpoint credentials."""

    batch_completed = Signal(str)
    batch_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Document Processor")
        self.setMinimumSize(800, 600)
        self.resize(1180, 760)
        self._documents: list[DocumentItem] = []
        self._artifacts: dict[Path, ExtractionArtifact] = {}
        self._provider = MicrosoftFoundryProvider()
        self._build_ui()
        self.batch_completed.connect(self._on_batch_completed)
        self.batch_failed.connect(self._on_batch_failed)
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
        panel = QGroupBox("1. Document set")
        layout = QVBoxLayout(panel)
        supported_formats = QLabel(
            "Supported: PDF, CSV, XLSX, DOCX, DOC. Use preflight to inspect content locally; nothing is uploaded."
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
        preflight_button = QPushButton("Preflight selected")
        preflight_button.clicked.connect(self._preflight_selected_documents)
        buttons.addWidget(preflight_button)
        buttons.addStretch()
        self.document_count_label = QLabel("0 ready")
        buttons.addWidget(self.document_count_label)
        layout.addLayout(buttons)
        return panel

    def _build_configuration_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        prompt_group = QGroupBox("2. Task and output contract")
        prompt_layout = QVBoxLayout(prompt_group)
        mode_layout = QFormLayout()
        self.processing_mode_combo = QComboBox()
        self.processing_mode_combo.addItem("Extracted text", ProcessingMode.TEXT)
        self.processing_mode_combo.addItem("PDF page images (vision model)", ProcessingMode.PDF_IMAGES)
        mode_layout.addRow("Document input", self.processing_mode_combo)
        prompt_layout.addLayout(mode_layout)
        prompt_layout.addWidget(QLabel("Task prompt (applied independently to every document)"))
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setPlaceholderText("Example: Extract PI, LL, and PL values. Return the defined JSON object and cite the source page or row.")
        self.prompt_editor.setMinimumHeight(105)
        prompt_layout.addWidget(self.prompt_editor)
        prompt_layout.addWidget(QLabel("JSON output schema"))
        self.schema_editor = QPlainTextEdit(json.dumps(DEFAULT_SCHEMA, indent=2))
        self.schema_editor.setMinimumHeight(185)
        prompt_layout.addWidget(self.schema_editor)
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
        self.model_id_input = QLineEdit()
        self.model_id_input.setPlaceholderText("Model ID")
        self.model_id_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("Model ID", self.model_id_input)
        self.api_version_input = QLineEdit()
        self.api_version_input.setPlaceholderText("Optional, e.g. 2025-04-01-preview")
        self.api_version_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("API version", self.api_version_input)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("API key")
        self.api_key_input.textChanged.connect(self._refresh_provider_state)
        provider_layout.addRow("API key", self.api_key_input)
        self.provider_note = QLabel("API key, endpoint, and model ID are used in memory for this session and are not written to disk.")
        self.provider_note.setWordWrap(True)
        provider_layout.addRow("Configuration", self.provider_note)
        layout.addWidget(provider_group)

        layout.addStretch()
        return panel

    def _build_queue_panel(self) -> QWidget:
        panel = QGroupBox("4. Results queue")
        layout = QVBoxLayout(panel)
        actions = QHBoxLayout()
        self.queue_status = QLabel("Draft batch — no provider requests have been made.")
        actions.addWidget(self.queue_status)
        actions.addStretch()
        validate_button = QPushButton("Validate batch")
        validate_button.clicked.connect(self._validate_batch)
        actions.addWidget(validate_button)
        self.process_button = QPushButton("Process batch")
        self.process_button.setEnabled(False)
        self.process_button.setToolTip("Provide endpoint, model ID, and API key before processing.")
        self.process_button.clicked.connect(self._start_batch)
        actions.addWidget(self.process_button)
        layout.addLayout(actions)
        self.results_editor = QPlainTextEdit()
        self.results_editor.setReadOnly(True)
        self.results_editor.setPlaceholderText("Validated Foundry responses will appear here. Results are not written to disk in this slice.")
        self.results_editor.setMinimumHeight(100)
        layout.addWidget(self.results_editor)
        return panel

    def _select_documents(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select documents",
            str(Path.home()),
            "Documents (*.pdf *.csv *.xlsx *.docx *.doc);;All files (*.*)",
        )
        seen_paths = {item.path for item in self._documents if item.status is not DocumentStatus.DUPLICATE}
        self._documents.extend(inspect_document(path, seen_paths) for path in paths)
        self._refresh_document_table()

    def _remove_selected_documents(self) -> None:
        rows = sorted({index.row() for index in self.document_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._artifacts.pop(self._documents[row].path, None)
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
        artifact = self._artifacts.get(item.path)
        if artifact is None:
            return item.message or "Not preflighted"
        if artifact.warnings:
            return artifact.warnings[0]
        return f"Local preflight complete: {len(artifact.source_locations)} source locations"

    def _preflight_selected_documents(self) -> None:
        rows = sorted({index.row() for index in self.document_table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Select documents", "Select one or more documents to preflight locally.")
            return
        failures: list[str] = []
        for row in rows:
            document = self._documents[row]
            if not document.is_ready:
                continue
            try:
                self._artifacts[document.path] = extract_document(document)
            except ExtractionError as error:
                failures.append(f"{document.path.name}: {error}")
        self._refresh_document_table()
        if failures:
            QMessageBox.warning(self, "Preflight warnings", "\n".join(failures))

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
                model_id=self.model_id_input.text().strip(),
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
        mode = ProcessingMode(self.processing_mode_combo.currentData())
        if mode is ProcessingMode.PDF_IMAGES:
            non_pdf_documents = [item.path.name for item in self._documents if item.is_ready and item.extension != ".pdf"]
            if non_pdf_documents:
                QMessageBox.warning(
                    self,
                    "PDF images require PDF documents",
                    "Image processing is available only for PDFs. Remove or switch the input mode for: "
                    + ", ".join(non_pdf_documents),
                )
                return False
        try:
            schema = json.loads(self.schema_editor.toPlainText())
        except json.JSONDecodeError as error:
            QMessageBox.warning(self, "Invalid output schema", f"The JSON schema cannot be parsed: {error.msg}")
            return False
        if schema.get("type") != "object":
            QMessageBox.warning(self, "Invalid output schema", "The initial output contract must define an object schema.")
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
        self.queue_status.setText("Processing each document in an independent Microsoft Foundry request…")
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _run_batch(self) -> None:
        try:
            prompt = self.prompt_editor.toPlainText().strip()
            schema = json.loads(self.schema_editor.toPlainText())
            mode = ProcessingMode(self.processing_mode_combo.currentData())
            results: list[dict[str, object]] = []
            for document in self._documents:
                if not document.is_ready:
                    continue
                if mode is ProcessingMode.PDF_IMAGES:
                    response = self._provider.process_pdf_images(render_pdf_pages(document), prompt, schema)
                else:
                    artifact = self._artifacts.get(document.path)
                    if artifact is None:
                        artifact = extract_document(document)
                        self._artifacts[document.path] = artifact
                    if artifact.status is not ExtractionStatus.COMPLETE or not artifact.content.strip():
                        results.append({"document": document.path.name, "status": artifact.status.value, "warnings": artifact.warnings})
                        continue
                    response = self._provider.process_document(artifact.content, prompt, schema)
                results.append({"document": document.path.name, "input_mode": mode.value, "status": "completed", **response})
        except (ExtractionError, ProviderError, json.JSONDecodeError) as error:
            self.batch_failed.emit(str(error))
            return
        self.batch_completed.emit(json.dumps(results, indent=2, ensure_ascii=False))

    def _on_batch_completed(self, results: str) -> None:
        self.results_editor.setPlainText(results)
        try:
            output_path = _write_results_file(results)
        except OSError as error:
            self.queue_status.setText(f"Batch completed, but results could not be written to disk: {error}")
        else:
            self.queue_status.setText(f"Batch completed. Results written to {output_path}")
        self._refresh_provider_state()

    def _on_batch_failed(self, error: str) -> None:
        self.queue_status.setText("Batch failed. No provider response was written to disk.")
        self._refresh_provider_state()
        QMessageBox.warning(self, "Batch processing failed", error)


def main() -> None:
    application = QApplication(sys.argv)
    application.setApplicationName("Document Processor")
    window = DocumentProcessorWindow()
    window.show()
    raise SystemExit(application.exec())


def _write_results_file(results: str, output_dir: Path | None = None) -> Path:
    directory = output_dir or Path.cwd() / "outputs"
    directory.mkdir(parents=True, exist_ok=True)
    output_path = directory / f"document_processor_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(results, encoding="utf-8")
    return output_path
