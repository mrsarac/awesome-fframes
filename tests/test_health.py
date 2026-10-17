import importlib.util
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"scripts"))

spec = importlib.util.spec_from_file_location('health', Path(__file__).parents[1]/'scripts/health.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def test_two_consecutive_weeks_and_same_week_retry(self):
        url = 'https://example.org/project'
        state = m.update_state({}, {url}, {url}, '2026-W42')
        self.assertEqual(state[url]['streak'], 1)
        retry = m.update_state(state, {url}, {url}, '2026-W42')
        self.assertEqual(retry[url]['streak'], 1)
        next_week = m.update_state(retry, {url}, {url}, '2026-W43')
        self.assertEqual(next_week[url]['streak'], 2)
        gap = m.update_state(state, {url}, {url}, '2026-W44')
        self.assertEqual(gap[url]['streak'], 1)
        healthy = m.update_state(next_week, {url}, set(), '2026-W43')
        self.assertEqual(healthy[url]['streak'], 0)

    def test_year_boundary_is_consecutive(self):
        url = 'https://example.org/x'
        state = {url: {'week': '2026-W53', 'streak': 1}}
        self.assertEqual(m.update_state(state, {url}, {url}, '2027-W01')[url]['streak'], 2)

    def test_removal_targets_entries_and_keeps_other_content(self):
        text = '# List\n\n## Bindings\n\n- [Bad](https://github.com/a/b) - Example.\n\n## Community\n\n- [Good](https://example.org/ok) - Working.\n'
        result = m.remove_entries(text, {'https://github.com/a/b'})
        self.assertNotIn('[Bad]', result)
        self.assertNotIn('## Bindings', result)
        self.assertNotIn('(#bindings)', result)
        self.assertIn('[Good]', result)
        self.assertTrue(result.startswith('# List'))

    def test_lychee_failure_urls_are_read_without_guessing(self):
        report = {'error_map': {'readme.md': [{'url': 'https://example.org/fail', 'status': {'code': 404}}]}}
        self.assertEqual(m.broken_urls(report), {'https://example.org/fail'})
        with self.assertRaises(ValueError):m.broken_urls({'unexpected': 'shape'})


class Integration(unittest.TestCase):
    def test_archived_repo_is_removed_but_dry_run_changes_nothing(self):
        import tempfile, json
        from datetime import datetime, timezone
        class Client:
            def get(self, url):
                return {'archived': True, 'stargazers_count':12, 'pushed_at':'2026-10-01T00:00:00Z', 'license':{'spdx_id':'MIT'}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);readme=root/'readme.md';state=root/'state.json';report=root/'lychee.json'
            readme.write_text('# List\n\n## Community\n\n- [Archived](https://github.com/owner/archive) - Old project.\n')
            state.write_text('{}');report.write_text(json.dumps({'error_map':{}, 'timeout_map':{}}))
            original=readme.read_text()
            result=m.run(Client(),readme,state,report,datetime(2026,10,17,tzinfo=timezone.utc),True)
            self.assertEqual(len(result['removed']),1)
            self.assertEqual(readme.read_text(),original)
            self.assertEqual(state.read_text(),'{}')
            m.run(Client(),readme,state,report,datetime(2026,10,17,tzinfo=timezone.utc),False)
            self.assertNotIn('[Archived]',readme.read_text())

    def test_multiple_empty_sections_keep_correct_contents(self):
        text='# List\n\n## Contents\n\n- [Bindings](#bindings)\n- [Crates](#crates)\n- [Community](#community)\n\n## Bindings\n\n- [One](https://example.org/one) - Old.\n\n## Crates\n\n- [Two](https://example.org/two) - Old.\n\n## Community\n\n- [Three](https://example.org/three) - Good.\n'
        result=m.remove_entries(text, {'https://example.org/one','https://example.org/two'})
        self.assertNotIn('Bindings',result)
        self.assertNotIn('Crates',result)
        self.assertIn('[Community](#community)',result)
        self.assertIn('[Three]',result)
