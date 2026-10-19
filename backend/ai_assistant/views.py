import json
import logging

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .models import ChatMessage, ChatSession
from .serializers import ChatMessageSerializer, ChatSessionSerializer
from .services import chat_stream

logger = logging.getLogger(__name__)


class ChatRequestSerializer(serializers.Serializer):
    """入参校验: 非法 JSON / 缺字段 → 自动 400"""
    message = serializers.CharField()
    session_id = serializers.UUIDField()      # 会话必须先经 POST /sessions/ 创建


class ChatView(APIView):
    """POST /api/ai/chat/ —— SSE 流式对话 (含业务记账)"""
    renderer_classes = [JSONRenderer]
    parser_classes = [JSONParser]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]
        session_id = str(serializer.validated_data["session_id"])

        # ---- 业务层挂钩: 归属校验 + 首条消息起标题 + user 消息落库 ----
        chat_session = get_object_or_404(ChatSession, session_id=session_id, user=request.user)
        if not chat_session.messages.exists() and chat_session.title in ("", "New Chat"):
            chat_session.title = message[:50]
            chat_session.save(update_fields=["title"])
        ChatMessage.objects.create(session=chat_session, role="user", content=message)
        # --------------------------------------------------------------

        resp = StreamingHttpResponse(
            recording_stream(
                chat_session,
                chat_stream(str(request.user.id), session_id, message),
            ),
            content_type="text/event-stream",
        )
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp


class ChatSessionViewSet(ModelViewSet):
    """会话 CRUD + 嵌套聊天记录。 queryset 天然按用户隔离, 跨用户访问一律 404"""
    serializer_class = ChatSessionSerializer
    lookup_field = "session_id"
    lookup_value_regex = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(
            user=self.request.user,
            title=serializer.validated_data.get("title") or "New Chat",
        )

    @action(detail=True, methods=["get"])
    def messages(self, request, session_id=None):
        session = self.get_object()
        return Response({
            "session_id": str(session.session_id),
            "title": session.title,
            "messages": ChatMessageSerializer(session.messages.all(), many=True).data,
        })


def _parse_frame(frame: str):
    """把 chat_stream 产出的单帧解析回 (事件名, 数据dict); 解析不了就返回 (None, None)"""
    lines = frame.strip().split("\n")
    if len(lines) < 2 or not lines[0].startswith("event: "):
        return None, None
    try:
        return lines[0][7:].strip(), json.loads(lines[1][6:])   # "data: " 后是单行 JSON
    except (IndexError, json.JSONDecodeError):
        return lines[0][7:].strip(), None


def recording_stream(chat_session, upstream):
    """包住 chat_stream: 帧原样转发; 同时攒 assistant 消息, 见到 done 帧落库"""
    buf = {"content": "", "thinking": "", "tool_calls": []}
    for frame in upstream:
        yield frame                                   # 前端协议零变化
        event, data = _parse_frame(frame)
        if data is None:
            continue
        if event == "text":
            buf["content"] += data.get("detail", "")
        elif event == "thinking":
            buf["thinking"] += data.get("detail", "")
        elif event == "tool_call":
            buf["tool_calls"].append({
                "name": data.get("name", ""),
                "args": data.get("args", {}),
            })
        elif event == "done":
            try:
                ChatMessage.objects.create(session=chat_session, role="assistant", **buf)
            except Exception:
                logger.warning("assistant 消息落库失败 session=%s", chat_session.session_id)
