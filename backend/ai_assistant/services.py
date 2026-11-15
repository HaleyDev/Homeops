import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote_plus

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from system_setting.models import ModelType
from system_setting.services import ModelConfigurationError, get_effective_model_config

from .agent.agent import create_agent
from .streaming import TurnResult, TurnStreamCollector

APP_NAME = "homeops_assistant"

_session_service = None
logger = logging.getLogger(__name__)


def get_session_service():
    global _session_service
    if _session_service is None:
        from django.conf import settings as dj_settings
        from google.adk.sessions import DatabaseSessionService
        from sqlalchemy.pool import NullPool

        db = dj_settings.DATABASES["default"]
        db_url = (
            f"postgresql+asyncpg://{quote_plus(db['USER'])}:{quote_plus(db['PASSWORD'])}"
            f"@{db.get('HOST') or '127.0.0.1'}:{db.get('PORT') or '5432'}/{db['NAME']}"
        )
        _session_service = DatabaseSessionService(db_url, poolclass=NullPool)
    return _session_service


def get_runner():
    """Build a fresh LLM/Agent/Runner for every new assistant turn."""

    from google.adk.runners import Runner

    config = get_effective_model_config(ModelType.TEXT)
    session_service = get_session_service()
    runner = Runner(
        agent=create_agent(config),
        app_name=APP_NAME,
        session_service=session_service,
    )
    return runner, session_service


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
    try:
        runner, session_service = get_runner()
    except ModelConfigurationError as exc:
        yield _sse("error", {"message": str(exc)})
        return
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
                {"message": "The AI assistant is temporarily unavailable. Please try again later."},
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
                    "error",
                    {"message": "The assistant message could not be saved. Please try again later."},
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
