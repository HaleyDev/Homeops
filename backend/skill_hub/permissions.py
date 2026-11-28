"""Skill Hub 的所有权判定：上传者（owner）或超级管理员。"""


def can_manage_skill(user, skill):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or skill.owner_id == user.id)
    )
