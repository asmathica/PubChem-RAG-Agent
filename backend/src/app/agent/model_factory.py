from dataclasses import dataclass
import logging

from langchain_openai import ChatOpenAI
#from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from app.agent.rate_limiters import (
    get_gemini_rate_limiter,
    get_mistral_rate_limiter,
    get_nvidia_rate_limiter,
    get_openrouter_rate_limiter,
)
from app.config import Settings
from app.errors.models import AppError, ErrorCode
from app.schemas.agent import LLMProviderName
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def _build_openrouter_chat_model(settings: Settings) -> ChatOpenAI | None:
    """Raw OpenRouter ChatOpenAI client (no `with_config` — see docstring of
    _build_nvidia_chat_model for the reason).

    Uses `llm_fallback_max_retries` instead of `max_retries`: when this model
    is hit it's already because the primary failed N times, so retrying the
    next provider another N times wastes user time. 1 try is enough to
    decide whether to advance to the next fallback.
    """
    if settings.openrouter_api_key is None:
        return None
    return ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_fallback_max_retries,
        rate_limiter=get_openrouter_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
        default_headers={
            "HTTP-Referer": "https://github.com/Arina-bear/PubChem-RAG-Agent",
            "X-Title": "PubChem RAG Agent",
        },
    )


def _build_mistral_chat_model(settings: Settings) -> ChatOpenAI | None:
    """Raw Mistral La Plateforme ChatOpenAI client when the API key is
    configured.

    Returns the bare ChatOpenAI (NOT wrapped in `with_config`) so callers
    can compose it inside a fallback chain (see _build_nvidia_chat_model
    for the wrapping-order rationale). Uses `llm_fallback_max_retries`
    because this builder is only ever called from a fallback slot — when
    Mistral is the explicit primary, the direct-provider branch wraps
    the same factory.
    """
    if settings.mistral_api_key is None:
        return None
    return ChatOpenAI(
        model=settings.mistral_model,
        api_key=settings.mistral_api_key.get_secret_value(),
        base_url=settings.mistral_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_fallback_max_retries,
        rate_limiter=get_mistral_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
    )


def _build_nvidia_chat_model(settings: Settings) -> ChatOpenAI | None:
    """Raw NVIDIA NIM ChatOpenAI client when the API key is configured.

    Returns the bare ChatOpenAI (NOT wrapped in `with_config`) so callers
    can compose it with `with_fallbacks(...)` first and apply `with_config`
    to the OUTSIDE of the fallback chain. Reversing the order makes
    LangChain see a `RunnableBinding` at the top, which silently skips
    the fallback path on errors.

    Uses `llm_fallback_max_retries` (same reason as
    `_build_openrouter_chat_model`).
    """
    if settings.nvidia_api_key is None:
        return None
    extra_body: dict[str, object] | None = None
    # GLM models on NVIDIA NIM expose a "thinking" mode via chat_template_kwargs.
    # Enabling it makes the model emit reasoning_content blocks alongside the
    # normal content; LangChain agents handle that fine and the extra detail
    # helps with multi-step PubChem lookups.
    if "glm" in settings.nvidia_model.lower():
        extra_body = {"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}}
    return ChatOpenAI(
        model=settings.nvidia_model,
        api_key=settings.nvidia_api_key.get_secret_value(),
        base_url=settings.nvidia_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_fallback_max_retries,
        rate_limiter=get_nvidia_rate_limiter(settings),
        temperature=0,
        use_responses_api=False,
        extra_body=extra_body,
    )

@dataclass
class ResolvedChatModel:
    provider: LLMProviderName
    model_name: str
    instance: ChatOpenAI


def resolve_provider_model_name(settings: Settings, provider: LLMProviderName | None = None) -> tuple[LLMProviderName, str]:
    """Определяет итогового провайдера и имя модели для инициализации LLM.
    Функция реализует логику приоритетов: если провайдер передан явно, используется он; 
    в противном случае берется провайдер по умолчанию из настроек. На основе выбранного 
    провайдера извлекается соответствующее имя модели или базовый URL.
    Args:
        settings (Settings): Объект конфигурации приложения, содержащий ключи и имена моделей.
        provider (LLMProviderName | None, optional): Желаемый провайдер. Если None, 
            используется `settings.llm_default_provider`.
    Returns:
        tuple[LLMProviderName, str]: Кортеж, состоящий из:
            1. Итогового имени провайдера (например, "openai", "ollama").
            2. Технического идентификатора модели или URL (например, "gpt-4o" или адрес сервера).

    """
    resolved_provider = provider or settings.llm_default_provider

    if resolved_provider not in {"openai", "modal_glm", "ollama", "gemini", "openrouter", "nvidia", "mistral"}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Неизвестный LLM provider: '{resolved_provider}'.",
            http_status=400,
        )
    if resolved_provider == "openai":
        return "openai", settings.openai_model

    if resolved_provider == "ollama":
        return "ollama", settings.ollama_base_url

    if resolved_provider == "gemini":
        return "gemini", settings.gemini_model

    if resolved_provider == "openrouter":
        return "openrouter", settings.openrouter_model

    if resolved_provider == "nvidia":
        return "nvidia", settings.nvidia_model

    if resolved_provider == "mistral":
        return "mistral", settings.mistral_model

    return "modal_glm", settings.modal_glm_model


def build_chat_model(settings: Settings, provider: LLMProviderName | None = None) -> ResolvedChatModel:
    """
    Функция выполняет роль фабрики: она определяет провайдера, проверяет наличие необходимых 
    API-ключей и создает объект ChatModel с предустановленными параметрами (температура, 
    таймауты, лимиты конкурентности). Поддерживает интеграцию с OpenAI, Ollama и кастомными 
    сервисами через интерфейс ChatOpenAI (например, Modal GLM).

    Args:
        settings (Settings): Глобальный объект конфигурации приложения.
        provider (LLMProviderName | None, optional): Принудительный выбор провайдера. 
            Если не указан, используется значение по умолчанию из настроек.

    Returns:
        ResolvedChatModel: Контейнер, содержащий:
            - Имя провайдера.
            - Техническое имя модели.
            - Настроенный инстанс модели (Runnable), готовый к вызову в LangChain.
    """
    print("!!! ШАГ 1: Входим в build_chat_model")
    print(f"!!! ШАГ 2: Провайдер {provider}")
   # print(f"DEBUG: API Key exists: {settings.modal_glm_api_key is not None}")
    resolved_provider, model_name = resolve_provider_model_name(settings, provider)
    model_kwargs = {"parallel_tool_calls": False}

#логика выбора провайдера
    if resolved_provider == "openai":
        if settings.openai_api_key is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "OPENAI_API_KEY не настроен.",
                http_status=500,
            )
        instance = ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            max_retries=settings.max_retries,
            temperature=0,
            model_kwargs=model_kwargs,
            use_responses_api=False,
        )
        return ResolvedChatModel(provider="openai", 
                                 model_name=model_name, 
                                 instance=instance.with_config(RunnableConfig(max_concurrency=1)))
    if resolved_provider == "ollama":
        ollama_url = settings.ollama_base_url or "http://localhost:11434"
        instance = ChatOllama(
            model="gemma3:4b",  # например, "gemma3:4b"
            base_url=ollama_url,
            temperature=0,
            num_predict=1000,
        )

        return ResolvedChatModel(
            provider="ollama",
            model_name="gemma3:4b",
            instance=instance.with_config(RunnableConfig(max_concurrency=1))
        )

    if resolved_provider == "gemini":
        if settings.google_api_key is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "GOOGLE_API_KEY не настроен.",
                http_status=500,
            )
        # Build the raw chat models WITHOUT `with_config` first. Compose
        # `with_fallbacks` INSIDE, then apply `with_config` to the combined
        # runnable. Reversing the order makes LangChain see a RunnableBinding
        # at the top, which silently skips the fallback path on errors.
        primary = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key.get_secret_value(),
            temperature=0,
            timeout=settings.llm_request_timeout_seconds,
            max_retries=settings.max_retries,
            rate_limiter=get_gemini_rate_limiter(settings),
        )

        # Прозрачный auto-failover: если Gemini вернул любую ошибку
        # (FAILED_PRECONDITION region, RESOURCE_EXHAUSTED quota, 5xx и т.п.) —
        # LangChain сам повторяет запрос через цепочку OpenRouter → NVIDIA.
        # Никакого state, никакого ручного try/except в верхних слоях.
        # См. docs: https://python.langchain.com/docs/how_to/fallbacks/
        composed: object = primary
        if settings.llm_enable_fallback:
            fallback_chain: list[object] = []
            openrouter_fallback = _build_openrouter_chat_model(settings)
            if openrouter_fallback is not None:
                fallback_chain.append(openrouter_fallback)
            nvidia_fallback = _build_nvidia_chat_model(settings)
            if nvidia_fallback is not None:
                fallback_chain.append(nvidia_fallback)
            if fallback_chain:
                composed = primary.with_fallbacks(fallback_chain)
                fallback_models = []
                if openrouter_fallback is not None:
                    fallback_models.append(f"openrouter:{settings.openrouter_model}")
                if nvidia_fallback is not None:
                    fallback_models.append(f"nvidia:{settings.nvidia_model}")
                msg = f"!!! FAILOVER: Gemini chat model wired with fallbacks → {', '.join(fallback_models)}"
                print(msg)  # also goes to uvicorn stdout
                logger.info(msg)
            else:
                msg = "!!! FAILOVER: no fallbacks configured — Gemini runs alone."
                print(msg)
                logger.info(msg)

        instance = composed.with_config(RunnableConfig(max_concurrency=1))

        return ResolvedChatModel(
            provider="gemini",
            model_name=model_name,
            instance=instance,
        )

    if resolved_provider == "openrouter":
        raw = _build_openrouter_chat_model(settings)
        if raw is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "OPENROUTER_API_KEY не настроен.",
                http_status=500,
            )
        return ResolvedChatModel(
            provider="openrouter",
            model_name=model_name,
            instance=raw.with_config(RunnableConfig(max_concurrency=1)),
        )

    if resolved_provider == "nvidia":
        raw = _build_nvidia_chat_model(settings)
        if raw is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "NVIDIA_API_KEY не настроен.",
                http_status=500,
            )
        # Symmetric failover. Order matches the user-requested cascade
        # NVIDIA NIM → Mistral → OpenRouter → Gemini, sized by free-tier
        # generosity: Mistral has the most headroom (60 RPM, 1B/month),
        # OpenRouter is the smallest pool, Gemini is the last resort.
        composed: object = raw
        if settings.llm_enable_fallback:
            fallback_chain: list[object] = []
            mistral_fallback = _build_mistral_chat_model(settings)
            if mistral_fallback is not None:
                fallback_chain.append(mistral_fallback)
            openrouter_fallback = _build_openrouter_chat_model(settings)
            if openrouter_fallback is not None:
                fallback_chain.append(openrouter_fallback)
            if settings.google_api_key is not None:
                gemini_fallback = ChatGoogleGenerativeAI(
                    model=settings.gemini_model,
                    google_api_key=settings.google_api_key.get_secret_value(),
                    temperature=0,
                    timeout=settings.llm_request_timeout_seconds,
                    max_retries=settings.llm_fallback_max_retries,
                    rate_limiter=get_gemini_rate_limiter(settings),
                )
                fallback_chain.append(gemini_fallback)
            if fallback_chain:
                composed = raw.with_fallbacks(fallback_chain)
                fallback_models = []
                if mistral_fallback is not None:
                    fallback_models.append(f"mistral:{settings.mistral_model}")
                if openrouter_fallback is not None:
                    fallback_models.append(f"openrouter:{settings.openrouter_model}")
                if settings.google_api_key is not None:
                    fallback_models.append(f"gemini:{settings.gemini_model}")
                msg = f"!!! FAILOVER: NVIDIA chat model wired with fallbacks → {', '.join(fallback_models)}"
                print(msg)
                logger.info(msg)
        return ResolvedChatModel(
            provider="nvidia",
            model_name=model_name,
            instance=composed.with_config(RunnableConfig(max_concurrency=1)),
        )

    if resolved_provider == "mistral":
        raw = _build_mistral_chat_model(settings)
        if raw is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "MISTRAL_API_KEY не настроен.",
                http_status=500,
            )
        # Mistral-primary failover (explicit user-requested order):
        #   Mistral → Google Gemma → OpenRouter Gemma → NVIDIA Llama
        # Idea: keep the two Google/Gemma-flavoured fallbacks adjacent so a
        # Mistral hiccup tries the closest-in-architecture replacement
        # first; NVIDIA Llama 3.3 70B is the heaviest and slowest option,
        # so it sits last.
        composed: object = raw
        if settings.llm_enable_fallback:
            fallback_chain: list[object] = []
            gemini_fallback = None
            if settings.google_api_key is not None:
                gemini_fallback = ChatGoogleGenerativeAI(
                    model=settings.gemini_model,
                    google_api_key=settings.google_api_key.get_secret_value(),
                    temperature=0,
                    timeout=settings.llm_request_timeout_seconds,
                    max_retries=settings.llm_fallback_max_retries,
                    rate_limiter=get_gemini_rate_limiter(settings),
                )
                fallback_chain.append(gemini_fallback)
            openrouter_fallback = _build_openrouter_chat_model(settings)
            if openrouter_fallback is not None:
                fallback_chain.append(openrouter_fallback)
            nvidia_fallback = _build_nvidia_chat_model(settings)
            if nvidia_fallback is not None:
                fallback_chain.append(nvidia_fallback)
            if fallback_chain:
                composed = raw.with_fallbacks(fallback_chain)
                fallback_models = []
                if gemini_fallback is not None:
                    fallback_models.append(f"gemini:{settings.gemini_model}")
                if openrouter_fallback is not None:
                    fallback_models.append(f"openrouter:{settings.openrouter_model}")
                if nvidia_fallback is not None:
                    fallback_models.append(f"nvidia:{settings.nvidia_model}")
                msg = f"!!! FAILOVER: Mistral chat model wired with fallbacks → {', '.join(fallback_models)}"
                print(msg)
                logger.info(msg)
        return ResolvedChatModel(
            provider="mistral",
            model_name=model_name,
            instance=composed.with_config(RunnableConfig(max_concurrency=1)),
        )

    if resolved_provider == "modal_glm":
        print("!!! ШАГ 3: Создаем ChatOpenAI")
        if settings.modal_glm_api_key is None:
            raise AppError(
                ErrorCode.LLM_NOT_CONFIGURED,
                "MODAL_GLM_API_KEY не настроен.",
                http_status=500,
            )

    extra_body: dict[str, object] | None = None##!!!!!
    if settings.modal_glm_disable_thinking:
        extra_body = {"thinking": {"type": "disabled"}}##!!!!!

    instance = ChatOpenAI(
        model=model_name,
        api_key=settings.modal_glm_api_key.get_secret_value(),
        base_url=settings.modal_glm_base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.max_retries,
        temperature=0,
        model_kwargs=model_kwargs,
        extra_body=extra_body,##!!!!!
        use_responses_api=False,
    )

    return ResolvedChatModel(provider="modal_glm", 
                             model_name=model_name, 
                             instance = instance.with_config(RunnableConfig(max_concurrency=1)))
