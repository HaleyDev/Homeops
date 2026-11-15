from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    KnowledgeBaseViewSet,
    KnowledgeDocumentDetailView,
    KnowledgeDocumentListView,
    KnowledgeDocumentRetryView,
)

router = DefaultRouter()
router.register("knowledge-bases", KnowledgeBaseViewSet, basename="knowledge-base")

urlpatterns = [
    path(
        "knowledge-bases/<int:knowledge_base_id>/documents/",
        KnowledgeDocumentListView.as_view(),
        name="knowledge-document-list",
    ),
    path(
        "knowledge-bases/<int:knowledge_base_id>/documents/<int:document_id>/",
        KnowledgeDocumentDetailView.as_view(),
        name="knowledge-document-detail",
    ),
    path(
        (
            "knowledge-bases/<int:knowledge_base_id>/documents/"
            "<int:document_id>/retry/"
        ),
        KnowledgeDocumentRetryView.as_view(),
        name="knowledge-document-retry",
    ),
    path("", include(router.urls)),
]
