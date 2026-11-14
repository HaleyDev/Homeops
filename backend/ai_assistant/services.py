import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote_plus

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from .agent.agent import root_agent
from .streaming import TurnResult, TurnStreamCollector

APP_NAME = "homeops_assistant"

_session_service = None
_runner = None
logger = logging.getLogger(__name__)


def get_runner():
    global _session_service, _runner
    if _runner is None:
        from django.conf import settings as dj_settings
        from google.adk.runners import Runner
        from google.adk.sessions import DatabaseSessionService
        from sqlalchemy.pool import NullPool

        db = dj_settings.DATABASES["default"]
        db_url = (
            f"mysql+aiomysql://{db['USER']}:{quote_plus(db['PASSWORD'])}"
            f"@{db.get('HOST') or '127.0.0.1'}:{db.get('PORT') or '3306'}/{db['NAME']}"
            "?charset=utf8mb4"
        )
        _session_service = DatabaseSessionService(db_url, poolclass=NullPool)
        _runner = Runner(
            agent=root_agent, app_name=APP_NAME, session_service=_session_service
        )
    return _runner, _session_service


def _sse(event: str, data: Mapping[str, Any]) -> str:
    """Encode one structured event as an SSE frame."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _a_chat_stream(runner, session_service, user_id, session_id, message):
    if (
        await session_service.get_session(
            app_name=APP_NAME, session_id=session_id, user_id=user_id
        )
        is None
    ):
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        yield event


def chat_stream(
    user_id: str,
    session_id: str,
    message: str,
    *,
    on_complete: Callable[[TurnResult], Mapping[str, Any]],
):
    """Bridge ADK's async stream and persist before emitting a single done.

    ``on_complete`` is supplied by the view and returns the serialized,
    persisted assistant message. Exceptions never become client-facing text.
    """

    yield _sse("session", {"session_id": session_id})
    runner, session_service = get_runner()
    collector = TurnStreamCollector()
    total_tokens = None
    loop = asyncio.new_event_loop()
    try:
        agen = _a_chat_stream(
            runner, session_service, user_id, session_id, message
        )
        try:
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break

                for stream_event in collector.process(event):
                    yield _sse(stream_event.name, stream_event.data)
                usage = event.usage_metadata
                tokens = (
                    getattr(usage, "total_token_count", None) if usage else None
                )
                if tokens is not None:
                    total_tokens = tokens
        except Exception:
            logger.exception("ADK chat stream failed session=%s", session_id)
            yield _sse(
                "error",
                {"message": "AI 助手服务暂时不可用，请稍后重试。"},
            )
        else:
            result = collector.finish()
            try:
                assistant_message = on_complete(result)
            except Exception:
                logger.exception(
                    "Assistant message persistence failed session=%s", session_id
                )
                yield _sse(
                    "error", {"message": "助手消息保存失败，请稍后重试。"}
                )
            else:
                yield _sse(
                    "done",
                    {
                        "total_tokens": total_tokens,
                        "assistant_message": assistant_message,
                    },
                )
        finally:
            try:
                loop.run_until_complete(agen.aclose())
            except Exception:
                logger.exception("ADK chat stream close failed session=%s", session_id)
    finally:
        loop.close()
