from document_processor.app import _write_results_file


def test_write_results_file_creates_json_output(tmp_path) -> None:
    output_path = _write_results_file('[{"status":"completed"}]', tmp_path)

    assert output_path.parent == tmp_path
    assert output_path.name.startswith("document_processor_results_")
    assert output_path.suffix == ".json"
    assert output_path.read_text(encoding="utf-8") == '[{"status":"completed"}]'
