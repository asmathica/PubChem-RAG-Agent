"""
MODULE: Agent Conversation Memory (LangGraph checkpointer)
----------------------------------------------------------
PURPOSE:
Singleton checkpointer для LangGraph агента. Хранит историю диалога per
`thread_id` (= chainlit session id). Решает проблему "агент не помнит
предыдущее сообщение в той же сессии".

BACKEND SELECTION:
- Если задан `settings.agent_checkpoint_postgres_url` → AsyncPostgresSaver
  (персистентное хранение, переживает restart, production-grade).
- Иначе → InMemorySaver (state в RAM, dev fallback без зависимостей).

LIFECYCLE:
Singleton инициализируется лениво при первом вызове `get_checkpointer()`.
AsyncPostgresSaver открывается через `__aenter__()` и держится открытым
весь runtime приложения. Закрытие через `close_checkpointer()` при
shutdown (вызвать в lifespan FastAPI или при завершении процесса).
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings

logger = logging.getLogger(__name__)

_checkpointer: Any = None
_postgres_cm: Any = None  # async context manager kept open for lifetime of process


async def get_checkpointer(settings: Settings) -> Any:
    """Возвращает singleton checkpointer. Инициализирует при первом вызове.

    Postgres URL → AsyncPostgresSaver (с auto `setup()` на первом запуске).
    Иначе → InMemorySaver.
    """
    global _checkpointer, _postgres_cm

    if _checkpointer is not None:
        return _checkpointer

    postgres_url_secret = settings.agent_checkpoint_postgres_url
    postgres_url = postgres_url_secret.get_secret_value() if postgres_url_secret else None

    if postgres_url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            _postgres_cm = AsyncPostgresSaver.from_conn_string(postgres_url)
            _checkpointer = await _postgres_cm.__aenter__()
            await _checkpointer.setup()
            logger.info("AsyncPostgresSaver инициализирован для conversation memory")
        except Exception as exc:
            logger.error(
                f"AsyncPostgresSaver init failed: {exc}. Fallback на InMemorySaver.",
                exc_info=True,
            )
            _postgres_cm = None
            _checkpointer = InMemorySaver()
    else:
        _checkpointer = InMemorySaver()
        logger.info("InMemorySaver используется для conversation memory (dev fallback)")

    return _checkpointer


async def close_checkpointer() -> None:
    """Закрывает Postgres connection pool при shutdown. Безопасно вызывать
    несколько раз или если checkpointer не был инициализирован."""
    global _checkpointer, _postgres_cm

    if _postgres_cm is not None:
        try:
            await _postgres_cm.__aexit__(None, None, None)
            logger.info("AsyncPostgresSaver closed")
        except Exception as exc:
            logger.warning(f"AsyncPostgresSaver close failed (non-fatal): {exc}")
        finally:
            _postgres_cm = None

    _checkpointer = None
