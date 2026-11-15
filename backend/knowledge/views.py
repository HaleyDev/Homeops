from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from backend.api import ApiResponseMixin, ok
from system_setting.permissions import IsSuperuser

from .models import KnowledgeBase, KnowledgeDocument
from .pagination import KnowledgePagination
from .serializers import KnowledgeBaseSerializer, KnowledgeDocumentSerializer
from .services.knowledge_bases import (
    create_knowledge_base,
    delete_knowledge_base,
    update_knowledge_base,
)
from .services.knowledge_documents import delete_document, upload_document


def _validate_path_ids(kwargs):
    for field in ("pk", "knowledge_base_id", "document_id"):
        value = kwargs.get(field)
        if value is None:
            continue
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError({field: "ID 必须是正整数。"}) from exc
        if value < 1:
            raise ValidationError({field: "ID 必须是正整数。"})


class KnowledgeBaseViewSet(ApiResponseMixin, ModelViewSet):
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [IsSuperuser]
    pagination_class = KnowledgePagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _validate_path_ids(kwargs)

    def get_queryset(self):
        queryset = KnowledgeBase.objects.annotate(document_count=Count("documents"))
        if self.action == "list":
            keyword = self.request.query_params.get("keyword", "").strip()
            if keyword:
                queryset = queryset.filter(
                    Q(name__icontains=keyword) | Q(description__icontains=keyword)
                )
        return queryset

    def perform_create(self, serializer):
        create_knowledge_base(serializer, self.request.user)

    def perform_update(self, serializer):
        update_knowledge_base(serializer)

    def destroy(self, request, *args, **kwargs):
        delete_knowledge_base(self.get_object())
        return ok(message="知识库已删除。")


class KnowledgeDocumentListView(ApiResponseMixin, APIView):
    permission_classes = [IsSuperuser]
    parser_classes = [MultiPartParser, FormParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _validate_path_ids(kwargs)

    def get(self, request, knowledge_base_id):
        get_object_or_404(KnowledgeBase, pk=knowledge_base_id)
        documents = KnowledgeDocument.objects.filter(
            knowledge_base_id=knowledge_base_id
        )
        paginator = KnowledgePagination()
        page = paginator.paginate_queryset(documents, request, view=self)
        serializer = KnowledgeDocumentSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, knowledge_base_id):
        document = upload_document(
            knowledge_base_id,
            request.FILES,
            request.user,
        )
        return ok(
            KnowledgeDocumentSerializer(document).data,
            message="文件已上传，尚未向量化。",
            status_code=status.HTTP_201_CREATED,
        )


class KnowledgeDocumentDetailView(ApiResponseMixin, APIView):
    permission_classes = [IsSuperuser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _validate_path_ids(kwargs)

    def delete(self, request, knowledge_base_id, document_id):
        delete_document(knowledge_base_id, document_id)
        return ok(message="文件已删除。")
