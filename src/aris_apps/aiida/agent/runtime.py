"""PydanticAI/Gemini adapter for the provider-neutral ARIS agent runtime."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic_ai.settings import ModelSettings

from src.aris_core.agent import (
    AgentModelRejectedError,
    AgentRetryPolicy,
    AgentRunRequest,
    AgentRunResult,
)
from src.aris_core.config import settings
from src.aris_core.logging import log_event


def _error_text_blob(error: Exception) -> str:
    values: list[str] = [str(error)]
    for attr in ("message", "body", "payload", "details", "status", "response"):
        value = getattr(error, attr, None)
        if value is not None:
            values.append(str(value))
    return " ".join(value for value in values if value).lower()


def _is_model_rejected_error(error: Exception) -> bool:
    text = _error_text_blob(error)
    return (
        ("404" in text and "model" in text)
        or "is not found for api version" in text
        or "unsupported model" in text
    )


def _is_retryable_unavailable_error(error: Exception) -> bool:
    text = _error_text_blob(error)
    has_503 = (
        "status_code: 503" in text
        or "status code: 503" in text
        or '"code": 503' in text
        or "'code': 503" in text
        or "http 503" in text
    )
    has_unavailable_hint = (
        "status': 'unavailable'" in text
        or '"status": "unavailable"' in text
        or "currently experiencing high demand" in text
        or "high demand" in text
        or "try again later" in text
        or "temporarily unavailable" in text
    )
    return has_503 and has_unavailable_hint


def _to_pydantic_model_name(name: str) -> str:
    if ":" in name:
        return name
    return f"google-gla:{name}"


def _build_gemini_model(name: str) -> Any:
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValueError("Model name cannot be empty.")
    model_name = cleaned.split(":", 1)[1] if ":" in cleaned else cleaned

    api_version = str(getattr(settings, "GEMINI_API_VERSION", "") or "").strip()
    if not api_version:
        return _to_pydantic_model_name(cleaned)

    try:
        from google.genai import Client as GoogleGenAIClient
        from google.genai.types import HttpOptions
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
    except Exception:  # noqa: BLE001
        logger.warning(
            log_event(
                "aiida.agent_runtime.model_init_api_version_fallback",
                model=model_name,
                api_version=api_version,
            )
        )
        return _to_pydantic_model_name(cleaned)

    api_key = settings.GEMINI_API_KEY
    if api_key == "your-key-here":
        api_key = None

    client = GoogleGenAIClient(
        api_key=api_key,
        vertexai=False,
        http_options=HttpOptions(api_version=api_version),
    )
    return GoogleModel(model_name, provider=GoogleProvider(client=client))


def _build_gemini_model_settings() -> ModelSettings | None:
    max_tokens = int(getattr(settings, "GEMINI_MAX_OUTPUT_TOKENS", 0) or 0)
    if max_tokens <= 0:
        return None
    return ModelSettings(max_tokens=max_tokens)


def _build_retry_policy() -> AgentRetryPolicy:
    retries = int(getattr(settings, "GEMINI_UNAVAILABLE_RETRIES", 2) or 0)
    retries = max(0, min(retries, 8))
    base_backoff = float(
        getattr(settings, "GEMINI_UNAVAILABLE_RETRY_BACKOFF_SECONDS", 2.0) or 2.0
    )
    return AgentRetryPolicy(
        unavailable_retries=retries,
        base_backoff_seconds=max(0.2, min(base_backoff, 60.0)),
    )


class PydanticAIGeminiRuntime:
    """Current runtime adapter. Provider details stop at this boundary."""

    provider = "Gemini"

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self.retry_policy = _build_retry_policy()

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        model_name = str(request.model_name or settings.DEFAULT_MODEL).strip()
        try:
            result = await self._agent.run(
                request.prompt,
                deps=request.deps,
                model=_build_gemini_model(model_name),
                model_settings=_build_gemini_model_settings(),
            )
        except Exception as error:  # noqa: BLE001
            if _is_model_rejected_error(error):
                api_version = str(getattr(settings, "GEMINI_API_VERSION", "unknown"))
                raise AgentModelRejectedError(
                    provider=self.provider,
                    model_name=model_name,
                    detail=(
                        f"API version='{api_version}'. Update ARIS_DEFAULT_MODEL "
                        "(for example gemini-flash-latest) or "
                        "ARIS_GEMINI_API_VERSION and retry."
                    ),
                ) from error
            raise

        output = getattr(result, "output", None)
        if output is None:
            output = getattr(result, "data", None)
        return AgentRunResult(
            output=output,
            provider=self.provider,
            model_name=model_name,
        )

    def is_retryable_unavailable_error(self, error: Exception) -> bool:
        return _is_retryable_unavailable_error(error)


def build_aiida_agent_runtime(agent: Any) -> PydanticAIGeminiRuntime:
    return PydanticAIGeminiRuntime(agent)


# Temporary import compatibility for the legacy chat fallback. These names keep
# provider-specific construction out of the application service while older
# tests and states that expose only ``state.agent`` continue to work.
_to_agent_model_name = _to_pydantic_model_name
_build_agent_model = _build_gemini_model
_build_model_settings = _build_gemini_model_settings
_is_retryable_model_unavailable_error = _is_retryable_unavailable_error


def _get_model_unavailable_retry_policy() -> tuple[int, float]:
    policy = _build_retry_policy()
    return policy.unavailable_retries, policy.base_backoff_seconds


__all__ = [
    "PydanticAIGeminiRuntime",
    "build_aiida_agent_runtime",
]
