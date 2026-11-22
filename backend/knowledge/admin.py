from django.contrib import admin

from .models import KnowledgeBase, KnowledgeDocument


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_by", "created_at", "updated_at")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_name",
        "knowledge_base",
        "size_bytes",
        "status",
        "created_at",
    )
    list_filter = ("status", "extension")
    search_fields = ("original_name", "content_hash")
    readonly_fields = ("created_at", "updated_at")
