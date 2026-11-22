from django.db import IntegrityError, transaction

from knowledge.models import KnowledgeBase

from . import Conflict


def create_knowledge_base(serializer, user):
    name = serializer.validated_data["name"]
    try:
        with transaction.atomic():
            if KnowledgeBase.objects.filter(name=name).exists():
                raise Conflict({"name": ["知识库名称已存在。"]})
            return serializer.save(created_by=user)
    except IntegrityError as exc:
        raise Conflict({"name": ["知识库名称已存在。"]}) from exc


def update_knowledge_base(serializer):
    name = serializer.validated_data.get("name")
    try:
        with transaction.atomic():
            if name is not None and KnowledgeBase.objects.filter(name=name).exclude(
                pk=serializer.instance.pk
            ).exists():
                raise Conflict({"name": ["知识库名称已存在。"]})
            return serializer.save()
    except IntegrityError as exc:
        raise Conflict({"name": ["知识库名称已存在。"]}) from exc


def delete_knowledge_base(instance):
    try:
        with transaction.atomic():
            knowledge_base = KnowledgeBase.objects.select_for_update().get(
                pk=instance.pk
            )
            if knowledge_base.documents.exists():
                raise Conflict("知识库内仍有文件，请先删除全部文件。")
            knowledge_base.delete()
    except IntegrityError as exc:
        raise Conflict("知识库内仍有文件，请先删除全部文件。") from exc
