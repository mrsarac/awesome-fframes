#!/usr/bin/env python3
"""Remove archived projects and links broken in two consecutive ISO weeks."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

from candidates import APIError, Client, repo_name

ENTRY = re.compile(r'^- \[[^\]]+\]\((https://[^)]+)\) - ', re.M)


def broken_urls(report):
    if 'error_map' not in report or not isinstance(report['error_map'], dict):
        raise ValueError('Expected a complete lychee JSON report')
    return {entry['url'] for field in ('error_map', 'timeout_map') for entries in report.get(field, {}).values() for entry in entries}


def week_date(week):
    year, number = week.split('-W')
    return date.fromisocalendar(int(year), int(number), 1)


def update_state(old, urls, broken, week):
    updated = {}
    for url in sorted(urls):
        previous = old.get(url, {})
        streak = 0
        first = None
        if url in broken:
            if previous.get('week') == week:
                streak = max(1, previous.get('streak', 0))
            elif previous.get('week') and week_date(week) - week_date(previous['week']) == timedelta(days=7):
                streak = previous.get('streak', 0) + 1
            else:
                streak = 1
            first = previous.get('first_failed_week') if streak > 1 else week
        # Healthy URLs need no new weekly state unless they are recovering.
        if streak or previous:
            updated[url] = {'week': week, 'streak': streak, 'first_failed_week': first}
    return updated


def remove_entries(text, removed):
    lines = [line for line in text.splitlines() if not ((match := ENTRY.match(line)) and match.group(1) in removed)]
    text = '\n'.join(lines) + '\n'
    # Rebuild sections before editing the earlier contents list, so offsets stay valid.
    pieces = re.split(r'(^## .+\n)', text, flags=re.M)
    kept = [pieces[0]]
    empty = []
    for index in range(1, len(pieces), 2):
        header, content = pieces[index:index + 2]
        title = header[3:].strip()
        if title not in ('Contents', 'Contributing') and not ENTRY.search(content):
            empty.append(title)
        else:
            kept.extend([header, content])
    text = ''.join(kept)
    for title in empty:
        text = re.sub(r'^- \[' + re.escape(title) + r'\]\(#[^)]+\)\n', '', text, flags=re.M)
    return text.rstrip() + '\n'


def run(client, readme, state_file, lychee_report, now, dry_run):
    original = readme.read_text()
    urls = set(ENTRY.findall(original))
    report_data = json.loads(lychee_report.read_text())
    broken = broken_urls(report_data)
    old_state = json.loads(state_file.read_text()) if state_file.exists() else {}
    year, week, _ = now.isocalendar()
    current = f'{year}-W{week:02d}'
    state = update_state(old_state, urls, broken, current)
    removed = []
    metadata = {}
    for url in sorted(urls):
        name = repo_name(url)
        if name and name not in metadata:
            print('Checking archive status: ' + name, file=sys.stderr, flush=True)
            metadata[name] = client.get('https://api.github.com/repos/' + name)
        info = metadata.get(name, {})
        reasons = []
        if info.get('archived'):
            reasons.append('Repository archived')
        if state.get(url, {}).get('streak', 0) >= 2:
            reasons.append('Link broken in consecutive weeks ' + str(state[url]['first_failed_week']) + ' and ' + current)
        if reasons:
            removed.append({'url': url, 'reasons': reasons, 'source': 'https://api.github.com/repos/' + name if name else url,
                            'stargazers_count': info.get('stargazers_count'), 'pushed_at': info.get('pushed_at'),
                            'license': (info.get('license') or {}).get('spdx_id'), 'crate_downloads': None})
    result = {'removed': removed, 'week': current, 'broken_this_run': sorted(urls & broken), 'checked_at': now.isoformat()}
    if not dry_run:
        removed_urls = {item['url'] for item in removed}
        updated = remove_entries(original, removed_urls)
        if updated != original:
            readme.write_text(updated)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({url: value for url, value in state.items() if url not in removed_urls}, indent=2) + '\n')
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--readme', type=Path, default=root / 'readme.md')
    parser.add_argument('--state', type=Path, default=root / '.github/link-state.json')
    parser.add_argument('--lychee-report', type=Path, default=root / 'lychee/out.json')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print('GITHUB_TOKEN is required.', file=sys.stderr)
        return 1
    try:
        result = run(Client(token), args.readme, args.state, args.lychee_report, datetime.now(timezone.utc), args.dry_run)
        print(json.dumps(result, indent=2))
        if args.report:
            args.report.write_text(json.dumps(result, indent=2) + '\n')
        return 0
    except (APIError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Health collection failed: ' + type(exc).__name__ + '. No partial list was published.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
