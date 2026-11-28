import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from skill_hub.models import Skill, SkillVersion


def make_skill_md(name='demo-skill', description='初始说明'):
    return (
        f'---\nname: {name}\ndescription: {description}\n---\n\n具体操作步骤。\n'
    ).encode()


def make_skill_zip(name='demo-skill', description='压缩包说明'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(f'{name}/SKILL.md', make_skill_md(name, description))
        archive.writestr(f'{name}/scripts/run.txt', b'run content')
    return buffer.getvalue()


class SkillHubApiTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.settings_override = override_settings(
            SKILL_HUB_ROOT=self.temporary_directory.name
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.root = Path(self.temporary_directory.name)

        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username='owner', password='password'
        )
        self.other = user_model.objects.create_user(
            username='other', password='password'
        )
        self.admin = user_model.objects.create_superuser(
            username='admin', password='password'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.public_client = APIClient()
        self.list_url = '/api/skill-hub/skills/'

    def upload(
        self,
        name='demo-skill',
        version='v1',
        description='初始说明',
        tags=None,
        client=None,
        content=None,
        filename='SKILL.md',
    ):
        payload = {
            'file': SimpleUploadedFile(
                filename,
                content if content is not None else make_skill_md(name, description),
            ),
            'version': version,
        }
        if tags is not None:
            payload['tags'] = json.dumps(tags, ensure_ascii=False)
        return (client or self.client).post(
            self.list_url, payload, format='multipart'
        )

    def stored_files(self):
        return [path for path in self.root.rglob('*') if path.is_file()]

    def test_business_endpoints_require_auth_while_discovery_is_public(self):
        self.assertEqual(self.public_client.get(self.list_url).status_code, 401)
        self.assertEqual(
            self.public_client.post(
                '/api/skill-hub/skills/validate/', {}, format='multipart'
            ).status_code,
            401,
        )
        response = self.public_client.get('/.well-known/skills/index.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'skills': []})
        self.assertEqual(
            self.public_client.get(
                '/api/skill-hub/skills/missing/download/'
            ).status_code,
            404,
        )

    def test_validate_reads_metadata_without_persisting(self):
        response = self.client.post(
            '/api/skill-hub/skills/validate/',
            {'file': SimpleUploadedFile('SKILL.md', make_skill_md())},
            format='multipart',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], 0)
        self.assertEqual(response.data['data']['name'], 'demo-skill')
        self.assertEqual(response.data['data']['description'], '初始说明')
        self.assertEqual(response.data['data']['source_type'], 'skill_md')
        self.assertTrue(response.data['data']['valid'])
        self.assertEqual(Skill.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

        invalid = self.client.post(
            '/api/skill-hub/skills/validate/',
            {
                'file': SimpleUploadedFile(
                    'SKILL.md', make_skill_md(name='Invalid_Name')
                )
            },
            format='multipart',
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(invalid.data['data']['valid'])
        self.assertTrue(invalid.data['data']['errors'])

    def test_upload_creates_normalized_zip_and_version_list(self):
        response = self.upload(version='release-1', tags=['Ops'])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['version'], 'release-1')
        self.assertEqual(response.data['data']['uploaded_by']['username'], 'owner')
        skill = Skill.objects.get(name='demo-skill')
        version = skill.versions.get()
        self.assertEqual(skill.owner, self.owner)
        self.assertEqual(skill.tags, ['Ops'])
        self.assertEqual(version.description, '初始说明')
        path = self.root / version.storage_key
        self.assertTrue(path.is_file())
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.namelist(), ['demo-skill/SKILL.md'])
            self.assertEqual(
                archive.read('demo-skill/SKILL.md'), make_skill_md()
            )

        list_response = self.client.get(self.list_url)
        self.assertEqual(list_response.status_code, 200)
        item = list_response.data['data']['items'][0]
        self.assertEqual(item['current_version'], 'release-1')
        self.assertEqual(item['description'], '初始说明')
        self.assertTrue(item['can_manage'])

        versions_response = self.client.get(
            '/api/skill-hub/skills/demo-skill/versions/'
        )
        self.assertEqual(versions_response.status_code, 200)
        items = versions_response.data['data']['items']
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['is_current'])

    def test_zip_upload_supports_public_discovery_and_download(self):
        response = self.upload(
            filename='skill.zip',
            content=make_skill_zip(),
            description='ignored',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['description'], '压缩包说明')
        self.assertEqual(response.data['data']['source_type'], 'archive')
        self.assertEqual(
            response.data['data']['files'], ['SKILL.md', 'scripts/run.txt']
        )

        index = self.public_client.get('/.well-known/skills/index.json')
        self.assertEqual(index.status_code, 200)
        self.assertEqual(
            index.json(),
            {
                'skills': [
                    {
                        'name': 'demo-skill',
                        'description': '压缩包说明',
                        'files': ['SKILL.md', 'scripts/run.txt'],
                    }
                ]
            },
        )
        skill_md = self.public_client.get(
            '/.well-known/skills/demo-skill/SKILL.md'
        )
        self.assertEqual(skill_md.status_code, 200)
        self.assertTrue(skill_md['Content-Type'].startswith('text/markdown'))
        self.assertEqual(skill_md.content, make_skill_md(description='压缩包说明'))
        resource = self.public_client.get(
            '/.well-known/skills/demo-skill/scripts/run.txt'
        )
        self.assertEqual(resource.status_code, 200)
        self.assertEqual(resource.content, b'run content')
        self.assertEqual(
            self.public_client.get(
                '/.well-known/skills/demo-skill/missing.txt'
            ).status_code,
            404,
        )

        download = self.public_client.get(
            '/api/skill-hub/skills/demo-skill/download/'
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/zip')
        self.assertEqual(int(download['Content-Length']), len(download.content))
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertEqual(
                archive.read('demo-skill/scripts/run.txt'), b'run content'
            )
        head = self.public_client.head(
            '/api/skill-hub/skills/demo-skill/download/'
        )
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')

    def test_new_version_changes_published_content_and_preserves_history(self):
        self.upload(version='v1', description='旧版说明')
        skill = Skill.objects.get(name='demo-skill')
        old_updated_at = skill.updated_at

        response = self.upload(version='v2', description='新版说明')
        self.assertEqual(response.status_code, 201)
        skill.refresh_from_db()
        self.assertGreater(skill.updated_at, old_updated_at)

        item = self.client.get(self.list_url).data['data']['items'][0]
        self.assertEqual(item['current_version'], 'v2')
        self.assertEqual(item['description'], '新版说明')
        self.assertEqual(item['version_count'], 2)
        latest = self.public_client.get(
            '/.well-known/skills/demo-skill/SKILL.md'
        )
        self.assertEqual(latest.content, make_skill_md(description='新版说明'))
        old = self.public_client.get(
            '/api/skill-hub/skills/demo-skill/versions/v1/download/'
        )
        with zipfile.ZipFile(io.BytesIO(old.content)) as archive:
            self.assertEqual(
                archive.read('demo-skill/SKILL.md'),
                make_skill_md(description='旧版说明'),
            )
        versions = self.client.get(
            '/api/skill-hub/skills/demo-skill/versions/'
        ).data['data']['items']
        self.assertEqual([item['version'] for item in versions], ['v2', 'v1'])
        self.assertEqual([item['is_current'] for item in versions], [True, False])

    def test_historical_version_publish_uses_name_and_updates_published_content(self):
        self.upload(version='v1', description='旧版说明')
        self.upload(version='v2', description='新版说明')

        response = self.client.post(
            '/api/skill-hub/skills/demo-skill/versions/v1/publish/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['version'], 'v1')
        self.assertTrue(response.data['data']['is_current'])
        item = self.client.get(self.list_url).data['data']['items'][0]
        self.assertEqual(item['current_version'], 'v1')
        self.assertEqual(item['description'], '旧版说明')
        index = self.public_client.get('/.well-known/skills/index.json').json()
        self.assertEqual(index['skills'][0]['description'], '旧版说明')
        discovered = self.public_client.get(
            '/.well-known/skills/demo-skill/SKILL.md'
        )
        self.assertEqual(discovered.content, make_skill_md(description='旧版说明'))
        download = self.public_client.get(
            '/api/skill-hub/skills/demo-skill/download/'
        )
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertEqual(
                archive.read('demo-skill/SKILL.md'),
                make_skill_md(description='旧版说明'),
            )
        versions = self.client.get(
            '/api/skill-hub/skills/demo-skill/versions/'
        ).data['data']['items']
        self.assertEqual([item['is_current'] for item in versions], [False, True])

    def test_publish_and_tag_edit_check_permissions_and_missing_versions(self):
        self.upload(version='v1')
        self.upload(version='v2')
        other_client = self._client_for(self.other)
        publish_url = '/api/skill-hub/skills/demo-skill/versions/v1/publish/'
        detail_url = '/api/skill-hub/skills/demo-skill/'

        self.assertEqual(other_client.post(publish_url).status_code, 403)
        self.assertEqual(
            other_client.patch(detail_url, {'tags': ['其他']}, format='json').status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                '/api/skill-hub/skills/demo-skill/versions/missing/publish/'
            ).status_code,
            404,
        )
        admin_client = self._client_for(self.admin)
        self.assertEqual(admin_client.post(publish_url).status_code, 200)
        self.assertEqual(
            admin_client.patch(detail_url, {'tags': []}, format='json').status_code,
            200,
        )

    def test_tag_edit_normalizes_clears_and_preserves_readonly_metadata(self):
        self.upload(version='v1', description='发布说明', tags=['初始'])
        detail_url = '/api/skill-hub/skills/demo-skill/'

        response = self.client.patch(
            detail_url, {'tags': [' Ops ', 'ops', '值班']}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['tags'], ['Ops', '值班'])
        self.assertEqual(response.data['data']['name'], 'demo-skill')
        self.assertEqual(response.data['data']['description'], '发布说明')

        response = self.client.patch(detail_url, {'tags': []}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['tags'], [])
        self.assertEqual(
            self.client.patch(detail_url, {}, format='json').status_code, 400
        )
        self.assertEqual(
            self.client.patch(detail_url, {'tags': ['']}, format='json').status_code,
            400,
        )

    def test_duplicate_version_and_non_owner_upload_are_rejected(self):
        self.upload()
        original_files = self.stored_files()

        duplicate = self.upload(description='不能覆盖')
        self.assertEqual(duplicate.status_code, 409)
        non_owner = self.upload(version='v2', client=self._client_for(self.other))
        self.assertEqual(non_owner.status_code, 403)
        self.assertEqual(SkillVersion.objects.count(), 1)
        self.assertEqual(self.stored_files(), original_files)

        admin_response = self.upload(
            version='v2', description='管理员版本', client=self._client_for(self.admin)
        )
        self.assertEqual(admin_response.status_code, 201)
        self.assertEqual(SkillVersion.objects.count(), 2)

    def test_tags_can_be_filtered_summarized_retained_and_cleared(self):
        self.upload(tags=[' Ops ', 'ops', '值班'])
        self.upload(name='other-skill', tags=['Ops'])

        filtered = self.client.get(self.list_url, {'tag': ['Ops', '值班']})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.data['data']['total'], 1)
        self.assertEqual(filtered.data['data']['items'][0]['name'], 'demo-skill')
        tags = self.client.get('/api/skill-hub/skills/tags/').data['data']['items']
        self.assertEqual(
            tags,
            [
                {'name': 'Ops', 'count': 2},
                {'name': '值班', 'count': 1},
            ],
        )

        self.upload(version='v2')
        skill = Skill.objects.get(name='demo-skill')
        self.assertEqual(skill.tags, ['Ops', '值班'])
        self.upload(version='v3', tags=[])
        skill.refresh_from_db()
        self.assertEqual(skill.tags, [])

    def test_delete_current_version_falls_back_and_last_delete_removes_skill(self):
        self.upload(version='v1', description='旧版说明')
        self.upload(version='v2', description='新版说明')
        skill = Skill.objects.get(name='demo-skill')
        storage_dir = self.root / str(skill.uuid)

        response = self.client.delete(
            '/api/skill-hub/skills/demo-skill/versions/v2/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.public_client.get(
                '/.well-known/skills/demo-skill/SKILL.md'
            ).content,
            make_skill_md(description='旧版说明'),
        )
        self.assertEqual(SkillVersion.objects.count(), 1)

        response = self.client.delete(
            '/api/skill-hub/skills/demo-skill/versions/v1/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Skill.objects.filter(name='demo-skill').exists())
        self.assertFalse(storage_dir.exists())
        self.assertEqual(
            self.public_client.get('/.well-known/skills/index.json').json(),
            {'skills': []},
        )

    def test_only_owner_or_superuser_can_delete(self):
        self.upload()
        response = self._client_for(self.other).delete(
            '/api/skill-hub/skills/demo-skill/'
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Skill.objects.filter(name='demo-skill').exists())

        response = self._client_for(self.admin).delete(
            '/api/skill-hub/skills/demo-skill/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Skill.objects.filter(name='demo-skill').exists())

    def test_invalid_and_oversized_uploads_have_no_side_effects(self):
        invalid = self.upload(version='')
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('errors', invalid.data)
        self.assertEqual(Skill.objects.count(), 0)

        with patch('skill_hub.services.MAX_UPLOAD_BYTES', 4):
            oversized = self.upload(version='v1')
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(Skill.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_database_failure_cleans_saved_file(self):
        with patch(
            'skill_hub.services.SkillVersion.objects.create',
            side_effect=IntegrityError('duplicate'),
        ):
            response = self.upload()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Skill.objects.count(), 0)
        self.assertEqual(SkillVersion.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client
