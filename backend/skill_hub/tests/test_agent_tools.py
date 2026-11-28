from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase, override_settings

from skill_hub.agent import create_skill_hub_agent
from skill_hub.agent.tools import generate_skill_install_prompt, list_available_skills
from skill_hub.models import Skill, SkillVersion


class SkillHubToolTests(TestCase):
    def create_skill(
        self,
        name,
        *,
        description='Skill description',
        tags=None,
        status=SkillVersion.Status.READY,
        version='v1',
    ):
        skill = Skill.objects.create(name=name, tags=tags or [])
        published = SkillVersion.objects.create(
            skill=skill,
            version=version,
            description=description,
            source_type=SkillVersion.SourceType.SKILL_MD,
            original_filename='SKILL.md',
            storage_key=f'tests/{name}-{version}.zip',
            archive_name=f'{name}-{version}.zip',
            size_bytes=100,
            sha256='a' * 64,
            file_count=1,
            files=['SKILL.md'],
            status=status,
        )
        skill.published_version = published
        skill.save(update_fields=['published_version'])
        return skill

    def test_list_available_skills_returns_only_downloadable_published_versions(self):
        self.create_skill(
            'second-skill',
            description='Second published description',
            tags=['Ops'],
        )
        self.create_skill('first-skill', description='First description')
        Skill.objects.create(name='empty-skill')
        self.create_skill('deleting-skill', status=SkillVersion.Status.DELETING)

        result = async_to_sync(list_available_skills)()

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total'], 2)
        self.assertEqual(
            [item['name'] for item in result['items']],
            ['first-skill', 'second-skill'],
        )
        self.assertEqual(
            result['items'][1],
            {
                'name': 'second-skill',
                'description': 'Second published description',
                'current_version': 'v1',
                'source_type': 'skill_md',
                'tags': ['Ops'],
                'files': ['SKILL.md'],
            },
        )

    @override_settings(FRONTEND_URL='https://skills.example.com/')
    def test_generate_prompt_validates_sorts_and_uses_default_source(self):
        self.create_skill('second-skill')
        self.create_skill('first-skill')

        result = async_to_sync(generate_skill_install_prompt)(
            ['second-skill', 'first-skill', 'second-skill']
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['source_url'], 'https://skills.example.com')
        self.assertEqual(
            [item['name'] for item in result['skills']],
            ['first-skill', 'second-skill'],
        )
        self.assertIn(
            'npx skills add "https://skills.example.com" '
            '--skill first-skill --skill second-skill '
            '-a "<你识别出的Agent类型>" -y',
            result['prompt'],
        )
        self.assertIn(
            'https://skills.example.com/.well-known/skills/index.json',
            result['prompt'],
        )
        self.assertIn('skills-lock.json', result['prompt'])
        self.assertIn('.gitignore', result['prompt'])

    def test_generate_prompt_rejects_unknown_or_unavailable_skills(self):
        self.create_skill('available-skill')

        result = async_to_sync(generate_skill_install_prompt)(
            ['available-skill', 'missing-skill'],
            'http://skill-hub.example.com',
        )

        self.assertEqual(result['status'], 'error')
        self.assertIn('missing-skill', result['error_message'])
        self.assertNotIn('prompt', result)

    def test_generate_prompt_rejects_invalid_names_and_source_urls(self):
        self.create_skill('demo-skill')
        invalid_names = ([], 'demo-skill', [''])

        for names in invalid_names:
            with self.subTest(names=names):
                result = async_to_sync(generate_skill_install_prompt)(names)
                self.assertEqual(result['status'], 'error')

        result = async_to_sync(generate_skill_install_prompt)(
            ['demo-skill'],
            'file:///tmp/skills',
        )
        self.assertEqual(result['status'], 'error')
        self.assertIn('HTTP(S)', result['error_message'])


class SkillHubAgentTests(SimpleTestCase):
    @patch('skill_hub.agent.subagent.Agent')
    def test_sub_agent_contains_only_the_two_skill_hub_tools(self, agent_class):
        model = object()

        result = create_skill_hub_agent(model)

        self.assertIs(result, agent_class.return_value)
        kwargs = agent_class.call_args.kwargs
        self.assertEqual(kwargs['name'], 'skill_hub_assistant')
        self.assertIs(kwargs['model'], model)
        self.assertEqual(
            [tool.__name__ for tool in kwargs['tools']],
            ['list_available_skills', 'generate_skill_install_prompt'],
        )
        self.assertIn('不要执行安装命令', kwargs['instruction'])
