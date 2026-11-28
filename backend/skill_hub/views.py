"""Skill Hub 的 DRF 视图。

业务接口沿用 ApiResponseMixin/ok 统一响应；发现与下载端点公开无鉴权，
直接返回 JsonResponse/HttpResponse，不套用统一响应格式。
"""

import json
import mimetypes

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from backend.api import ApiResponseMixin, ok

from . import services, storage, validators
from .models import Skill, SkillVersion
from .pagination import SkillHubPagination
from .permissions import can_manage_skill
from .serializers import SkillListSerializer, SkillVersionSerializer


class Conflict(APIException):
    status_code = 409
    default_detail = 'Resource conflict.'
    default_code = 'skill_hub_conflict'


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = 'Uploaded file is too large.'
    default_code = 'skill_hub_payload_too_large'


def _get_skill(name):
    return get_object_or_404(Skill, name=name)


def _get_upload(request):
    files = request.FILES.getlist('file')
    if len(files) != 1:
        raise ValidationError({'file': 'Exactly one file must be uploaded.'})
    return files[0]


def _parse_tags(request):
    """tags 支持重复表单字段或 JSON 字符串数组；未携带返回 None。"""
    if 'tags' not in request.data:
        return None
    if not hasattr(request.data, 'getlist'):
        return request.data['tags']
    values = request.data.getlist('tags')
    if len(values) == 1:
        text = values[0].strip()
        if not text:
            return []
        if text.startswith('['):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    {'tags': 'Tags must be a JSON array or repeated form fields.'}
                ) from exc
    return values


def _upload_errors(exc):
    raise ValidationError(exc.report)


class SkillListView(ApiResponseMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        queryset = (
            Skill.objects.select_related('owner', 'published_version')
            .prefetch_related('versions')
            .order_by('-updated_at', '-id')
        )
        keyword = request.query_params.get('keyword', '').strip()
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword)
                | Q(versions__description__icontains=keyword)
            ).distinct()
        for tag in request.query_params.getlist('tag'):
            tag = tag.strip()
            if tag:
                queryset = queryset.filter(tags__contains=[tag])
        paginator = SkillHubPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = SkillListSerializer(
            page, many=True, context={'request': request}
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        uploaded = _get_upload(request)
        raw_tags = _parse_tags(request)
        try:
            version = services.upload_skill(
                uploaded,
                request.data.get('version', ''),
                raw_tags,
                request.user,
            )
        except services.InvalidUploadError as exc:
            _upload_errors(exc)
        except services.PayloadTooLargeError as exc:
            raise PayloadTooLarge(str(exc)) from exc
        except services.ConflictError as exc:
            raise Conflict(str(exc)) from exc
        except services.OwnerPermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        return ok(
            SkillVersionSerializer(
                version, context={'published_version_id': version.id}
            ).data,
            message='上传成功。',
            status_code=status.HTTP_201_CREATED,
        )


class SkillValidateView(ApiResponseMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = _get_upload(request)
        try:
            report = services.dry_run(uploaded)
        except services.InvalidUploadError as exc:
            return ok(exc.report)
        except services.PayloadTooLargeError as exc:
            raise PayloadTooLarge(str(exc)) from exc
        return ok(report)


class SkillTagsView(ApiResponseMixin, APIView):
    def get(self, request):
        return ok({'items': services.tag_summary()})


class SkillDetailView(ApiResponseMixin, APIView):
    def patch(self, request, name):
        skill = _get_skill(name)
        if not can_manage_skill(request.user, skill):
            raise PermissionDenied('Only the owner or a superuser can modify this Skill.')
        raw_tags = _parse_tags(request)
        if raw_tags is None:
            raise ValidationError({'tags': 'Tags are required.'})
        tags, issues = validators.normalize_tags(raw_tags)
        if issues:
            raise ValidationError({'tags': [issue.message for issue in issues]})
        services.update_tags(skill, tags)
        return ok(
            SkillListSerializer(skill, context={'request': request}).data,
            message='Skill 已更新。',
        )

    def delete(self, request, name):
        skill = _get_skill(name)
        if not can_manage_skill(request.user, skill):
            raise PermissionDenied('Only the owner or a superuser can delete this Skill.')
        services.delete_skill(skill)
        return ok(message='Skill 已删除。')


class SkillVersionListView(ApiResponseMixin, APIView):
    def get(self, request, name):
        skill = _get_skill(name)
        published = services.published_version(skill)
        versions = skill.versions.select_related('uploaded_by', 'skill').order_by(
            '-created_at', '-id'
        )
        return ok(
            {
                'items': SkillVersionSerializer(
                    versions,
                    many=True,
                    context={'published_version_id': published.id if published else None},
                ).data
            }
        )


class SkillVersionDetailView(ApiResponseMixin, APIView):
    def delete(self, request, name, version):
        skill = _get_skill(name)
        if not can_manage_skill(request.user, skill):
            raise PermissionDenied('Only the owner or a superuser can delete this Skill.')
        try:
            services.delete_version(skill, version)
        except SkillVersion.DoesNotExist as exc:
            raise NotFound('Version not found.') from exc
        return ok(message='版本已删除。')


class SkillVersionPublishView(ApiResponseMixin, APIView):
    def post(self, request, name, version):
        skill = _get_skill(name)
        if not can_manage_skill(request.user, skill):
            raise PermissionDenied('Only the owner or a superuser can publish versions.')
        try:
            published = services.publish_version(skill, version)
        except SkillVersion.DoesNotExist as exc:
            raise NotFound('Version not found or cannot be published.') from exc
        return ok(
            SkillVersionSerializer(
                published, context={'published_version_id': published.id}
            ).data,
            message='版本已发布。',
        )


class SkillDownloadView(APIView):
    """ZIP 下载：公开无鉴权；不带 version 时下载发布版本。"""

    permission_classes = [AllowAny]

    def _resolve_version(self, name, version):
        skill = _get_skill(name)
        if version is None:
            target = services.published_version(skill)
        else:
            target = skill.versions.filter(
                version=version, status=SkillVersion.Status.READY
            ).first()
        if target is None:
            raise NotFound('Version not found or cannot be downloaded.')
        return target

    def get(self, request, name, version=None):
        target = self._resolve_version(name, version)
        try:
            data = storage.resolve_key(target.storage_key).read_bytes()
        except FileNotFoundError as exc:
            raise NotFound('File not found.') from exc
        response = HttpResponse(data, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{target.archive_name}"'
        response['Content-Length'] = len(data)
        response['ETag'] = f'"{target.sha256}"'
        return response

    def head(self, request, name, version=None):
        response = self.get(request, name=name, version=version)
        response.content = b''
        return response


class DiscoveryIndexView(APIView):
    """Agent Skills Discovery 索引：动态构造，无静态文件。"""

    permission_classes = [AllowAny]

    def get(self, request):
        items = []
        skills = Skill.objects.prefetch_related('versions').order_by('name')
        for skill in skills:
            published = services.published_version(skill)
            if published is None:
                continue
            items.append(
                {
                    'name': skill.name,
                    'description': published.description,
                    'files': published.files,
                }
            )
        return JsonResponse({'skills': items})


class DiscoveryFileView(APIView):
    """按发布版本返回 SKILL.md 或资源文件，路径必须命中 files 清单。"""

    permission_classes = [AllowAny]

    def get(self, request, name, file_path='SKILL.md'):
        skill = _get_skill(name)
        published = services.published_version(skill)
        if published is None:
            raise NotFound('Skill not found or has no downloadable version.')
        if file_path not in published.files:
            raise NotFound('File not found.')
        content = storage.read_entry(published.storage_key, skill.name, file_path)
        if content is None:
            raise NotFound('File not found.')
        if file_path == 'SKILL.md':
            content_type = 'text/markdown; charset=utf-8'
        else:
            content_type = (
                mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
            )
        response = HttpResponse(content, content_type=content_type)
        response['ETag'] = f'"{published.sha256}"'
        response['Cache-Control'] = 'public, max-age=60'
        return response
