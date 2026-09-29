"""Named extraction templates: a task prompt plus the JSON output structure the model must return."""

from __future__ import annotations


# --- Geotechnical lab reports: extract per-sample values -------------------------------------------------------

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


# --- Borehole logs: two log layouts share one output structure -------------------------------------------------

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


# --- Geotechnical lab reports: extract metadata plus the primary results table ---------------------------------

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


# --- General PDF transcription: page-by-page Markdown, no output structure -------------------------------------

PDF_MARKDOWN_TEMPLATE_KEY = "pdf_markdown"
PDF_MARKDOWN_PROMPT = "Preserve all visible content faithfully, including tables, handwriting, and form fields."


# Structured (JSON) templates by key; the Markdown template is handled separately as it has no output structure.
EXTRACTION_TEMPLATES: dict[str, tuple[str, dict[str, object]]] = {
    SOIL_LAB_SUMMARY_TEMPLATE_KEY: (SOIL_LAB_SUMMARY_PROMPT, SOIL_LAB_SUMMARY_STRUCTURE),
    GEOTECH_LAB_REPORT_TEMPLATE_KEY: (GEOTECH_LAB_REPORT_PROMPT, GEOTECH_LAB_REPORT_STRUCTURE),
    BOREHOLE_LOG_TEMPLATE_1_KEY: (BOREHOLE_LOG_TEMPLATE_1_PROMPT, BOREHOLE_LOG_STRUCTURE),
    BOREHOLE_LOG_TEMPLATE_2_KEY: (BOREHOLE_LOG_TEMPLATE_2_PROMPT, BOREHOLE_LOG_STRUCTURE),
}
