"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    # 所有 API 统一挂载在 /api 前缀下（全局唯一入口）
    # 新增应用时在这里追加一行 path('', include('xxx.urls')) 即可，
    # 各应用内部只定义自己的业务路径（如 auth/、user/），不写 api 前缀
    path('api/', include([
        path('', include('accounts.urls')),
    ])),
]
