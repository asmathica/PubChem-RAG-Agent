"""Process-wide LLM rate limiters.

LangChain's `InMemoryRateLimiter` implements an asyncio-safe token bucket
and is consumed by every `BaseChatModel` (incl. `ChatGoogleGenerativeAI`)
through the constructor's `rate_limiter=` argument. The model awaits
`rate_limiter.aacquire()` *before* each LLM HTTP call — so a request will
park in the queue rather than fail with 429 when the bucket is empty.

We expose **one singleton per provider** so that concurrent Chainlit
sessions and the FastAPI `/api/agent` endpoint share the same global
quota inside a single Python process.

Caveats
-------
- Works only inside one process. If the deployment scales to several
  uvicorn workers, swap for a Redis-backed limiter.
- Buckets count *requests*, not tokens — Google's free tier on Gemini /
  Gemma uses RPM, which matches.
- The default of 13 RPM leaves headroom under Google's 15-RPM free-tier
  cap; it absorbs skew between the client's monotonic clock and Google's
  quota window (otherwise the last request in a minute can still hit 429).
"""
from __future__ import annotations

from langchain_core.rate_limiters import InMemoryRateLimiter

from app.config import Settings


_gemini_limiter: InMemoryRateLimiter | None = None
_openrouter_limiter: InMemoryRateLimiter | None = None
_nvidia_limiter: InMemoryRateLimiter | None = None
_mistral_limiter: InMemoryRateLimiter | None = None


def _build(rpm: int) -> InMemoryRateLimiter:
    """Process-wide token bucket sized to ``rpm`` requests per minute."""
    return InMemoryRateLimiter(
        requests_per_second=rpm / 60.0,
        check_every_n_seconds=0.1,
        max_bucket_size=float(rpm),
    )


def get_gemini_rate_limiter(settings: Settings) -> InMemoryRateLimiter:
    """Singleton bucket for all Gemini/Gemma calls (`llm_rate_limit_gemini_rpm`)."""
    global _gemini_limiter
    if _gemini_limiter is None:
        _gemini_limiter = _build(settings.llm_rate_limit_gemini_rpm)
    return _gemini_limiter


def get_openrouter_rate_limiter(settings: Settings) -> InMemoryRateLimiter:
    """Singleton bucket for OpenRouter calls (`llm_rate_limit_openrouter_rpm`).

    OpenRouter free pool docs cap each model at ~20 RPM; this bucket
    parks excess requests instead of letting them surface as 429.
    """
    global _openrouter_limiter
    if _openrouter_limiter is None:
        _openrouter_limiter = _build(settings.llm_rate_limit_openrouter_rpm)
    return _openrouter_limiter


def get_nvidia_rate_limiter(settings: Settings) -> InMemoryRateLimiter:
    """Singleton bucket for NVIDIA NIM calls (`llm_rate_limit_nvidia_rpm`).

    NVIDIA NIM free tier caps each model at 40 RPM; we run at 35 to
    leave headroom for clock skew.
    """
    global _nvidia_limiter
    if _nvidia_limiter is None:
        _nvidia_limiter = _build(settings.llm_rate_limit_nvidia_rpm)
    return _nvidia_limiter


def get_mistral_rate_limiter(settings: Settings) -> InMemoryRateLimiter:
    """Singleton bucket for Mistral La Plateforme calls
    (`llm_rate_limit_mistral_rpm`).

    Mistral free tier caps each project at 60 RPM (1 req/sec) plus
    500 000 TPM and 1B tokens/month; we run at 55 RPM to absorb skew.
    """
    global _mistral_limiter
    if _mistral_limiter is None:
        _mistral_limiter = _build(settings.llm_rate_limit_mistral_rpm)
    return _mistral_limiter
