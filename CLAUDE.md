# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Does

Fetches GitHub repository metadata for the unfoldingWord GitHub organizations (`unfoldingWord`, `unfoldingWord-box3`, `unfoldingWord-dev`), writes the results to an OpenDocument Spreadsheet (`.ods`), exports per-sheet CSV files, and classifies repositories by activity and usage status.

## Running

```bash
# Generate the spreadsheet (takes several minutes — many API calls per repo)
python GitHubRepositoryFetcher.py

# Refresh only npm registry data without re-fetching GitHub metadata
python UpdateNpmData.py

# Split the spreadsheet into per-sheet CSV files
python SheetToCSVConverter.py

# Classify repositories and produce sheets/categorized_repos.csv and sheets/categorized_repos.ods
python CatagorizeRepos.py
```

## Architecture

Four top-level scripts, three shared libraries:

### Top-level scripts

- **`GitHubRepositoryFetcher.py`** — orchestrator. Loops over the three orgs, calls `fetch_repositories_for_org()` (pagination via GitHub API Link headers), then enriches each repo dict in-place with dependents, contributors, last commit date, last release date, open PR count, and npm data. After all repos are fetched, calls `update_npmjs_dependencies()` to resolve cross-repo npm dependency relationships (including monorepo subpackages). Finally calls `write_ods()` to produce `sheets/unfoldingword_repos.ods` directly using the ODF XML format (no odfpy write API — raw XML zipped).

- **`UpdateNpmData.py`** — discovers all `@unfoldingword`-scoped packages via the npm search API, then re-fetches npm registry data (downloads, publish date, deprecation status, broken status, npm organization) for every package recorded in `sheets/unfoldingword_repos.ods`. Saves packages present in the npm org but missing from the ODS to `sheets/missing_modules.json`. Rewrites both sheets in place. Also recomputes `npmjs used by` by inverting the `npmjs uses` graph already stored in the ODS. Run after `GitHubRepositoryFetcher.py` to refresh npm data without repeating all GitHub API calls.

- **`SheetToCSVConverter.py`** — reads `sheets/unfoldingword_repos.ods` via pandas/odf and writes one CSV per sheet (`sheets/Repositories.csv`, `sheets/JavaScript TypeScript.csv`).

- **`CatagorizeRepos.py`** — reads the `Repositories` sheet from `sheets/unfoldingword_repos.ods`, runs `determine_github_classification()` and `determine_npmjs_classification()` on every row, appends four columns (`classification`, `classification reason`, `npmjs classification`, `npmjs classification reason`), sorts by classification priority, and writes `sheets/categorized_repos.csv` and `sheets/categorized_repos.ods`. Also writes a filtered `NPM Modules` sheet with npm-focused column ordering. GitHub classification labels (sort order): `Archive/Delete candidate`, `Manual review`, `Keep`, `Nothing to do`, `Protected private`. npm classification labels: `Nothing to do`, `Deprecate npm package candidate`, `Repair npm package`, `Manual review - npm package`, `Keep - npm package in use`. Rule logic is documented in `ClassificationRules.md`.

### Shared libraries

- **`lib/utilities.py`** — ODS/CSV I/O, low-level HTTP helpers, and data-manipulation utilities. Key contents:
  - `urlopen_with_retry()` — urllib wrapper with retry on transient network errors; used by both `lib/github_utils.py` and `lib/npm_utils.py`.
  - `load_env_file()` — loads `.env` key=value pairs into `os.environ`.
  - ODS I/O: `read_ods_sheet()` (raw XML parser), `read_ods_sheets()` / `write_ods_sheets()` / `write_rows_to_ods()` (pandas-based helpers), `update_ods_sheet_data()` (in-place sheet row replacement that preserves column widths).
  - `load_repository_data()` — loads the Repositories sheet from an ODS file and returns `(headers, list[dict])`, normalizing comma-separated cells to lists.
  - `write_list_to_csv()` — writes row dicts to a CSV, flattening list values to comma-separated strings.
  - Data-manipulation helpers used by `CatagorizeRepos.py`: `is_empty()`, `is_true()`, `as_int()`, `parse_date()`, `months_old()`, `contains_any()`.
  - `contains_any(value, terms)` returns the first matching term string (truthy) or `""` (falsy) — not a bool — so callers can inspect which term fired.

- **`lib/github_utils.py`** — all GitHub API and web-scraping functions. Key contents:
  - `github_request()` / `github_html_request()` — thin wrappers around `urllib` with auth headers and 429/403 retry logic (backed by `urlopen_with_retry`).
  - `get_next_page_url()` — parses GitHub Link headers for pagination.
  - `fetch_repository_*()` — individual enrichment fetchers: dependents (scraped HTML), contributors, last commit date, last release date, open PR count, commit count, GitHub release downloads, submodules (`.gitmodules`).
  - `fetch_repository_file()` — fetches a file from a repo, trying `main` then `master`.
  - `fetch_repository_json_file()`, `fetch_package_json()`, `fetch_package_json_files()`, `fetch_nx_json()` — file-fetch helpers for npm/monorepo data.
  - `fetch_repositories_for_org()` / `fetch_repositories()` — paginated org-level repo fetchers; `fetch_repositories_for_org` uses a local import from `lib.npm_utils` to avoid a circular dependency.
  - `write_ods()` — writes the two-sheet ODS file (`Repositories` + `JavaScript TypeScript`) as raw ODF XML in a zip.

- **`lib/npm_utils.py`** — all npm registry functions and dependency graph management. Key contents:
  - `fetch_npmjs_package_metadata()` — fetches full package metadata from the npm registry.
  - `npm_repo_is_from_uw()` — checks whether a package's homepage/repository URL maps back to a uW org; signature is `(package_metadata, org_names, org_modules, maintainer_names)`.
  - `is_uw_maintained()` — checks whether a package's maintainer list contains a known uW maintainer.
  - `find_npm_org()` — returns the npm organization name that owns a package, or `None`.
  - `fetch_npmjs_org_packages()` — discovers all packages in a scoped npm org via the npm search API (paginated).
  - `fetch_npmjs_modules_for_all_orgs()` — calls `fetch_npmjs_org_packages()` for each org in `NPM_ORG_NAMES`, compares against ODS data, and returns `(missing_modules, org_modules)`.
  - `npm_repo_check_if_broken()` — returns a description string if the package metadata indicates a broken/misconfigured package, else `None`.
  - `fetch_npmjs_last_published()`, `fetch_npmjs_is_deprecated()`, `fetch_npmjs_download_count()`, `fetch_npmjs_total_download_count()` — individual npm data fetchers.
  - `get_repos_by_npmjs_package_name()` — builds a `{package_name: repo}` index.
  - `update_repo_npmjs_dependency_relationships()` / `update_npmjs_dependencies()` — populates `npmjs uses` / `npmjs used by` fields by cross-referencing `dependencies`, `devDependencies`, and `peerDependencies` across all repos, including monorepo subpackages.

## Key Conventions

- Repo data flows as plain `dict` objects (GitHub API JSON). Fields added by this script are kebab-case Python keys (`last_commit_date`, `open_prs_count`, etc.).
- The `.ods` file is written as raw ODF XML in a zip, not via odfpy's write API.
- `open_issues_count` comes from GitHub metadata (includes PRs); `open_prs_count` is fetched separately from the pulls API.
- `github_dependents` is scraped from GitHub's HTML dependents page, not the API — fragile if GitHub changes page layout.
- `lib/github_utils.py` imports `urlopen_with_retry` from `lib/utilities.py`. `lib/npm_utils.py` imports `urlopen_with_retry` from `lib/utilities.py` and `fetch_repository_json_file` from `lib/github_utils.py`. Neither `lib/utilities.py` nor `lib/github_utils.py` imports from the other library at module level, avoiding circular imports.