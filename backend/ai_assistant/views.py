import uuid

from django.contrib.admin import action
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .services import chat_stream
from .models import ChatSession
from .serializers import ChatMessageSerializer, ChatSessionSerializer


class ChatRequestSerializer(serializers.Serializer):
    """入参校验: 非法 JSON / 缺 message / session_id 非 UUID → 自动 400"""
    message = serializers.CharField()               # 默认 trim 空白, 空串直接报错
    session_id = serializers.UUIDField(required=False)


class ChatView(APIView):
    """POST /api/ai/chat/ —— SSE 流式对话。

    认证与权限走项目全局 DRF 配置 (SimpleJWT + IsAuthenticated),
    前端现有 token 直接可用, 鉴权失败自动返回 401。
    """
    renderer_classes = [JSONRenderer]   # 关掉 Browsable API, 响应就是纯 SSE
    parser_classes = [JSONParser]       # 只收 JSON

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]
        session_id = str(serializer.validated_data.get("session_id") or uuid.uuid4())

        resp = StreamingHttpResponse(
            chat_stream(str(request.user.id), session_id, message),
            content_type="text/event-stream",
        )
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

class ChatSessionViewSet(ModelViewSet):
    """会话列表 / 新建会话 / 删除会话"""
    serializer_class = ChatSessionSerializer
    lookup_field = "session_id"
    lookup_value_regex = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, title=serializer.validated_data.get("title") or "New Chat")

    @action(detail=True, methods=["get"])
    def messages(self, request, session_id=None):
        session = self.get_object()
        return Response({
            "session_id": str(session.session_id),
            "title": session.title,
            "messages": ChatMessageSerializer(session.messages.all(), many=True).data,
        })