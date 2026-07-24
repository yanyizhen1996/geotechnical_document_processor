# Document Processor

A Windows desktop application for safely processing large document sets one document at a time. The application keeps each document request isolated, validates structured output, and prepares results for review and export.

## Initial implementation

This first vertical slice provides a PySide6 GUI shell with document selection and local preflight for PDF, CSV, XLSX, DOCX, and DOC files; task instructions and an editable JSON output-structure editor; a soil laboratory summary template; a selectable text or PDF-image input mode; Microsoft Foundry as the default profile; a policy-gated OpenAI profile; and a results queue with timestamped JSON output files.

Text mode extracts CSV, XLSX, DOCX, and text-based PDF content locally, retaining page, sheet/row, or paragraph/table provenance in memory. Image-only PDFs are marked for locally configured OCR in this mode. PDF-image mode renders every page of each PDF into an in-memory PNG and sends those page images in one isolated vision request for that document; it is not available for CSV, XLSX, DOCX, or DOC files. Legacy DOC files are detected but remain unavailable until an approved local conversion path is configured.

It provides core domain, provider, and SQLite repository scaffolding. Foundry credentials stay in memory for the running session and are not written to disk.

## Microsoft Foundry prerequisites

Before enabling processing, confirm with the platform administrator:

1. The approved Microsoft Foundry model endpoint URL.
2. A valid API key for that endpoint.
3. The model ID/deployment name expected by the endpoint.
4. Data-handling policy, concurrency/rate limits, and quota telemetry approach.

Microsoft Foundry is the intended primary provider. OpenAI is an explicit, separate provider option; it must not be used as an automatic fallback.

## Microsoft Foundry chat API integration

The app uses a synchronous chat-completions style request against your configured Foundry endpoint:

1. Configure endpoint URL, API key, and model ID in the GUI.
2. Select the input mode. Use **Extracted text** for non-PDF documents, or **PDF page images** for PDFs that need visual processing.
3. Select an extraction template. **Soil laboratory summary** is the default and populates an editable output structure containing the reported test type and one entry per tested sample with borehole, sample ID, depth, and final result values. Select **Custom** to edit either field without overwriting it.
4. For each document, build one independent request with:
	- a system instruction to stay document-bound
	- one user message containing task instructions, output structure, and that document's extracted content or rendered page images
5. Submit the request to the configured endpoint with the `api-key` header. PDF-image mode requires a configured model/deployment that accepts image inputs.
6. Parse `choices[0].message.content` as the model response.
7. Display results in the GUI and write timestamped JSON and long-format CSV files under `outputs/`. The CSV contains one row per reported test result, repeating its document, test, and sample context.

The initial integration limits each extracted document context to 100,000 characters to avoid long-running requests; document-local chunking will be added later.

## Setup

Create/select a Python 3.11+ environment, then install the application with development tools:

	pip install -e ".[dev]"

Run the desktop application:

	document-processor

Run tests:

	pytest

## Current limitations

The GUI does not yet perform document-local chunking, robust retries, database-backed result history, or the optional OpenAI path. Legacy `.doc` extraction remains unavailable pending an approved local conversion route.
