"""Provider contracts. Concrete network providers are intentionally not implemented yet."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .domain import ProviderKind


class ProviderError(Exception):
    """Base normalized provider failure."""


class ProviderNotReadyError(ProviderError):
    """The provider is not authorized or configured for a request."""


class ProviderRequestError(ProviderError):
    """The configured provider rejected or could not complete a request."""


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    provider: ProviderKind
    ready: bool
    message: str


@dataclass(frozen=True, slots=True)
class UsageEstimate:
    request_count: int
    estimate_label: str
    details: str


@dataclass(frozen=True, slots=True)
class MicrosoftFoundryConfiguration:
    """API-key configuration for Microsoft Foundry model inference."""

    endpoint: str
    api_key: str
    model_id: str
    api_version: str = ""


MAX_ADDITIONAL_CONTEXT_CHARACTERS = 100_000
DEFAULT_FOUNDRY_API_VERSION = "2024-05-01-preview"
FALLBACK_FOUNDRY_API_VERSIONS = (
    "2025-04-01-preview",
    "2024-05-01-preview",
)


class DocumentProvider(ABC):
    """Provider boundary that keeps document requests stateless and isolated."""

    @abstractmethod
    def readiness(self) -> ProviderReadiness:
        """Return setup readiness without exposing credentials."""

    @abstractmethod
    def estimate(self, document_count: int) -> UsageEstimate:
        """Estimate provider-specific usage before submitting a batch."""

    @abstractmethod
    def process_document(self, content: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Process one document only; no cross-document state is permitted."""


class MicrosoftFoundryProvider(DocumentProvider):
    """Microsoft Foundry chat provider using a configured HTTPS endpoint and API key."""

    def __init__(self, configuration: MicrosoftFoundryConfiguration | None = None) -> None:
        self._configuration = configuration

    def configure(self, configuration: MicrosoftFoundryConfiguration) -> None:
        """Configure endpoint credentials; secrets are retained in memory only."""
        self._configuration = configuration

    def readiness(self) -> ProviderReadiness:
        if self._configuration is None:
            message = "Enter the Microsoft Foundry endpoint URL, API key, and model ID."
        elif not self._configuration.endpoint.strip() or not self._configuration.api_key.strip() or not self._configuration.model_id.strip():
            message = "Endpoint URL, API key, and model ID are all required."
        elif not self._configuration.endpoint.strip().lower().startswith("https://"):
            message = "Endpoint must be an HTTPS URL."
        else:
            message = "Ready. Each document will be sent in an independent Foundry request."
        return ProviderReadiness(
            ProviderKind.MICROSOFT_FOUNDRY,
            self._configuration is not None
            and bool(self._configuration.endpoint.strip())
            and self._configuration.endpoint.strip().lower().startswith("https://")
            and bool(self._configuration.api_key.strip())
            and bool(self._configuration.model_id.strip()),
            message,
        )

    def estimate(self, document_count: int) -> UsageEstimate:
        return UsageEstimate(
            document_count,
            "Estimated Microsoft Foundry requests",
            "Cost depends on the configured model pricing and token usage telemetry.",
        )

    def process_document(self, content: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.readiness().ready:
            raise ProviderNotReadyError(self.readiness().message)
        if len(content) > MAX_ADDITIONAL_CONTEXT_CHARACTERS:
            raise ProviderRequestError(
                "Document extraction exceeds the current 100,000-character request limit; document-local chunking is not implemented yet."
            )
        assert self._configuration is not None

        response = self._post_json(
            self._configuration.endpoint,
            _build_foundry_payload(self._configuration.endpoint, self._configuration.model_id, prompt, schema, content),
        )
        return {
            "text": _extract_foundry_text(response),
            "usage": _extract_usage(response),
        }

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._configuration is not None
        normalized_endpoint = _normalize_foundry_endpoint(endpoint, self._configuration.api_version.strip())
        attempted_versions: list[str] = []
        request = Request(
            normalized_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": self._configuration.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if _is_deployment_not_found(detail):
                raise ProviderRequestError(
                    "Microsoft Foundry could not find the configured deployment/model. "
                    f"Resolved endpoint: {normalized_endpoint}. "
                    f"Configured Model ID: {self._configuration.model_id}. "
                    "In Foundry, this field must be the exact deployment name available to this project/resource, "
                    "not the project name, endpoint name, or generic model family name unless that is also the deployment name. "
                    "If you just created the deployment, wait a few minutes and retry. "
                    f"Provider response: {detail}"
                ) from error
            if error.code == 400 and _is_api_version_not_supported(detail):
                retried = _retry_foundry_versions(
                    normalized_endpoint,
                    payload,
                    self._configuration.api_key,
                    attempted_versions,
                )
                if retried is not None:
                    return retried
                attempted = ", ".join(attempted_versions) if attempted_versions else "none"
                raise ProviderRequestError(
                    "Microsoft Foundry rejected api-version. "
                    f"Resolved endpoint: {normalized_endpoint}. Tried fallback api-versions: {attempted}. "
                    "Set API version explicitly in the GUI to the value shown on your Foundry endpoint page. "
                    f"Provider response: {detail}"
                ) from error
            if error.code == 404:
                raise ProviderRequestError(
                    "Microsoft Foundry returned 404 Resource not found. "
                    f"Resolved endpoint: {normalized_endpoint}. "
                    "Check endpoint path, deployment/model availability, and api-version. "
                    "For Azure AI Foundry model inference, use a base endpoint like "
                    "https://<resource>.services.ai.azure.com/models (the app appends /chat/completions and api-version). "
                    "For Azure OpenAI-style routes, verify the deployment path and api-version in the URL. "
                    f"Provider response: {detail}"
                ) from error
            raise ProviderRequestError(f"Microsoft Foundry request failed ({error.code}): {detail}") from error
        except (URLError, TimeoutError) as error:
            raise ProviderRequestError(f"Could not reach Microsoft Foundry endpoint: {error}") from error
        except json.JSONDecodeError as error:
            raise ProviderRequestError("Microsoft Foundry endpoint returned a non-JSON response.") from error
        if not isinstance(data, dict):
            raise ProviderRequestError("Microsoft Foundry endpoint returned an unexpected response shape.")
        return data


def _normalize_foundry_endpoint(endpoint: str, api_version: str = "") -> str:
    """Normalize common Foundry endpoint inputs to a concrete chat-completions URL."""
    parsed = urlparse(endpoint.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ProviderNotReadyError("Endpoint must be a full HTTPS URL.")
    if parsed.scheme.lower() != "https":
        raise ProviderNotReadyError("Endpoint must use HTTPS.")

    path = parsed.path.rstrip("/")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    lower_path = path.lower()
    host = parsed.netloc.lower()

    if not path:
        if "services.ai.azure.com" in host:
            path = "/models/chat/completions"
        elif ".openai.azure.com" in host:
            path = "/openai/v1/chat/completions"
        else:
            path = "/chat/completions"
    elif "/api/projects/" in lower_path:
        if "/openai/v1/" not in lower_path:
            path = f"{path}/openai/v1/chat/completions"
        elif lower_path.endswith("/openai/v1"):
            path = f"{path}/chat/completions"
    elif lower_path.endswith("/models"):
        path = f"{path}/chat/completions"
    elif lower_path.endswith("/openai"):
        path = f"{path}/v1/chat/completions"
    elif lower_path.endswith("/openai/v1"):
        path = f"{path}/chat/completions"

    if path.lower().endswith("/models/chat/completions") and "api-version" not in query:
        query["api-version"] = api_version or DEFAULT_FOUNDRY_API_VERSION

    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, urlencode(query), parsed.fragment))


def _build_foundry_payload(endpoint: str, model_id: str, prompt: str, schema: dict[str, Any], content: str) -> dict[str, Any]:
    """Build payloads compatible with Foundry and Azure OpenAI-style endpoints."""
    payload: dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": "Use only the provided document content in this request. Do not rely on prior turns.",
            },
            {"role": "user", "content": _build_document_prompt(prompt, schema, content)},
        ],
    }
    # Deployment-style Azure OpenAI endpoints encode model/deployment in the URL.
    if "/openai/deployments/" not in endpoint.lower():
        payload["model"] = model_id
    return payload


def _build_document_prompt(prompt: str, schema: dict[str, Any], content: str) -> str:
    """Build a self-contained, document-specific request without earlier results."""
    return (
        f"Task: {prompt}\n\n"
        "Return valid JSON only, matching this JSON Schema exactly:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Document content:\n"
        f"{content}"
    )


def _extract_foundry_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    raise ProviderRequestError("Microsoft Foundry response did not include choices[0].message.content.")


def _extract_usage(response: dict[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    return usage if isinstance(usage, dict) else {}


def _is_api_version_not_supported(detail: str) -> bool:
    lowered = detail.lower()
    return "api version not supported" in lowered or "api-version not supported" in lowered


def _is_deployment_not_found(detail: str) -> bool:
    lowered = detail.lower()
    return "deploymentnotfound" in lowered or "api deployment for this resource does not exist" in lowered


def _replace_api_version(endpoint: str, api_version: str) -> str:
    parsed = urlparse(endpoint)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["api-version"] = api_version
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))


def _retry_foundry_versions(
    normalized_endpoint: str,
    payload: dict[str, Any],
    api_key: str,
    attempted_versions: list[str],
) -> dict[str, Any] | None:
    parsed = urlparse(normalized_endpoint)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current = query.get("api-version", "")
    for version in FALLBACK_FOUNDRY_API_VERSIONS:
        if not version or version == current:
            continue
        candidate = _replace_api_version(normalized_endpoint, version)
        attempted_versions.append(version)
        request = Request(
            candidate,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict):
                return data
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code != 400 or not _is_api_version_not_supported(detail):
                raise ProviderRequestError(f"Microsoft Foundry request failed ({error.code}): {detail}") from error
        except (URLError, TimeoutError) as error:
            raise ProviderRequestError(f"Could not reach Microsoft Foundry endpoint: {error}") from error
        except json.JSONDecodeError as error:
            raise ProviderRequestError("Microsoft Foundry endpoint returned a non-JSON response.") from error
    return None
