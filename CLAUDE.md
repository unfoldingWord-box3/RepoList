# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Does

Fetches GitHub repository metadata for the unfoldingWord GitHub organizations (`unfoldingWord`, `unfoldingWord-box3`, `unfoldingWord-dev`), writes the results to an OpenDocument Spreadsheet (`.ods`), exports per-sheet CSV files, and classifies repositories by activity and usage status.

## Running

```bash
# Generate the spreadsheet (takes several minutes — many API calls per repo)
python GitHubRepositoryFetcher.py

# Split the spreadsheet into per-sheet CSV files
python SheetToCSVConverter.py

# Classify repositories and produce categorized_repos.csv and categorized_repos.ods
python CatagorizeRepos.py
```

## Architecture

Three top-level scripts, one shared library:

- **`GitHubRepositoryFetcher.py`** — orchestrator. Loops over the three orgs, calls `fetch_repositories_for_org()` (pagination via GitHub API Link headers), then enriches each repo dict in-place with dependents, contributors, last commit date, last release date, open PR count, and npm data. After all repos are fetched, calls `update_npmjs_dependencies()` to resolve cross-repo npm dependency relationships (including monorepo subpackages). Finally calls `write_ods()` to produce `unfoldingword_repos.ods` directly using the ODF XML format (no odfpy write API — raw XML zipped).

- **`SheetToCSVConverter.py`** — reads `unfoldingword_repos.ods` via pandas/odf and writes one CSV per sheet (`Repositories.csv`, `JavaScript TypeScript.csv`).

- **`CatagorizeRepos.py`** — reads the `Repositories` sheet from `unfoldingword_repos.ods`, runs `determine_github_classification()` and `determine_npmjs_classification()` on every row, appends four columns (`classification`, `classification reason`, `npmjs classification`, `npmjs classification reason`), sorts by classification priority, and writes `categorized_repos.csv` and `categorized_repos.ods`. GitHub classification labels (in priority order): `No longer used candidate`, `Keep - externally used`, `Keep - locally used`, `Manual review`, `Needs review`, `Dead - archived`, plus additional labels `Active`, `Dead candidate`, `Dead - deprecated`, `Stale`, `Stale but used`, `Stale package`, `Stale / neglected`, `Stale release process`. npm classification labels: `Deprecated npm package`, `Keep - npm package in use`, `Deprecate npm package candidate`, `Manual review - npm package`. See `ClassificationRules.md` for the full rule set.

- **`lib/utilities.py`** — all HTTP helpers, data-fetching functions, and ODS/CSV I/O utilities. Key design points:
  - `github_request()` / `github_html_request()` — thin wrappers around `urllib` with auth headers and 429 retry logic (`urlopen_with_retry`).
  - npm data is only fetched for JS/TS repos with a non-private `package.json` whose npm package homepage/repository URL maps back to one of the unfoldingWord orgs (`npm_repo_is_from_uw()`).
  - Monorepo detection: if a repo's `package.json` has `workspaces`, or an `nx.json` is present, all nested `package.json` files are fetched and each subpackage is treated as a synthetic repo entry appended to the main list.
  - `fetch_repository_file()` tries `main` then `master` branch for file lookups.
  - ODS I/O: `read_ods_sheet()` (raw XML parser), `read_ods_sheets()` / `write_ods_sheets()` / `write_rows_to_ods()` (pandas-based helpers).
  - `load_repository_data()` — loads `unfoldingword_repos.ods` Repositories sheet and returns `(headers, list[dict])`, normalizing comma-separated cells to lists.
  - `write_list_to_csv()` — writes row dicts to a CSV, flattening list values to comma-separated strings.
  - Data-manipulation helpers used by `CatagorizeRepos.py`: `is_empty()`, `is_true()`, `as_int()`, `parse_date()`, `months_old()`, `contains_any()`.

## Key Conventions

- Repo data flows as plain `dict` objects (GitHub API JSON). Fields added by this script are kebab-case Python keys (`last_commit_date`, `open_prs_count`, etc.).
- The `.ods` file is written as raw ODF XML in a zip, not via odfpy's write API.
- `open_issues_count` comes from GitHub metadata (includes PRs); `open_prs_count` is fetched separately from the pulls API.
- `github_dependents` is scraped from GitHub's HTML dependents page, not the API — fragile if GitHub changes page layout.