"""
用户认证接口（适配 Vben Admin 前端）

Vben Admin 前端对后端的约定：
1. 所有响应使用统一格式: {"code": 0, "data": ..., "message": "..."}
   - code = 0 表示成功，前端取 data 字段
   - code != 0 表示业务失败，message 会直接展示给用户（HTTP 状态码保持 200）
2. 业务字段使用 camelCase（如 accessToken、userId）
3. Token 过期/无效时返回 HTTP 401，前端会自动跳转登录页或尝试刷新 Token
4. 刷新 Token 通过 HttpOnly Cookie 传递（前端开启 enableRefreshToken 时使用）
"""
from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

REFRESH_TOKEN_COOKIE = 'homeops_refresh_token'


def ok(data=None, message='OK'):
    """成功响应：{"code": 0, "data": ..., "message": "OK"}"""
    return Response({'code': 0, 'data': data, 'message': message})


def fail(message='操作失败', code=1):
    """业务失败响应（HTTP 200，前端直接展示 message）"""
    return Response({'code': code, 'data': None, 'message': message})


def set_refresh_cookie(response, refresh_token):
    """将 refresh token 写入 HttpOnly Cookie，只随 /api/auth/* 请求发送"""
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=int(
            settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()
        ),
        httponly=True,
        samesite='Lax',
        path='/api/auth',
    )


class LoginView(APIView):
    """
    登录接口

    POST /api/auth/login
    请求体: {"username": "admin", "password": "xxx"}
    成功: {"code": 0, "data": {"accessToken": "..."}, "message": "OK"}
    失败: {"code": 1, "data": null, "message": "用户名或密码错误"}
    """

    # 登录接口本身不需要认证和权限
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return fail('用户名和密码不能为空')

        user = authenticate(request, username=username, password=password)
        if user is None:
            return fail('用户名或密码错误')

        refresh = RefreshToken.for_user(user)
        response = ok({'accessToken': str(refresh.access_token)})
        # refresh token 放入 HttpOnly Cookie，供 /api/auth/refresh 使用
        set_refresh_cookie(response, str(refresh))
        return response


class RefreshView(APIView):
    """
    刷新 accessToken

    POST /api/auth/refresh
    从 HttpOnly Cookie 中读取 refresh token，
    响应体直接返回新的 accessToken 字符串（Vben 前端约定）。
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        token = request.COOKIES.get(REFRESH_TOKEN_COOKIE)
        if not token:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        try:
            refresh = RefreshToken(token)
        except TokenError:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        return Response(str(refresh.access_token))


class LogoutView(APIView):
    """
    退出登录

    POST /api/auth/logout
    清除 refresh token Cookie。
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        response = ok(message='已退出登录')
        response.delete_cookie(REFRESH_TOKEN_COOKIE, path='/api/auth')
        return response


class UserInfoView(APIView):
    """
    获取当前用户信息

    GET /api/user/info
    需要请求头: Authorization: Bearer <accessToken>
    返回 Vben Admin 的 UserInfo 结构（camelCase）。
    """

    def get(self, request):
        user = request.user
        roles = ['super'] if user.is_superuser else ['user']
        return ok({
            'userId': str(user.id),
            'username': user.username,
            'realName': user.username,
            'avatar': '',
            'desc': 'HomeOps 管理员' if user.is_superuser else '普通用户',
            'roles': roles,
            'homePath': '/home',
        })


class CodesView(APIView):
    """
    获取当前用户权限码

    GET /api/auth/codes
    用于前端 v-access 指令按权限码控制按钮/组件显隐，暂无权限码体系，返回空数组。
    """

    def get(self, request):
        return ok([])


class MeView(APIView):
    """
    获取当前用户信息（调试用，非 Vben Admin 必需接口）

    GET /api/auth/me
    """

    def get(self, request):
        user = request.user
        return ok({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_superuser': user.is_superuser,
        })
