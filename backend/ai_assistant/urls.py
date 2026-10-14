from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ChatSessionViewSet, ChatView

router = DefaultRouter()
router.register("sessions", ChatSessionViewSet, basename="chat-session")

urlpatterns = [
    path("chat/", ChatView.as_view()),
] + router.urls