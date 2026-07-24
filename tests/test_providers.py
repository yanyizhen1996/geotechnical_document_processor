import pytest

from document_processor.providers import (
    MAX_ADDITIONAL_CONTEXT_CHARACTERS,
    MicrosoftFoundryProvider,
    MicrosoftFoundryConfiguration,
    ProviderNotReadyError,
    ProviderRequestError,
    _is_api_version_not_supported,
    _is_deployment_not_found,
    _build_foundry_image_payload,
    _build_foundry_payload,
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
        provider.process_document("content", "extract", {"type": "object"})


def test_microsoft_foundry_sends_configured_request_payload(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "choices": [
                {
                    "message": {
                        "content": '{"pi": 12}'
                    }
                }
            ]
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider.process_document("document-only content", "Extract PI", {"type": "object"})

    assert result["text"] == '{"pi": 12}'
    assert calls[0][0].startswith("https://example.foundry.microsoft.com")
    payload = calls[0][1]
    assert payload["model"] == "gpt-4.1-mini"
    assert "temperature" not in payload
    assert len(payload["messages"]) == 2
    assert payload["messages"][1]["role"] == "user"
    assert "Extract PI" in payload["messages"][1]["content"]
    assert "document-only content" in payload["messages"][1]["content"]


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


def test_microsoft_foundry_rejects_oversized_context() -> None:
    provider = MicrosoftFoundryProvider(
        MicrosoftFoundryConfiguration(
            endpoint="https://example.foundry.microsoft.com/chat/completions?api-version=2024-05-01-preview",
            api_key="test-key",
            model_id="gpt-4.1-mini",
        )
    )

    with pytest.raises(ProviderRequestError, match="chunking"):
        provider.process_document("x" * (MAX_ADDITIONAL_CONTEXT_CHARACTERS + 1), "Extract", {"type": "object"})


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


def test_build_payload_omits_model_for_deployment_style_endpoints() -> None:
    payload = _build_foundry_payload(
        "https://example.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-02-01",
        "ignored-model-id",
        "Extract PI",
        {"type": "object"},
        "document text",
    )

    assert "model" not in payload
    assert payload["messages"][1]["role"] == "user"


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
