import importlib.util
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('candidates', Path(__file__).parents[1] / 'scripts/candidates.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Client:
    def __init__(self):
        self.writes = []
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if 'search/repositories' in path:
            return {'items': [{'full_name': 'other/new', 'html_url': 'https://github.com/other/new', 'description': 'A useful project'}], 'incomplete_results': False, 'total_count': 1}
        if 'reverse_dependencies' in path:
            return {'dependencies': [{'version_id': 7}], 'versions': [{'id': 7, 'crate': 'new-crate'}], 'meta': {'total': 1}}
        if path.endswith('/crates/new-crate'):
            return {'crate': {'repository': 'https://github.com/other/new', 'downloads':100}}
        if path.endswith('/license'):
            return {'type':'file','html_url':'https://github.com/other/new/blob/main/LICENSE'}
        if '/commits?' in path:
            return [{'commit': {'committer': {'date': '2024-01-01T00:00:00Z'}}}]
        if '/issues?' in path:
            return []
        if '/repos/' in path:
            return {'fork':False,'archived':False,'description':'Useful video tools','pushed_at':'2026-10-01T00:00:00Z','stargazers_count':0,'topics':[]}
        raise AssertionError(path)

    def write(self, method, path, data):
        self.writes.append((method, path, data))


class Tests(unittest.TestCase):
    def readme(self, root):
        path = Path(root) / 'readme.md'
        path.write_text('# List\n\n## Contents\n\n- [Community](#community)\n\n## Community\n\n- [Existing](https://github.com/owner/existing/tree/main/demo) - Example.\n')
        return path

    def test_month_boundary_and_leap_year(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.assertFalse(m.is_stale('2025-10-17T00:00:00Z', now))
        self.assertTrue(m.is_stale('2025-10-16T23:59:59Z', now))
        leap = datetime(2024, 2, 29, tzinfo=timezone.utc)
        self.assertFalse(m.is_stale('2023-02-28T00:00:00Z', leap))

    def test_dry_run_deduplicates_sources_and_never_writes(self):
        with tempfile.TemporaryDirectory() as root:
            client = Client()
            body = m.run(client, self.readme(root), 'mrsarac/awesome-fframes', datetime(2026, 10, 17, tzinfo=timezone.utc), True)
            self.assertEqual(body.count('https://github.com/other/new'), 1)
            self.assertIn('12 months', body)
            self.assertIn('owner/existing', body)
            self.assertFalse(client.writes)
            self.assertFalse(any('/issues?' in p for p in client.calls))

    def test_existing_week_issue_is_updated_even_if_closed(self):
        with tempfile.TemporaryDirectory() as root:
            client = Client(); get = client.get
            def existing(path):
                if '/issues?' in path:
                    return [{'number': 4, 'body': '<!-- candidates:2026-W42 -->', 'state': 'closed'}]
                return get(path)
            client.get = existing
            m.run(client, self.readme(root), 'mrsarac/awesome-fframes', datetime(2026, 10, 17, tzinfo=timezone.utc), False)
            self.assertEqual(client.writes[0][0], 'PATCH')
            self.assertTrue(client.writes[0][1].endswith('/issues/4'))
            self.assertNotIn('state', client.writes[0][2])

    def test_missing_week_issue_is_created_once(self):
        with tempfile.TemporaryDirectory() as root:
            client = Client()
            m.run(client, self.readme(root), 'mrsarac/awesome-fframes', datetime(2026, 10, 17, tzinfo=timezone.utc), False)
            self.assertEqual(len(client.writes), 1)
            self.assertEqual(client.writes[0][0], 'POST')
            self.assertEqual(client.writes[0][2]['title'], 'Candidates (week 42)')

    def test_incomplete_search_is_an_error_not_a_partial_issue(self):
        with tempfile.TemporaryDirectory() as root:
            client = Client(); get = client.get
            client.get = lambda path: {'items': [], 'incomplete_results': True, 'total_count': 0} if 'search/repositories' in path else get(path)
            with self.assertRaises(m.APIError):
                m.run(client, self.readme(root), 'mrsarac/awesome-fframes', datetime.now(timezone.utc), False)
            self.assertFalse(client.writes)

    def test_existing_repo_is_not_proposed_from_another_url(self):
        self.assertEqual(m.repo_name('https://github.com/Owner/Existing/tree/main/demo'), 'owner/existing')
        self.assertIsNone(m.repo_name('https://example.org/Owner/Existing'))


if __name__ == '__main__':
    unittest.main()

class StrictCriteria(unittest.TestCase):
    def test_thresholds_require_all_safety_fields(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        good = {'fork': False, 'archived': False, 'description': 'Useful video tools', 'pushed_at': '2026-10-01T00:00:00Z', 'stargazers_count': 10, 'license_file': 'https://github.com/owner/repo/blob/main/LICENSE', 'crate_downloads': 0}
        self.assertEqual(m.rejection_reasons(good, now), [])
        for key, value in [('fork', True), ('archived', True), ('description', ''), ('license_file', None), ('pushed_at', '2025-01-01T00:00:00Z'), ('stargazers_count', 9)]:
            with self.subTest(key=key):
                self.assertTrue(m.rejection_reasons(dict(good, **{key:value}), now))
        self.assertFalse(m.rejection_reasons(dict(good, stargazers_count=0, crate_downloads=100), now))
        self.assertTrue(m.rejection_reasons(dict(good, stargazers_count=0, crate_downloads=99), now))

    def test_descriptions_and_section_are_deterministic(self):
        text = m.clean_description('🎬 **fast** video tool! ' + 'word ' * 40)
        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith('.'))
        self.assertTrue(text[0].isupper())
        self.assertNotIn('🎬', text)
        self.assertNotIn('*', text)
        self.assertEqual(m.section_for({'from_crates': True}), 'Crates')
        self.assertEqual(m.section_for({'name': 'owner/video-agent', 'topics': []}), 'Agent skills')
        self.assertEqual(m.section_for({'name': 'owner/video', 'topics': []}), 'Community')

class EmptyRepository(unittest.TestCase):
    def test_empty_search_result_is_reviewed_without_aborting(self):
        client=Client();get=client.get
        def empty(path):
            if '/other/new/commits?' in path:raise m.APIError('Empty repository',409)
            return get(path)
        client.get=empty
        with tempfile.TemporaryDirectory() as root:
            path=Tests().readme(root)
            body=m.run(client,path,'mrsarac/awesome-fframes',datetime(2026,10,17,tzinfo=timezone.utc),True)
            self.assertIn('12 months',body)
