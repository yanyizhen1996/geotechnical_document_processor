# Document Processor

A Windows desktop application for safely processing large document sets one document at a time. The application keeps each document request isolated, validates structured output, and prepares results for review and export.

## Initial implementation

This first vertical slice provides a PySide6 GUI shell for PDF selection; task instructions and an editable JSON output-structure editor; soil laboratory summary, borehole log digitization, geotechnical laboratory report, and page-by-page PDF-to-Markdown templates; Microsoft Foundry as the default profile; a policy-gated OpenAI profile; and a results queue with timestamped output files.

All extraction is vision-based and PDF-only. Structured extraction templates render every page of a PDF into an in-memory PNG and send those images in one isolated vision request for that document. CSV, XLSX, DOCX, DOC, and local PDF-text extraction are not supported.

The **General PDF Text transcription** extraction template uses the same in-memory page renderer, but sends exactly one rendered page to the vision model per request. Each page is asked to faithfully transcribe visible content, including headings, tables, form labels, handwriting, and values, into GitHub-Flavored Markdown. Page requests are ordered within their source PDF and are combined under `## Page N` headings into one Markdown file per successfully completed PDF. The batch retains its timestamped JSON status manifest but does not produce CSV files in this mode. Rate-limit and transient network/read-timeout failures are retried with exponential backoff; a page that still cannot be transcribed fails its source PDF instead of producing an incomplete Markdown file.

Extraction templates (prompts and output structures) live in `src/document_processor/templates.py`. Foundry credentials stay in memory for the running session and are not written to disk.

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
2. Select an extraction template. The selected named template is applied immediately. **Geotechnical Lab Reports (Extract Values)** is the default and populates an editable output structure containing the reported test type and one entry per tested sample with borehole, sample ID, depth, and final result values. **Geotechnical Lab Reports (Extract Tables)** extracts a primary results table. **Borehole Log Digitization (Standard Template 1)** extracts a page-level borehole ID, surface elevation, depth unit, sample intervals, and soil descriptions from conventional B/P-series logs. **Borehole Log Digitization (Standard Template 2)** uses the G-series-borehole and graphical-blow-count conventions. **General PDF Text transcription** performs faithful page-by-page transcription and hides the JSON output structure because it returns Markdown. Select **Custom** to edit the current structured-extraction fields without overwriting them.
3. For each document, build one independent request with:
	- a system instruction to stay document-bound
	- one user message containing task instructions, output structure when applicable, and rendered page images
4. Submit the request to the configured endpoint with the `api-key` header. A structured template sends all rendered pages in one document request; the General PDF Text transcription template sends one independent request for each page. Both require a configured model/deployment that accepts image inputs.
5. Parse `choices[0].message.content` as the model response.
6. Display results and live batch input, cached input, output, total token counts, and estimated cost in the GUI. Write a timestamped JSON manifest for every batch under `outputs/`. Structured extraction templates also write long-format CSV files; General PDF Text transcription instead writes one combined Markdown file for each completed source PDF. Token telemetry and cost estimates are not persisted. The Geotechnical Lab Reports (Extract Values) template writes one CSV with a row per reported test result, repeating its document, test, and sample context. The borehole log templates write two CSVs—one sample per row and one soil description per row—each repeating the document, borehole ID, and surface elevation.

## Live Cost Estimates

The results queue estimates each completed batch from the returned token counts and the selected model's USD price per one million tokens. The configured rates are `gpt-5-mini`: input `$0.28`, cached input `$0.03`, output `$2.20`; `gpt-5.4-mini`: input `$0.83`, cached input `$0.09`, output `$4.95`; and `gpt-5.6-luna`: input `$1.00`, cached input `$0.10`, output `$6.00`. These estimates are shown only for the current application session.

PDF-to-Markdown requests are page-local, so their API cost and latency increase approximately with the number of PDF pages. Structured extraction sends all page images together and is therefore best suited to PDFs that fit within the selected vision model's context and image limits.

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

The GUI does not yet stream very large PDFs one page at a time during rendering, provide database-backed result history, or enable the optional OpenAI path.
