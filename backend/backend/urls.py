"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path

from skill_hub import views as skill_hub_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # 所有 API 统一挂载在 /api 前缀下（全局唯一入口）
    # 新增应用时在这里追加一行 path('', include('xxx.urls')) 即可，
    # 各应用内部只定义自己的业务路径（如 auth/、user/），不写 api 前缀
    path('api/', include([
        path('', include('accounts.urls')),
        path('ai/', include('ai_assistant.urls')),
        path('system-setting/', include('system_setting.urls')),
        path('', include('knowledge.urls')),
        path('skill-hub/', include('skill_hub.urls')),
    ])),
    # Skill Hub 发现端点（Agent Skills Discovery，公开无鉴权）：
    # 全部为 skill_hub 的动态视图，不存在静态 .well-known 目录或 index.json 文件
    path(
        '.well-known/skills/index.json',
        skill_hub_views.DiscoveryIndexView.as_view(),
    ),
    path(
        '.well-known/skills/<slug:name>/SKILL.md',
        skill_hub_views.DiscoveryFileView.as_view(),
    ),
    path(
        '.well-known/skills/<slug:name>/<path:file_path>',
        skill_hub_views.DiscoveryFileView.as_view(),
    ),
]
