"""accounts 应用的路由

挂载方式（backend/urls.py 中统一挂载在 /api 前缀下）:
    path('api/', include([
        path('', include('accounts.urls')),
    ]))

本文件只定义 accounts 自己的业务路径，不带 api 前缀。
最终 URL 与 Vben Admin 前端约定保持一致，均为无尾斜杠：
    POST /api/auth/login     登录
    POST /api/auth/refresh   刷新 accessToken
    POST /api/auth/logout    退出登录
    GET  /api/auth/codes     获取权限码
    GET  /api/auth/me        获取当前用户信息（调试用）
    GET  /api/user/info      获取用户信息（Vben Admin）
"""
from django.urls import path

from .views import (
    CodesView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    UserInfoView,
)

app_name = 'accounts'

urlpatterns = [
    path('auth/login', LoginView.as_view(), name='auth-login'),
    path('auth/refresh', RefreshView.as_view(), name='auth-refresh'),
    path('auth/logout', LogoutView.as_view(), name='auth-logout'),
    path('auth/codes', CodesView.as_view(), name='auth-codes'),
    path('auth/me', MeView.as_view(), name='auth-me'),
    path('user/info', UserInfoView.as_view(), name='user-info'),
]
