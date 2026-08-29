from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """HomeOps 用户模型

    gitlab_sub 存放 GitLab OIDC id_token 中的 sub claim
    （GitLab 给每个用户分配的全局唯一、永不变更标识）。

    GitLab 登录时按它查找或创建本地用户：
    - 首次登录：创建 User 并写入 gitlab_sub
    - 再次登录：按 gitlab_sub 复用同一 User，不重复建档

    允许为 null：账号密码创建的本地用户（如管理员）可以不绑定 GitLab。
    """

    gitlab_sub = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text='GitLab OIDC sub claim，用于绑定 GitLab 账号；本地用户可为空',
    )

    def __str__(self):
        return self.username
