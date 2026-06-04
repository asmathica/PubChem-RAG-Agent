"""
Фабрика LLM-моделей с прозрачным fallback chain.

Что делает:
1. По провайдеру (primary) собирает raw ChatModel.
2. Если включён `llm_enable_fallback` — оборачивает его в
   `with_fallbacks(...)` с цепочкой остальных доступных провайдеров.
3. На самом верху — `with_config(max_concurrency=1)`, чтобы агент делал
   не больше одного LLM-call за раз.

Важный порядок:
   primary.with_fallbacks([fallbacks]).with_config(...)
а НЕ
   primary.with_config(...).with_fallbacks([fallbacks])
— во втором случае LangChain видит сверху `RunnableBinding` и тихо
пропускает fallback-путь.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.agent.rate_limiters import (
    get_gemini_rate_limiter,
    get_mistral_rate_limiter,
    get_nvidia_rate_limiter,
    get_openrouter_rate_limiter,
)
from app.config import Settings
from app.errors.models import AppError, ErrorCode
from app.schemas.agent import LLMProviderName

logger = logging.getLogger(__name__)


@dataclass
class ResolvedChatModel:
    """Готовая к использованию LLM + метаданные про provider/model."""
    provider: LLMProviderName
    model_name: str
    instance: BaseChatModel


# ─── raw factory functions ─────────────────────────────────────────────────
# Все возвращают bare ChatModel БЕЗ with_config (чтобы caller мог обернуть
# в with_fallbacks). retries=fallback_max — потому что fallback-слот должен
# advance'нуть к следующему провайдеру быстро, не долбить тот же endpoint.


def _build_openrouter(settings: Settings, *, retries: int) -> ChatOpenAI | None:
    if settings.openrouter_api_key is None:
        return None
    return ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        rate_limiter=get_openrouter_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
        default_headers={
            "HTTP-Referer": "https://github.com/Arina-bear/PubChem-RAG-Agent",
            "X-Title": "PubChem RAG Agent",
        },
    )


def _build_mistral(settings: Settings, *, retries: int) -> ChatOpenAI | None:
    if settings.mistral_api_key is None:
        return None
    return ChatOpenAI(
        model=settings.mistral_model,
        api_key=settings.mistral_api_key.get_secret_value(),
        base_url=settings.mistral_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        rate_limiter=get_mistral_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
    )


def _build_nvidia(settings: Settings, *, retries: int) -> ChatOpenAI | None:
    if settings.nvidia_api_key is None:
        return None
    extra_body: dict[str, object] | None = None
    # GLM-модели на NVIDIA NIM поддерживают "thinking" mode через chat_template_kwargs.
    if "glm" in settings.nvidia_model.lower():
        extra_body = {"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}}
    return ChatOpenAI(
        model=settings.nvidia_model,
        api_key=settings.nvidia_api_key.get_secret_value(),
        base_url=settings.nvidia_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        rate_limiter=get_nvidia_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
        extra_body=extra_body,
    )


def _build_gemini(settings: Settings, *, retries: int) -> ChatGoogleGenerativeAI | None:
    if settings.google_api_key is None:
        return None
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key.get_secret_value(),
        temperature=0,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        rate_limiter=get_gemini_rate_limiter(settings),
    )


def _build_openai(settings: Settings, *, retries: int) -> ChatOpenAI | None:
    if settings.openai_api_key is None:
        return None
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        temperature=0,
        model_kwargs={"parallel_tool_calls": False},
        use_responses_api=False,
    )


def _build_modal_glm(settings: Settings, *, retries: int) -> ChatOpenAI | None:
    if settings.modal_glm_api_key is None:
        return None
    extra_body: dict[str, object] | None = None
    if settings.modal_glm_disable_thinking:
        extra_body = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        model=settings.modal_glm_model,
        api_key=settings.modal_glm_api_key.get_secret_value(),
        base_url=settings.modal_glm_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=retries,
        temperature=0,
        model_kwargs={"parallel_tool_calls": False},
        extra_body=extra_body,
        use_responses_api=False,
    )


def _build_ollama(settings: Settings, *, retries: int) -> ChatOllama:
    """Ollama локальная — ключи не нужны, всегда строится."""
    return ChatOllama(
        model=settings.base_llm_model,
        base_url=settings.ollama_base_url or "http://localhost:11434",
        temperature=0,
        num_predict=1000,
    )


# Реестр всех factory'ев. Используется как для primary, так и для fallback'ов.
_BuilderFn = Callable[..., BaseChatModel | None]
_PROVIDER_BUILDERS: dict[LLMProviderName, _BuilderFn] = {
    "openrouter": _build_openrouter,
    "mistral": _build_mistral,
    "nvidia": _build_nvidia,
    "gemini": _build_gemini,
    "openai": _build_openai,
    "modal_glm": _build_modal_glm,
    "ollama": _build_ollama,
}

# Имя модели для каждого провайдера (для resolve_provider_model_name).
_PROVIDER_MODEL_ATTR: dict[LLMProviderName, str] = {
    "openai": "openai_model",
    "ollama": "base_llm_model",
    "gemini": "gemini_model",
    "openrouter": "openrouter_model",
    "nvidia": "nvidia_model",
    "mistral": "mistral_model",
    "modal_glm": "modal_glm_model",
}

# Порядок fallback-цепочки для каждого primary.
# Идея: ставить рядом архитектурно похожие провайдеры (Mistral → Gemini/Gemma),
# самые тяжёлые (NVIDIA Llama 3.3 70B) — в конец как last resort.
_FALLBACK_ORDER: dict[LLMProviderName, tuple[LLMProviderName, ...]] = {
    "mistral":     ("gemini", "openrouter", "nvidia"),
    "gemini":      ("openrouter", "nvidia"),
    "nvidia":      ("mistral", "openrouter", "gemini"),
    "openrouter":  (),  # один путь
    "openai":      (),
    "modal_glm":   (),
    "ollama":      (),
}


# ─── public API ────────────────────────────────────────────────────────────


def resolve_provider_model_name(
    settings: Settings,
    provider: LLMProviderName | None = None,
) -> tuple[LLMProviderName, str]:
    """Определяет финального провайдера и имя/URL модели для logger/Langfuse.

    Если `provider` явно не передан — берём `settings.llm_default_provider`.
    Raise'ит AppError если provider не из whitelist'а.
    """
    resolved: LLMProviderName = provider or settings.llm_default_provider  # type: ignore[assignment]
    if resolved not in _PROVIDER_MODEL_ATTR:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Неизвестный LLM provider: '{resolved}'.",
            http_status=400,
        )
    return resolved, getattr(settings, _PROVIDER_MODEL_ATTR[resolved])


def build_chat_model(
    settings: Settings,
    provider: LLMProviderName | None = None,
) -> ResolvedChatModel:
    """Собирает primary + fallback chain + with_config в один Runnable.

    1. resolve provider.
    2. собрать primary (полные `max_retries`).
    3. если включён fallback — добавить остальных доступных провайдеров
       (с `llm_fallback_max_retries`, чтобы не залипать на одном).
    4. обернуть в with_config(max_concurrency=1).
    """
    logger.debug("build_chat_model: provider=%s", provider)
    resolved_provider, model_name = resolve_provider_model_name(settings, provider)

    primary_builder = _PROVIDER_BUILDERS[resolved_provider]
    primary = primary_builder(settings, retries=settings.max_retries)
    if primary is None:
        raise AppError(
            ErrorCode.LLM_NOT_CONFIGURED,
            f"Ключ для провайдера '{resolved_provider}' не настроен в .env.",
            http_status=500,
        )

    composed: BaseChatModel = primary
    if settings.llm_enable_fallback:
        composed = _wire_fallbacks(primary, resolved_provider, settings)

    return ResolvedChatModel(
        provider=resolved_provider,
        model_name=model_name,
        instance=composed.with_config(RunnableConfig(max_concurrency=1)),  # type: ignore[return-value]
    )


def _wire_fallbacks(
    primary: BaseChatModel,
    primary_name: LLMProviderName,
    settings: Settings,
) -> BaseChatModel:
    """Оборачивает primary в .with_fallbacks([...]) с цепочкой по _FALLBACK_ORDER.

    Логирует какие именно fallback'и подключены, чтобы оператор видел в логах
    реальную конфигурацию (не все ключи могут быть в .env — тогда часть отвалится).
    """
    candidates = _FALLBACK_ORDER.get(primary_name, ())
    if not candidates:
        return primary

    chain: list[BaseChatModel] = []
    labels: list[str] = []
    retries = settings.llm_fallback_max_retries
    for name in candidates:
        builder = _PROVIDER_BUILDERS.get(name)
        if builder is None:
            continue
        fallback = builder(settings, retries=retries)
        if fallback is None:
            continue  # ключ не настроен — пропускаем
        chain.append(fallback)
        labels.append(f"{name}:{getattr(settings, _PROVIDER_MODEL_ATTR[name])}")

    if not chain:
        logger.info("FAILOVER: %s runs alone (no fallback keys configured)", primary_name)
        return primary

    logger.info("FAILOVER: %s wired with fallbacks → %s", primary_name, ", ".join(labels))
    return primary.with_fallbacks(chain)  # type: ignore[return-value]
