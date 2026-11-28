from django.contrib import admin

from .models import Skill, SkillVersion


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'tags', 'created_at', 'updated_at')
    search_fields = ('name',)
    readonly_fields = ('uuid', 'created_at', 'updated_at')


@admin.register(SkillVersion)
class SkillVersionAdmin(admin.ModelAdmin):
    list_display = ('skill', 'version', 'status', 'size_bytes', 'uploaded_by', 'created_at')
    list_filter = ('status', 'source_type')
    search_fields = ('skill__name', 'version')
    readonly_fields = ('storage_key', 'sha256', 'created_at')
