import io
import stat
import tarfile
import zipfile

from django.test import SimpleTestCase

from skill_hub.archives import collect_skill


SKILL_MD = b'---\nname: demo-skill\ndescription: text\n---\n\nbody\n'


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def make_tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for path, content in entries.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class SkillArchiveTests(SimpleTestCase):
    def test_single_skill_md_is_supported_case_insensitively(self):
        collected = collect_skill('SKILL.MD', SKILL_MD)

        self.assertEqual(collected.source_type, 'skill_md')
        self.assertEqual(collected.files, {'SKILL.md': SKILL_MD})
        self.assertEqual(collected.errors, [])

    def test_zip_uses_skill_root_and_ignores_siblings(self):
        data = make_zip(
            {
                'demo-skill/SKILL.md': SKILL_MD,
                'demo-skill/scripts/run.sh': b'echo ok\n',
                'other/ignored.txt': b'ignored',
            }
        )

        collected = collect_skill('skill.zip', data)

        self.assertEqual(collected.source_type, 'archive')
        self.assertEqual(collected.directory, 'demo-skill')
        self.assertEqual(
            collected.files,
            {
                'SKILL.md': SKILL_MD,
                'scripts/run.sh': b'echo ok\n',
            },
        )
        self.assertEqual(collected.errors, [])

    def test_tar_gz_is_supported(self):
        data = make_tar({'demo-skill/SKILL.md': SKILL_MD})

        collected = collect_skill('skill.tar.gz', data)

        self.assertEqual(collected.directory, 'demo-skill')
        self.assertEqual(collected.files, {'SKILL.md': SKILL_MD})
        self.assertEqual(collected.errors, [])

    def test_multiple_skill_files_and_path_traversal_are_rejected(self):
        cases = {
            'multiple': make_zip(
                {
                    'one/SKILL.md': SKILL_MD,
                    'two/SKILL.md': SKILL_MD,
                }
            ),
            'traversal': make_zip(
                {
                    'demo-skill/SKILL.md': SKILL_MD,
                    '../escape.txt': b'escape',
                }
            ),
        }

        for label, data in cases.items():
            with self.subTest(label=label):
                collected = collect_skill('skill.zip', data)
                self.assertEqual(collected.files, {})
                self.assertEqual(collected.errors[0].code, 'invalid_archive')

    def test_zip_symlink_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('demo-skill/SKILL.md', SKILL_MD)
            link = zipfile.ZipInfo('demo-skill/link')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, '/etc/passwd')

        collected = collect_skill('skill.zip', buffer.getvalue())

        self.assertEqual(collected.files, {})
        self.assertIn('Symbolic links', collected.errors[0].message)

    def test_unsupported_and_corrupt_files_return_validation_errors(self):
        for filename, data in (
            ('skill.pdf', SKILL_MD),
            ('skill.zip', b'not an archive'),
        ):
            with self.subTest(filename=filename):
                collected = collect_skill(filename, data)
                self.assertEqual(collected.files, {})
                self.assertTrue(collected.errors)
