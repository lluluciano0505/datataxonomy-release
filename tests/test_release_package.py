import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_release import ROOT_FILES, build_release


class ReleasePackageTests(unittest.TestCase):
    def make_source(self, root):
        for name in ROOT_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('release fixture')
        (root / 'taxonomies/default.yaml').write_text('generic taxonomy')
        for name in ['.env', 'config.yaml', 'taxonomy.yaml', 'saved_configs.json',
                     'outputs/private.csv', 'configs/private.yaml', '.git/config',
                     'taxonomies/private.yaml', 'core/__pycache__/cached.py',
                     'docs/private.docx', 'release/old/private.txt']:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private fixture')
        for name in ['core/main.py', 'tests/fixtures/api_smoke/brief.txt',
                     'demo_data/synthetic.csv', 'docs/review_rules.rst']:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture')

    def test_exports_current_files_and_default_taxonomy_without_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            self.make_source(root)
            destination = Path(directory) / 'release'
            manifest = build_release(destination, root)
            self.assertEqual((destination / 'taxonomy.yaml').read_text(), 'generic taxonomy')
            self.assertEqual((destination / 'core/main.py').read_text(), 'public fixture')
            self.assertTrue((destination / 'demo_data/synthetic.csv').exists())
            self.assertTrue((destination / 'tests/fixtures/api_smoke/brief.txt').exists())
            self.assertFalse(any('private fixture' in path.read_text() for path in destination.rglob('*') if path.is_file()))
            self.assertEqual(json.loads((destination / 'release-manifest.json').read_text()), manifest)
            with self.assertRaises(ValueError):
                build_release(destination, root)

    def test_rejects_symlink_sources_and_source_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            self.make_source(root)
            (root / 'core/leak.py').symlink_to(root / '.env')
            with self.assertRaises(ValueError):
                build_release(Path(directory) / 'release', root)
            with self.assertRaises(ValueError):
                build_release(root, root)
