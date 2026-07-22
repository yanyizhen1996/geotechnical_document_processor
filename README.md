# Document Processor

A Windows desktop application for safely processing large document sets one document at a time. The application keeps each document request isolated, validates structured output, and prepares results for review and export.

## Initial implementation

This first vertical slice provides a PySide6 GUI shell with document selection and local preflight for PDF, CSV, XLSX, DOCX, and DOC files; task-prompt and JSON output-contract editors; Microsoft Foundry as the default profile; a policy-gated OpenAI profile; a local request/quota estimate; and a results queue with timestamped JSON output files.

Preflight extracts CSV, XLSX, DOCX, and text-based PDF content locally, retaining page, sheet/row, or paragraph/table provenance in memory. Image-only PDFs are marked for locally configured OCR. Legacy DOC files are detected but remain unavailable until an approved local conversion path is configured.

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
2. For each document, build one independent request with:
	- a system instruction to stay document-bound
	- one user message containing task, schema, and that document's extracted content
3. Submit the request to the configured endpoint with the `api-key` header.
4. Parse `choices[0].message.content` as the model response.
5. Display results in the GUI and write a timestamped JSON file under `outputs/`.

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
