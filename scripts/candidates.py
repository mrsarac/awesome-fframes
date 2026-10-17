#!/usr/bin/env python3
"""Discover review candidates without modifying the curated list."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class APIError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, token):
        self.token = token

    def request(self, url, method='GET', data=None):
        headers = {'User-Agent': 'awesome-fframes-maintenance (github.com/mrsarac/awesome-fframes)'}
        if urlparse(url).hostname == 'api.github.com':
            headers.update({'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        payload = None if data is None else json.dumps(data).encode()
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        for attempt in range(2):
            try:
                with urlopen(Request(url, data=payload, headers=headers, method=method), timeout=20) as response:
                    return json.load(response)
            except HTTPError as exc:
                if method == 'GET' and exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(1)
                    continue
                raise APIError('HTTP ' + str(exc.code) + ': ' + urlparse(url).path, exc.code) from exc
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                raise APIError('Request failed: ' + urlparse(url).hostname) from exc
        raise APIError('Request retry exhausted')

    def get(self, url):
        return self.request(url)

    def write(self, method, url, data):
        # Writes are never retried: the next run checks the weekly marker first.
        return self.request(url, method, data)


def repo_name(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'github.com':
        return None
    parts = parsed.path.strip('/').split('/')
    if len(parts) < 2:
        return None
    name = '/'.join(parts[:2]).removesuffix('.git').lower()
    return name if re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', name) else None


def is_stale(timestamp, now):
    try:
        cutoff = now.replace(year=now.year - 1)
    except ValueError:  # Leap day: twelve calendar months ends on February 28.
        cutoff = now.replace(year=now.year - 1, day=28)
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00')) < cutoff


def pages(client, url, key=None):
    for page in range(1, 11):
        data = client.get(url + ('&' if '?' in url else '?') + urlencode({'per_page': 100, 'page': page}))
        if isinstance(data, dict) and data.get('incomplete_results'):
            raise APIError('GitHub search was incomplete')
        items = data[key] if key else data
        if not isinstance(items, list):
            raise APIError('Unexpected API page shape')
        yield data, items
        if len(items) < 100:
            return
    raise APIError('Pagination exceeded the safety limit; review search coverage')


def listed_repos(readme):
    return {name for url in re.findall(r'^- \[[^\]]+\]\((https://[^)]+)\) - ', readme.read_text(), re.M)
            if (name := repo_name(url)) is not None}


def discover(client):
    found = {}
    for query in ['topic:fframes fork:false archived:false is:public', 'fframes in:name,description fork:false archived:false is:public']:
        print('Searching GitHub: ' + query, file=sys.stderr, flush=True)
        for _, items in pages(client, 'https://api.github.com/search/repositories?' + urlencode({'q': query}), 'items'):
            for item in items:
                name = repo_name(item['html_url'])
                if name:
                    found.setdefault(name, {'from_crates': False, 'crate_downloads': 0, 'crates': []})
    for page in range(1, 11):
        print('Reading crates.io reverse dependencies: page ' + str(page), file=sys.stderr, flush=True)
        data = client.get('https://crates.io/api/v1/crates/fframes/reverse_dependencies?' + urlencode({'page': page, 'per_page': 100}))
        dependencies = data['dependencies']
        version_ids = {dep['version_id'] for dep in dependencies}
        for version in data['versions']:
            if version['id'] not in version_ids:
                continue
            crate = version['crate']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', crate):
                raise APIError('Invalid crate identifier')
            details = client.get('https://crates.io/api/v1/crates/' + quote(crate, safe=''))
            name = repo_name(details['crate'].get('repository') or '')
            key = name or 'crate:' + crate
            record = found.setdefault(key, {'from_crates': True, 'crate_downloads': 0, 'crates': []})
            downloads = int(details['crate'].get('downloads', 0))
            record['from_crates'] = True
            record['crate_downloads'] = max(record['crate_downloads'], downloads)
            record['crates'].append({'name': crate, 'downloads': downloads})
        if page * 100 >= data['meta']['total']:
            return found
        if not dependencies:
            raise APIError('Reverse dependency pagination ended early')
    raise APIError('Reverse dependency pagination exceeded the safety limit')


def clean_description(raw):
    text = unicodedata.normalize('NFKC', raw or '')
    text = re.sub(r'<[^>]*>|https?://\S+', ' ', text)
    text = ''.join(c for c in text if unicodedata.category(c) not in ('So', 'Sk', 'Cs', 'Cf') and c not in '\ufe0e\ufe0f')
    text = re.sub(r'[\[\]`*_~|<>#]', '', text)
    text = ' '.join(text.split()).strip(' .!?:;,=-')
    if not text:
        return ''
    text = text[0].upper() + text[1:]
    if len(text) > 99:
        text = text[:99].rsplit(' ', 1)[0] or text[:99]
    return text.rstrip(' .!?:;,=-') + '.'


def section_for(record):
    if record.get('from_crates'):
        return 'Crates'
    words = record.get('name', '') + ' ' + ' '.join(record.get('topics', []))
    return 'Agent skills' if re.search('agent|skill', words, re.I) else 'Community'


def rejection_reasons(record, now):
    reasons = []
    if record.get('fork'):
        reasons.append('Fork')
    if record.get('archived'):
        reasons.append('Archived')
    if not record.get('license_file'):
        reasons.append('No license file')
    if not clean_description(record.get('description')):
        reasons.append('No usable description')
    pushed = record.get('pushed_at')
    if not pushed or datetime.fromisoformat(pushed.replace('Z', '+00:00')) < now - timedelta(days=180):
        reasons.append('No push in the last 180 days')
    if record.get('stargazers_count', 0) < 10 and record.get('crate_downloads', 0) < 100:
        reasons.append('Below 10 stars / 100 dependent-crate downloads')
    return reasons


def add_entries(text, additions):
    for record in additions:
        header = '## ' + record['section']
        if header not in text:
            # Health checks may have removed an empty section in a previous week.
            anchor = re.sub(r'[^a-z0-9 -]', '', record['section'].lower()).replace(' ', '-')
            contents_end = text.index('\n## ', text.index('## Contents') + 1)
            text = text[:contents_end].rstrip() + '\n- [' + record['section'] + '](#' + anchor + ')\n' + text[contents_end:]
            insertion = text.find('## Contributing')
            insertion = len(text) if insertion < 0 else insertion
            text = text[:insertion].rstrip() + '\n\n' + header + '\n\n' + text[insertion:]
        start = text.index(header + '\n') + len(header) + 1
        end = text.find('\n## ', start)
        end = len(text) if end < 0 else end
        text = text[:end].rstrip() + '\n' + record['line'] + '\n\n' + text[end:].lstrip('\n')
    return text.rstrip() + '\n'


def run(client, readme, repository, now, dry_run, report=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise APIError('Invalid destination repository')
    listed = listed_repos(readme)
    found = discover(client)
    unlisted = set(found) - listed - {repository.lower()}
    additions = []
    rejected = []
    stale = []
    for name in sorted(listed | unlisted):
        print('Checking metadata: ' + name, file=sys.stderr, flush=True)
        if name.startswith('crate:'):
            rejected.append({'name': name, 'reasons': ['No GitHub repository for license and health checks']})
            continue
        info = client.get('https://api.github.com/repos/' + name)
        commits = client.get('https://api.github.com/repos/' + name + '/commits?per_page=1')
        if not isinstance(commits, list):
            raise APIError('Unexpected commit response')
        if not commits or is_stale(commits[0]['commit']['committer']['date'], now):
            stale.append(name + ' (no commit in the last 12 months)')
        if name in listed:
            continue
        record = dict(info, **found[name], name=name)
        try:
            license_file = client.get('https://api.github.com/repos/' + name + '/license')
            record['license_file'] = license_file.get('html_url') if license_file.get('type') == 'file' else None
        except APIError as exc:
            if exc.status != 404:
                raise
            record['license_file'] = None
        reasons = rejection_reasons(record, now)
        if reasons:
            rejected.append({'name': name, 'reasons': reasons})
            continue
        description = clean_description(record['description'])
        # Avoid repeating an entry name at the start of its description.
        label = name.split('/')[1]
        if description.lower().startswith(label.lower()):
            description = clean_description(description[len(label):].lstrip(' :-')) or 'Resources for video projects.'
        record['section'] = section_for(record)
        record['url'] = 'https://github.com/' + name
        record['line'] = '- [' + label + '](' + record['url'] + ') - ' + description
        additions.append({k: record.get(k) for k in ('name', 'url', 'line', 'section', 'stargazers_count', 'license_file', 'pushed_at', 'crate_downloads', 'crates')})
    year, week, _ = now.isocalendar()
    marker = f'<!-- candidates:{year}-W{week:02d} -->'
    title = f'Candidates (week {week})'
    lines = [title, '', 'Entries below do not meet automatic inclusion criteria. Review is manual.', '', '## Rejected candidates', '']
    for item in rejected:
        name = item['name']
        url = 'https://crates.io/crates/' + name[6:] if name.startswith('crate:') else 'https://github.com/' + name
        lines.append('- ' + url + ' — ' + '; '.join(item['reasons']) + '.')
    if not rejected:
        lines.append('No rejected candidates.')
    lines.extend(['', '## Maintenance review', ''])
    lines.extend('- ' + name for name in stale)
    if not stale:
        lines.append('No entries older than 12 months found.')
    lines.extend(['', 'Checked at ' + now.isoformat() + '.', '', marker])
    body = '\n'.join(lines)
    if report is not None:
        report.update({'added': additions, 'rejected': rejected, 'stale': stale, 'checked_at': now.isoformat()})
    updated_readme = add_entries(readme.read_text(), additions) if additions else readme.read_text()
    if not dry_run:
        url = 'https://api.github.com/repos/' + repository + '/issues'
        matches = []
        for _, items in pages(client, url + '?state=all'):
            matches.extend(item for item in items if marker in (item.get('body') or '') and 'pull_request' not in item)
        if len(matches) > 1:
            raise APIError('Duplicate weekly issues already exist; manual review needed')
        if matches:
            client.write('PATCH', url + '/' + str(matches[0]['number']), {'body': body})
        else:
            client.write('POST', url, {'title': title, 'body': body})
        if additions:
            readme.write_text(updated_readme)
    preview = ['Eligible additions: ' + str(len(additions))]
    preview.extend(record['line'] for record in additions)
    return '\n'.join(preview) + '\n\n' + body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='print proposals without changing files or issues')
    parser.add_argument('--readme', type=Path, default=Path(__file__).resolve().parents[1] / 'readme.md')
    parser.add_argument('--report', type=Path, help='optional machine-readable provenance report')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', 'mrsarac/awesome-fframes'))
    args = parser.parse_args()
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print('GITHUB_TOKEN is required.', file=sys.stderr)
        return 1
    report = {}
    try:
        print(run(Client(token), args.readme, args.repository, datetime.now(timezone.utc), args.dry_run, report))
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + '\n')
        return 0
    except (APIError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Candidate collection failed: ' + type(exc).__name__ + '. No partial list was published.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
