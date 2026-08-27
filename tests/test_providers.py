import pytest

from document_processor.providers import (
    MicrosoftFoundryProvider,
    MicrosoftFoundryConfiguration,
    ProviderNotReadyError,
    ProviderTransientError,
    _is_api_version_not_supported,
    _is_deployment_not_found,
    _build_foundry_image_payload,
    _build_foundry_markdown_page_payload,
    _normalize_foundry_endpoint,
)


def test_microsoft_foundry_is_not_ready_until_api_configured() -> None:
    provider = MicrosoftFoundryProvider()

    readiness = provider.readiness()

    assert not readiness.ready
    assert "endpoint" in readiness.message.lower()


def test_microsoft_foundry_refuses_processing_until_ready() -> None:
    provider = MicrosoftFoundryProvider()

    with pytest.raises(ProviderNotReadyError):
        provider.process_pdf_images((b"page",), "extract", {"type": "object"})


def test_microsoft_foundry_sends_one_multimodal_request_per_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MicrosoftFoundryProvider(
        MicrosoftFoundryConfiguration(
            endpoint="https://example.foundry.microsoft.com/chat/completions?api-version=2024-05-01-preview",
            api_key="test-key",
            model_id="gpt-4.1-mini",
        )
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, payload))
        return {"choices": [{"message": {"content": '{"pi": 12}'}}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider.process_pdf_images((b"page-one", b"page-two"), "Extract PI", {"type": "object"})

    assert result["text"] == '{"pi": 12}'
    assert len(calls) == 1
    content = calls[0][1]["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert "Extract PI" in content[0]["text"]
    assert [item["image_url"]["url"] for item in content[1:]] == [
        "data:image/png;base64,cGFnZS1vbmU=",
        "data:image/png;base64,cGFnZS10d28=",
    ]


def test_microsoft_foundry_sends_one_markdown_request_per_pdf_page(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MicrosoftFoundryProvider(
        MicrosoftFoundryConfiguration(
            endpoint="https://example.foundry.microsoft.com/chat/completions?api-version=2024-05-01-preview",
            api_key="test-key",
            model_id="gpt-4.1-mini",
        )
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, payload))
        return {
            "choices": [{"message": {"content": "# Page title"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 23, "total_tokens": 123},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider.process_pdf_page_markdown(b"page-one", "Preserve handwritten annotations.")

    assert result == {
        "text": "# Page title",
        "usage": {"prompt_tokens": 100, "completion_tokens": 23, "total_tokens": 123},
    }
    assert len(calls) == 1
    payload = calls[0][1]
    assert payload["model"] == "gpt-4.1-mini"
    content = payload["messages"][1]["content"]
    assert len(content) == 2
    assert content[0]["type"] == "text"
    assert "GitHub-Flavored Markdown" in content[0]["text"]
    assert "Preserve handwritten annotations." in content[0]["text"]
    assert "Return valid JSON only" not in content[0]["text"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64,cGFnZS1vbmU="


def test_microsoft_foundry_marks_read_timeouts_as_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MicrosoftFoundryProvider(
        MicrosoftFoundryConfiguration(
            endpoint="https://example.foundry.microsoft.com/chat/completions?api-version=2024-05-01-preview",
            api_key="test-key",
            model_id="gpt-4.1-mini",
        )
    )

    def timeout_request(*_arguments: object, **_kwargs: object) -> None:
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("document_processor.providers.urlopen", timeout_request)

    with pytest.raises(ProviderTransientError, match="read operation timed out"):
        provider.process_pdf_page_markdown(b"page", "")


def test_microsoft_foundry_marks_connection_resets_as_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MicrosoftFoundryProvider(
        MicrosoftFoundryConfiguration(
            endpoint="https://example.foundry.microsoft.com/chat/completions?api-version=2024-05-01-preview",
            api_key="test-key",
            model_id="gpt-4.1-mini",
        )
    )

    def reset_connection(*_arguments: object, **_kwargs: object) -> None:
        raise ConnectionResetError("The connection was reset by the remote host")

    monkeypatch.setattr("document_processor.providers.urlopen", reset_connection)

    with pytest.raises(ProviderTransientError, match="connection was reset"):
        provider.process_pdf_page_markdown(b"page", "")


def test_normalize_foundry_models_base_appends_chat_path_and_api_version() -> None:
    endpoint = "https://example.services.ai.azure.com/models"

    normalized = _normalize_foundry_endpoint(endpoint)

    assert normalized == "https://example.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"


def test_normalize_openai_base_appends_v1_chat_path() -> None:
    endpoint = "https://example.openai.azure.com"

    normalized = _normalize_foundry_endpoint(endpoint)

    assert normalized == "https://example.openai.azure.com/openai/v1/chat/completions"


def test_normalize_foundry_project_base_appends_chat_path_and_api_version() -> None:
    endpoint = "https://example.services.ai.azure.com/api/projects/project-a"

    normalized = _normalize_foundry_endpoint(endpoint)

    assert normalized == (
        "https://example.services.ai.azure.com/api/projects/project-a/openai/v1/chat/completions"
    )


def test_normalize_foundry_project_chat_preserves_explicit_api_version() -> None:
    endpoint = (
        "https://example.services.ai.azure.com/api/projects/project-a/openai/v1/chat/completions"
    )

    normalized = _normalize_foundry_endpoint(endpoint)

    assert normalized == endpoint


def test_normalize_foundry_project_base_uses_explicit_api_version_argument() -> None:
    endpoint = "https://example.services.ai.azure.com/api/projects/project-a"

    normalized = _normalize_foundry_endpoint(endpoint, "2025-04-01-preview")

    assert normalized.endswith("/api/projects/project-a/openai/v1/chat/completions")


def test_api_version_not_supported_detection_handles_provider_message() -> None:
    detail = '{"error":{"code":"BadRequest","message":"API version not supported"}}'

    assert _is_api_version_not_supported(detail)


def test_deployment_not_found_detection_handles_provider_message() -> None:
    detail = '{"error":{"code":"DeploymentNotFound","message":"The API deployment for this resource does not exist."}}'

    assert _is_deployment_not_found(detail)


def test_build_image_payload_omits_model_for_deployment_style_endpoints() -> None:
    payload = _build_foundry_image_payload(
        "https://example.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-02-01",
        "ignored-model-id",
        "Extract PI",
        {"type": "object"},
        (b"page",),
    )

    assert "model" not in payload
    assert payload["messages"][1]["content"][1]["type"] == "image_url"


def test_build_markdown_page_payload_omits_model_for_deployment_style_endpoints() -> None:
    payload = _build_foundry_markdown_page_payload(
        "https://example.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-02-01",
        "ignored-model-id",
        "",
        b"page",
    )

    assert "model" not in payload
    content = payload["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert "GitHub-Flavored Markdown" in content[0]["text"]
    assert content[1]["type"] == "image_url"
