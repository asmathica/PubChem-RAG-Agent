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

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings

logger = logging.getLogger(__name__)

_checkpointer: Any = None
_postgres_cm: Any = None  # async context manager kept open for lifetime of process
# Lock защищает init от race: два concurrent first-callers могли оба пройти
# `if _checkpointer is not None: return None` и оба войти в __aenter__() →
# второй pool оставался без ссылки и утекал. Double-check pattern: fast path
# без lock (когда уже инициализирован), slow path под lock.
_init_lock = asyncio.Lock()


async def get_checkpointer(settings: Settings) -> Any:
    """Возвращает singleton checkpointer. Инициализирует при первом вызове.

    Postgres URL → AsyncPostgresSaver (с auto `setup()` на первом запуске).
    Иначе → InMemorySaver.
    """
    global _checkpointer, _postgres_cm

    # Fast path: уже проинициализирован — без lock (95%+ вызовов попадают сюда).
    if _checkpointer is not None:
        return _checkpointer

    async with _init_lock:
        # Re-check под lock — между первым check и захватом lock другой корутин
        # мог уже всё проинициализировать.
        if _checkpointer is not None:
            return _checkpointer

        postgres_url_secret = settings.agent_checkpoint_postgres_url
        postgres_url = postgres_url_secret.get_secret_value() if postgres_url_secret else None

        if postgres_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            cm = AsyncPostgresSaver.from_conn_string(postgres_url)
            try:
                saver = await cm.__aenter__()
                # setup() в отдельный try чтобы при падении гарантированно вызвать
                # __aexit__() на УЖЕ открытом context manager — иначе pool утечёт.
                try:
                    await saver.setup()
                except Exception:
                    await cm.__aexit__(None, None, None)
                    raise
                _postgres_cm = cm
                _checkpointer = saver
                logger.info("AsyncPostgresSaver инициализирован для conversation memory")
            except Exception as exc:
                logger.error(
                    f"AsyncPostgresSaver init failed: {exc}. Fallback на InMemorySaver.",
                    exc_info=True,
                )
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
