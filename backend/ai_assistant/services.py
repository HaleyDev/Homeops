import asyncio
import json
import os
from urllib.parse import quote_plus

from google.genai import types
from google.adk.events import Event
from .agent.agent import root_agent

APP_NAME = "homeops_assistant"

_session_service = None
_runner = None

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
        _runner = Runner(agent=root_agent, app_name=APP_NAME,
                         session_service=_session_service)
    return _runner, _session_service

def _sse(event: str, data: str) -> str:
    """格式化 SSE 消息"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

def _frames(ev: Event) -> list[str]:
    frames = []
    for p in (ev.content.parts if ev.content else []):
        if p.function_call:
            frames.append(_sse("tool_call", {
                "name": p.function_call.name,
                "args": dict(p.function_call.args or {}),
            }))
        elif p.function_response:
            frames.append(_sse("tool_response", {"name": p.function_response.name}))
        elif p.text:
            if getattr(p, "thought", False):
                frames.append(_sse("thinking", {"detail": p.text}))
            else:
                frames.append(_sse("text", {"detail": p.text}))
    if ev.is_final_response():
        usage = ev.usage_metadata
        frames.append(_sse("done", {
            "total_tokens": getattr(usage, "total_token_count", None) if usage else None,
        }))
    return frames

async def _a_chat_stream(runner, session_service, user_id, session_id, message):
    if await session_service.get_session(
        app_name=APP_NAME, session_id=session_id, user_id=user_id
    ) is None:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id)
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for ev in runner.run_async(user_id=user_id, session_id=session_id,
                                     new_message=content):
        yield ev


def chat_stream(user_id: str, session_id: str, message: str):
    """自管事件循环, 逐事件翻译成 SSE 帧。"""
    runner, session_service = get_runner()
    yield _sse("session", {"session_id": session_id})
    loop = asyncio.new_event_loop()
    try:
        agen = _a_chat_stream(runner, session_service, user_id, session_id, message)
        try:
            while True:
                ev = loop.run_until_complete(agen.__anext__())
                for frame in _frames(ev):
                    yield frame
        except StopAsyncIteration:
            pass
        except Exception as e:
            yield _sse("error", {"message": str(e)[:200]})
        finally:
            loop.run_until_complete(agen.aclose())
    finally:
        loop.close()