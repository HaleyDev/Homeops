from functools import partial

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
            chat_stream(
                str(request.user.id),
                session_id,
                message,
                on_complete=partial(_persist_assistant_message, chat_session),
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


def _persist_assistant_message(chat_session, result):
    """Persist and serialize the authoritative message for the done event."""

    message = ChatMessage.objects.create(
        session=chat_session,
        role=ChatMessage.Role.ASSISTANT,
        content=result.content,
        thinking=result.thinking,
        tool_calls=result.tool_calls,
    )
    return ChatMessageSerializer(message).data
