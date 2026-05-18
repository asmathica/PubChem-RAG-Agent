from functools import lru_cache
import os
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

ENV_PATH =  "./.env"
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file = ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )
    ollama_base_url: str = "http://localhost:11434"
    app_name: str = "PubChem Compound Explorer API"
    api_version: str = "0.1.0"
    environment: str = "development"
    base_llm_model: str = "gemma3:4b" 

    pubchem_rest_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    pubchem_view_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

    request_timeout_seconds: float = 30.0
    llm_request_timeout_seconds: float = 120.0
    agent_run_timeout_seconds: float = 240.0
    # 2 retry на primary — достаточно для transient 5xx; больше упирается
    # в curl/UI timeout (12 попыток × 3 провайдера × ~10s = 6 минут).
    max_retries: int = 2
    # Fallback провайдер делает 1 попытку и сразу advance к следующему,
    # вместо того чтобы долбить тот же endpoint.
    llm_fallback_max_retries: int = 1
    candidate_limit: int = 10
    query_rate_limit_per_second: int = 3
    heavy_query_concurrency: int = 1
    agent_max_steps: int = 10

    llm_default_provider: str = "mistral"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    modal_glm_base_url: str = "https://api.us-west-2.modal.direct/v1"
    modal_glm_api_key: SecretStr | None = None
    modal_glm_model: str = "zai-org/GLM-5.1-FP8"
    modal_glm_disable_thinking: bool = True
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3-flash-preview"
    # Free tier: gemini-3-flash-preview = 5 RPM, gemma-4-31b-it /
    # gemini-3.1-flash-lite-preview ≈ 15 RPM. 13 даёт безопасный запас
    # под 15-RPM cap; для -3-flash-preview лучше переопределить в .env на 4.
    llm_rate_limit_gemini_rpm: int = 13

    # Per-provider RPM лимиты (process-wide token bucket в InMemoryRateLimiter):
    # OpenRouter free pool — 20 RPM на модель ([docs](https://openrouter.ai/docs/api/reference/limits));
    # 18 даёт headroom под clock skew с серверной стороной.
    llm_rate_limit_openrouter_rpm: int = 18
    # NVIDIA NIM (build.nvidia.com) — 40 RPM на endpoint модели
    # ([forums.developer.nvidia.com](https://forums.developer.nvidia.com/t/request-to-increase-nim-api-rate-limit-from-40-rpm-to-200-rpm-for-personal-study/368108));
    # 35 — то же самое с запасом.
    llm_rate_limit_nvidia_rpm: int = 35
    # Mistral La Plateforme — 60 RPM (1 req/sec) на free tier; 55 — запас
    # под clock skew с серверной стороной. https://docs.mistral.ai/deployment/laplateforme/tier/
    llm_rate_limit_mistral_rpm: int = 55

    # OpenRouter — первый fallback OpenAI-совместимого типа.
    # https://openrouter.ai/docs
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"

    # NVIDIA NIM — второй fallback. Тоже OpenAI-совместимый, не зависит от
    # Google → выручает когда OpenRouter free pool тоже rate-limited.
    # Получить ключ: https://build.nvidia.com (Build with NVIDIA, бесплатно)
    nvidia_api_key: SecretStr | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Note: z-ai/glm4.7 reached EOL on 2026-05-14 on NVIDIA NIM (410 Gone).
    # meta/llama-3.3-70b-instruct is the stable replacement with native tool
    # calling; swap to `nvidia/llama-3.3-nemotron-super-49b-v1` if you want a
    # smaller, NVIDIA-tuned variant.
    nvidia_model: str = "meta/llama-3.3-70b-instruct"

    # Mistral La Plateforme — самый щедрый free tier среди этих провайдеров:
    # 60 RPM (1 req/sec), 500 000 TPM, 1B токенов/месяц. Tool calling
    # нативный, OpenAI-совместимый. Получить ключ:
    # https://console.mistral.ai/home?profile_dialog=api-keys
    mistral_api_key: SecretStr | None = None
    mistral_base_url: str = "https://api.mistral.ai/v1"
    # Mistral Medium 3.5 — frontier-class, агентский/кодовый use case,
    # 262K context, Apr 2026. Альтернативы:
    #   magistral-small-latest (Mistral Small 4, быстрее)
    #   mistral-large-latest (Mistral Large 3, мощнее но медленнее)
    #   ministral-14b-latest (edge, очень быстро)
    mistral_model: str = "mistral-medium-3.5"

    # Авто-failover Gemini → OpenRouter → NVIDIA. Включён по умолчанию: если
    # основной Google-вызов падает (FAILED_PRECONDITION, RESOURCE_EXHAUSTED,
    # 5xx и т.п.) и хотя бы один fallback настроен — LangChain прозрачно
    # повторяет запрос через цепочку. Установи в `false`, чтобы отлаживать
    # Gemini без скрытого fallback.
    llm_enable_fallback: bool = True

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "http://localhost:3000"

    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    frontend_public_api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("FRONTEND_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_API_BASE_URL"),
    )


@lru_cache
def get_settings() -> Settings:
    load_dotenv(str(ENV_PATH))
   # env_key = os.environ.get("MODAL_GLM_API_KEY")
    print(f"\n--- [CRITICAL DEBUG] ---")
    print(f"Путь к .env: {ENV_PATH}")
   # print(f"Ключ в os.environ: {env_key[:5]}***" if env_key else "Ключ в os.environ: MISSING")
    #settings = Settings()

   # print(f"Ключ в Settings объекте: {settings.modal_glm_api_key is not None}")
    #print(f"------------------------\n")
    return Settings()
