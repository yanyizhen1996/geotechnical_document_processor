# Document Processor

A Windows desktop application for safely processing large document sets one document at a time. The application keeps each document request isolated, validates structured output, and prepares results for review and export.

## Initial implementation

This first vertical slice provides a PySide6 GUI shell with document selection and local preflight for PDF, CSV, XLSX, DOCX, and DOC files; task instructions and an editable JSON output-structure editor; soil laboratory summary and borehole log digitization templates; a selectable text or PDF-image input mode; Microsoft Foundry as the default profile; a policy-gated OpenAI profile; and a results queue with timestamped JSON output files.

Text mode extracts CSV, XLSX, DOCX, and text-based PDF content locally, retaining page, sheet/row, or paragraph/table provenance in memory. Image-only PDFs are marked for locally configured OCR in this mode. PDF-image mode renders every page of each PDF into an in-memory PNG and sends those page images in one isolated vision request for that document; it is not available for CSV, XLSX, DOCX, or DOC files. Legacy DOC files are detected but remain unavailable until an approved local conversion path is configured.

It provides core domain, provider, and SQLite repository scaffolding. Foundry credentials stay in memory for the running session and are not written to disk.

## Microsoft Foundry prerequisites

Before enabling processing, confirm with the platform administrator:

1. The approved Microsoft Foundry model endpoint URL.
2. A valid API key for that endpoint.
3. A supported model name: `gpt-5-mini`, `gpt-5.4-mini`, or `gpt-5.6-luna`.
4. Data-handling policy, concurrency/rate limits, and quota telemetry approach.

Microsoft Foundry is the intended primary provider. OpenAI is an explicit, separate provider option; it must not be used as an automatic fallback.

## Microsoft Foundry chat API integration

The app uses a synchronous chat-completions style request against your configured Foundry endpoint:

1. Configure endpoint URL, API key, and model name in the GUI.
2. Select the input mode. Use **Extracted text** for non-PDF documents, or **PDF page images** for PDFs that need visual processing.
3. Select an extraction template. **Soil laboratory summary** is the default and populates an editable output structure containing the reported test type and one entry per tested sample with borehole, sample ID, depth, and final result values. **Borehole log digitization** extracts a page-level borehole ID, surface elevation, and depth unit; one entry per sampled interval (sample ID, plain-number top/bottom depth, and blow count as reported text); and one entry per described soil stratum. Select **Custom** to edit either field without overwriting it.
4. For each document, build one independent request with:
	- a system instruction to stay document-bound
	- one user message containing task instructions, output structure, and that document's extracted content or rendered page images
5. Submit the request to the configured endpoint with the `api-key` header. PDF-image mode requires a configured model/deployment that accepts image inputs.
6. Parse `choices[0].message.content` as the model response.
7. Display results and live batch input, cached input, output, total token counts, and estimated cost in the GUI. Write timestamped JSON and long-format CSV files under `outputs/`; token telemetry and cost estimates are not persisted. The soil laboratory summary template writes one CSV with a row per reported test result, repeating its document, test, and sample context. The borehole log template writes two CSVs—one sample per row and one soil description per row—each repeating the document, borehole ID, and surface elevation.

## Live Cost Estimates

The results queue estimates each completed batch from the returned token counts and the selected model's USD price per one million tokens. The configured rates are `gpt-5-mini`: input `$0.28`, cached input `$0.03`, output `$2.20`; `gpt-5.4-mini`: input `$0.83`, cached input `$0.09`, output `$4.95`; and `gpt-5.6-luna`: input `$1.00`, cached input `$0.10`, output `$6.00`. These estimates are shown only for the current application session.

The initial integration limits each extracted document context to 100,000 characters to avoid long-running requests; document-local chunking will be added later.

## Quick start (recommended for new machines)

Make sure Python 3.11 or newer is installed, then double-click `run.bat`.
On first run it automatically creates a local `.venv`, installs all required
packages, and launches the app. Every later run just starts the app.

## Setup (manual)

Create/select a Python 3.11+ environment, then install the runtime packages:

	pip install -r requirements.txt

Run the app directly (no package install needed):

	python app.py

Alternatively, install the application as a package with development tools:

	pip install -e ".[dev]"

Run the desktop application:

	document-processor

Run tests:

	pytest

## Current limitations

The GUI does not yet perform document-local chunking, robust retries, database-backed result history, or the optional OpenAI path. Legacy `.doc` extraction remains unavailable pending an approved local conversion route.
