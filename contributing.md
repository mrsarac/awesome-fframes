# Contributing

Suggest one relevant resource per pull request. This list focuses on fframes, not general video tools.

- Use `- [Name](url) - Description.` with an uppercase first letter and a final period.
- Link to the canonical project, documentation or article. Open the link before submitting it.
- Explain what the resource provides without star counts, speed claims or promotional language.
- Check the repository license file. Reusable crates, bindings and templates need an explicit license; unlicensed source belongs only in Showcase and must say “no license found”. Media rights may differ from code rights.
- Disclose entries that are your own projects with “maintainer's own project” where applicable.
- Check recent commits. Flag projects with no commit in the previous twelve months for review rather than silently removing them.
- Do not copy third-party code or media into this repository.

Run these checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
npx awesome-lint
lychee readme.md
GITHUB_TOKEN=YOUR_GITHUB_TOKEN python3 scripts/candidates.py --dry-run
```

Supply credentials through your environment; never commit or paste a real token into a report. Dry runs read metadata and print proposals without editing the list, state or issues. The candidates script admits only non-fork, non-archived repositories with a license file, a description, a push within 180 days, and either ten stars or a reverse-dependent crate with one hundred downloads. Descriptions are cleaned and shortened deterministically; no model is called. Other candidates and entries without a commit in twelve months go into one ISO-week issue. API failures stop the run instead of silently publishing partial results.

Weekly maintenance runs on Mondays at 08:00 UTC and can be dispatched manually. The health script removes archived repositories and links failing in two consecutive ISO weeks. A retry within the same week does not increase the failure streak; a healthy observation or missed week breaks it. State lives in `.github/link-state.json`. The pending `bot/weekly` branch is reused so unmerged observations survive until the next run.

One pull request contains proposed list/state changes and their source metadata. Actions are pinned to commit SHAs; the scripts use only the Python standard library and public GitHub/crates.io APIs. No model or agent runs. Automatic additions go to Crates for reverse dependencies, Agent skills for matching names/topics, or Community otherwise. Removal of the last entry also removes its heading and contents link. A provenance ledger retains evidence for an open pull request; it is cleared as changes reach the default branch.

Both checks run on the proposed tree within the weekly job and their results are recorded in the pull request body. The separate pull-request workflow also runs for normal PR events. PR workflows created through `GITHUB_TOKEN` may wait for a maintainer to approve them; the weekly job therefore validates the proposed tree independently. See the [GitHub workflow-trigger documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow). First-week link failures are recorded even when a PR needs repair. Only the weekly pull request is queued with `gh pr merge --auto --squash` after both awesome-lint and lychee pass. The merge command is bound to the checked commit SHA. Inclusion thresholds remain unchanged. A maintainer must enable Actions pull requests and auto-merge in repository settings; the workflow never changes those settings. Initial-release and other pull requests are outside this automatic merge path.

For a local health preview, first create a lychee report:

```sh
mkdir -p lychee
lychee --no-progress --format json --output lychee/out.json readme.md
GITHUB_TOKEN=YOUR_GITHUB_TOKEN python3 scripts/health.py --dry-run
```

Fork pull requests receive check results; issue creation requires trusted workflow permissions. The weekly branch preserves pending edits instead of force-pushing over them. If the default branch diverges while a PR is open, resolve any merge conflict during review.

CC0 applies to your list contributions. Before proposing this list to the main Awesome directory, allow at least thirty days for it to mature.
