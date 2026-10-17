#!/usr/bin/env python3
"""Keep provenance for changes in an open weekly pull request."""
import json
from pathlib import Path
import re

ENTRY = re.compile(r'^- \[[^\]]+\]\((https://[^)]+)\) - ', re.M)


def build(root):
    work = root / 'lychee'
    additions = json.loads((work / 'candidates.json').read_text())['added']
    removals = json.loads((work / 'health.json').read_text())['removed']
    ledger_path = root / '.github/weekly-sources.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    for record in additions:
        ledger[record['url']] = dict(record, change='add')
    for record in removals:
        ledger[record['url']] = dict(record, change='remove')
    base = set(ENTRY.findall((work / 'base.md').read_text()))
    current = set(ENTRY.findall((root / 'readme.md').read_text()))
    changed = base ^ current
    if not changed.issubset(ledger):
        raise ValueError('A changed entry lacks provenance; review manually')
    ledger = {url: ledger[url] for url in sorted(changed)}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
    lines = ['Weekly maintenance', '', 'No model calls. Auto-merge is requested only after awesome-lint and lychee pass on the checked commit.', '']
    for url, record in ledger.items():
        lines.extend(['- ' + record['change'].capitalize() + ': ' + url,
                      '  - Stars: ' + str(record.get('stargazers_count')),
                      '  - License: ' + str(record.get('license_file') or record.get('license')),
                      '  - Last push: ' + str(record.get('pushed_at')),
                      '  - Dependent-crate downloads: ' + str(record.get('crate_downloads')),
                      '  - Source: ' + str(record.get('source') or record.get('url'))])
        if record.get('crates'):
            lines.append('  - Crates: ' + json.dumps(record['crates']))
        if record.get('reasons'):
            lines.append('  - Reason: ' + '; '.join(record['reasons']))
    state = json.loads((root / '.github/link-state.json').read_text())
    if state:
        lines.extend(['', 'Link observations:', '', '```json', json.dumps(state, indent=2), '```'])
    if not ledger:
        lines.append('No entry additions/removals; any diff records link-health observations.')
    lines.extend(['', 'Checks ran on this proposed tree in the weekly workflow; results and run URL follow.'])
    (work / 'pr-body.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1])
