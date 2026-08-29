from django.urls import path
from mozilla_django_oidc.views import (
    OIDCAuthenticationRequestView,
    OIDCLogoutView,
)

from .views import (
    CodesView,
    GitLabOIDCCallbackView,
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
    # GitLab OIDC 登录
    path(
        'oidc/authenticate',
        OIDCAuthenticationRequestView.as_view(),
        name='oidc_authentication_init',
    ),
    path(
        'oidc/callback',
        GitLabOIDCCallbackView.as_view(),
        name='oidc_authentication_callback',
    ),
    path('oidc/logout', OIDCLogoutView.as_view(), name='oidc_logout'),
]
