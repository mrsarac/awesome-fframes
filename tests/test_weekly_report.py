import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('weekly_report',Path(__file__).parents[1]/'scripts/weekly_report.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def test_pending_change_keeps_sources_on_a_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'lychee').mkdir();(root/'.github').mkdir()
            (root/'lychee/base.md').write_text('# List\n')
            (root/'readme.md').write_text('- [New](https://github.com/owner/new) - Example.\n')
            (root/'.github/link-state.json').write_text('{}')
            (root/'lychee/health.json').write_text('{"removed":[]}')
            proof={'url':'https://github.com/owner/new','stargazers_count':12,'license_file':'https://github.com/owner/new/blob/main/LICENSE','pushed_at':'2026-10-17T00:00:00Z','crate_downloads':0}
            (root/'lychee/candidates.json').write_text(json.dumps({'added':[proof]}))
            m.build(root)
            (root/'lychee/candidates.json').write_text('{"added":[]}')
            m.build(root)
            body=(root/'lychee/pr-body.md').read_text()
            self.assertIn('Stars: 12',body)
            self.assertIn('LICENSE',body)
            self.assertIn('2026-10-17',body)
            self.assertEqual(len(json.loads((root/'.github/weekly-sources.json').read_text())),1)
            (root/'lychee/base.md').write_text((root/'readme.md').read_text())
            m.build(root)
            self.assertEqual(json.loads((root/'.github/weekly-sources.json').read_text()),{})

    def test_unproven_change_stops_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'lychee').mkdir();(root/'.github').mkdir()
            (root/'lychee/base.md').write_text('# List\n')
            (root/'readme.md').write_text('- [New](https://github.com/owner/new) - Example.\n')
            (root/'lychee/candidates.json').write_text('{"added":[]}')
            (root/'lychee/health.json').write_text('{"removed":[]}')
            with self.assertRaises(ValueError):m.build(root)
