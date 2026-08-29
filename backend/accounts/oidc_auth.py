from mozilla_django_oidc.auth import OIDCAuthenticationBackend

# GitLab 群组角色 claim 的键前缀
GROUP_ROLE_CLAIM_PREFIX = 'https://gitlab.org/claims/groups/'

# 角色名 -> GitLab access_level 等级（仅取登录后可鉴别的三档）
ROLE_LEVELS = {
    'developer': 30,
    'maintainer': 40,
    'owner': 50,
}

# 群组角色 -> 本地管理员的映射规则：
# 「用户在左侧群组中达到右侧角色及以上」时，视为本系统管理员
# （is_staff 与 is_superuser 同步置位）。键为群组 full_path，值为角色名。
# 按实际群组填写，例如 {'platform-team': 'maintainer'}
GITLAB_ADMIN_GROUP_RULES = {}


class GitLabOIDCBackend(OIDCAuthenticationBackend):
    """GitLab OIDC 认证后端：按 gitlab_sub 认人，按群组角色 claim 定权"""

    def filter_users_by_claims(self, claims):
        """按 sub（绑定键）查找已存在的本地用户"""
        sub = claims.get('sub')
        if not sub:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(gitlab_sub=sub)

    def verify_claims(self, claims):
        """身份判定只依赖 sub；email 仅作展示，不作为身份依据"""
        return 'sub' in claims

    def get_username(self, claims):
        """用户名取 GitLab username，取不到时退回 sub 前缀"""
        username = claims.get('preferred_username') or claims.get('nickname')
        if not username:
            username = 'gitlab-' + claims.get('sub', '')[:16]
        return username

    def create_user(self, claims):
        """首次 GitLab 登录：创建本地用户并写入绑定键"""
        sub = claims.get('sub')
        username = self.get_username(claims)
        # 本地可能已有同名账号密码用户，冲突时加后缀避免撞唯一约束
        if self.UserModel.objects.filter(username__iexact=username).exists():
            username = f'{username}-{sub[:8]}'
        user = self.UserModel.objects.create_user(
            username,
            email=claims.get('email') or '',
        )
        user.gitlab_sub = sub
        user.first_name = claims.get('name') or ''
        user.save()
        self._assign_roles(user, claims)
        return user

    def update_user(self, user, claims):
        """已绑定的用户再次登录：刷新资料与权限"""
        user.email = claims.get('email') or ''
        user.first_name = claims.get('name') or ''
        user.save()
        self._assign_roles(user, claims)
        return user

    def _assign_roles(self, user, claims):
        """按群组角色 claim 映射本地管理员权限。

        GitLab 未返回任何群组信息时（如 scope 不足、群组私有），
        保持用户现有权限不变，避免误降权。
        """
        if not GITLAB_ADMIN_GROUP_RULES:
            return
        groups_claim = claims.get('groups')
        role_claims = {
            role: claims.get(GROUP_ROLE_CLAIM_PREFIX + role)
            for role in ROLE_LEVELS
        }
        if groups_claim is None and all(v is None for v in role_claims.values()):
            return

        is_admin = False
        for group_path, min_role in GITLAB_ADMIN_GROUP_RULES.items():
            min_level = ROLE_LEVELS[min_role]
            # 角色达到门槛的群组列表：在 owner/maintainer/developer
            # 对应 claim 中任一达到门槛的列表里出现即满足
            for role, level in ROLE_LEVELS.items():
                if level < min_level:
                    continue
                groups = role_claims.get(role) or []
                if group_path in groups:
                    is_admin = True
                    break
            if is_admin:
                break

        if user.is_staff != is_admin or user.is_superuser != is_admin:
            user.is_staff = is_admin
            user.is_superuser = is_admin
            user.save(update_fields=['is_staff', 'is_superuser'])
