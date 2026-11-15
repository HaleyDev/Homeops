from rest_framework import serializers

from .models import KnowledgeBase, KnowledgeDocument


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=50, trim_whitespace=True)
    description = serializers.CharField(max_length=300, trim_whitespace=True)
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBase
        fields = (
            "id",
            "name",
            "description",
            "document_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "document_count", "created_at", "updated_at")

    def get_document_count(self, obj):
        annotated_count = getattr(obj, "document_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.documents.count()


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    knowledge_base_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = KnowledgeDocument
        fields = (
            "id",
            "knowledge_base_id",
            "original_name",
            "mime_type",
            "extension",
            "size_bytes",
            "status",
            "error_message",
            "created_at",
        )
        read_only_fields = fields
