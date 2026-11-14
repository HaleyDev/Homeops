from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    LLMModelViewSet,
    LLMProviderViewSet,
    SelectionDetailView,
    SelectionListView,
)

router = DefaultRouter()
router.register("llm/providers", LLMProviderViewSet, basename="llm-provider")
router.register("llm/models", LLMModelViewSet, basename="llm-model")

urlpatterns = [
    path("llm/selections/", SelectionListView.as_view()),
    path("llm/selections/<str:category>/", SelectionDetailView.as_view()),
] + router.urls
