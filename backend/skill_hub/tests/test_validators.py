from django.test import SimpleTestCase

from skill_hub.validators import normalize_tags, parse_skill_md, validate_version


def make_skill_md(name='demo-skill', description='演示说明'):
    return (
        f'---\nname: {name}\ndescription: {description}\n---\n\n具体操作步骤。\n'
    ).encode()


class SkillMetadataValidatorTests(SimpleTestCase):
    def test_valid_frontmatter_returns_stripped_metadata(self):
        metadata = parse_skill_md(
            make_skill_md(description='  从文件读取的描述  ')
        )

        self.assertTrue(metadata.valid)
        self.assertEqual(metadata.name, 'demo-skill')
        self.assertEqual(metadata.description, '从文件读取的描述')
        self.assertEqual(metadata.warnings, [])

    def test_invalid_frontmatter_and_encoding_return_errors(self):
        cases = {
            'missing_frontmatter': b'name: demo-skill',
            'duplicate_key': (
                b'---\nname: demo-skill\nname: other\ndescription: text\n---\nbody'
            ),
            'invalid_name': make_skill_md(name='Invalid_Name'),
            'empty_description': make_skill_md(description='   '),
            'invalid_utf8': b'\xff\xfe',
            'nul_byte': b'---\nname: demo-skill\x00\n---\nbody',
            'unhashable_key': b'---\n? [a, b]\n: value\n---\nbody',
        }

        for label, content in cases.items():
            with self.subTest(label=label):
                metadata = parse_skill_md(content)
                self.assertFalse(metadata.valid)
                self.assertTrue(metadata.errors)

    def test_empty_body_is_only_a_warning(self):
        metadata = parse_skill_md(
            b'---\nname: demo-skill\ndescription: text\n---\n'
        )

        self.assertTrue(metadata.valid)
        self.assertEqual(metadata.warnings[0].code, 'empty_body')

    def test_version_and_tag_rules(self):
        for version in ('1', 'v1.2.3', 'release_candidate-2'):
            with self.subTest(version=version):
                self.assertIsNone(validate_version(version))
        for version in ('', '.hidden', 'a/b', 'a' * 33):
            with self.subTest(version=version):
                self.assertIsNotNone(validate_version(version))

        tags, errors = normalize_tags([' Ops ', 'ops', '值班'])
        self.assertEqual(tags, ['Ops', '值班'])
        self.assertEqual(errors, [])
        self.assertEqual(normalize_tags(None), ([], []))
        self.assertTrue(normalize_tags('Ops')[1])
        self.assertTrue(normalize_tags([''])[1])
        self.assertTrue(normalize_tags(['tag'] * 21)[1])
