from django.db import models
from django.conf import settings
import uuid


# Create your models here.

class ChatSession(models.Model):
    "会话记录，左侧会话栏中的数据，一行表示一个会话窗口"
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name="ai_chat_sessions",
    )
    title = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

class ChatMessage(models.Model):

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    thinking = models.TextField(blank=True, default="")
    tool_calls = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]