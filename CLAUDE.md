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

# Download the tagged-repos Google Sheet to sheets/marked_repos.ods
# (requires GOOGLE_SHEET_ID in .env and credentials.json; browser auth on first run)
python FetchMarkedReposSheetFromGithub.py

# Fetch Netlify site data for the unfoldingWord account and write sheets/netlify_sites.csv
python FetchNetlifySites.py

# Classify repositories and produce sheets/categorized_repos.csv and sheets/categorized_repos.ods
python CatagorizeRepos.py
```

## Architecture

Six top-level scripts, three shared libraries:

### Top-level scripts

- **`GitHubRepositoryFetcher.py`** — orchestrator. Verifies `GITHUB_TOKEN` against the GitHub API, calls `fetch_all_npmjs_modules_for_orgs()` to discover all npm packages owned by the configured npm orgs (`NPM_ORG_NAMES`), then `fetch_repositories(ORG_NAMES, org_modules)` to loop over the three GitHub orgs via `fetch_repositories_for_org()` (pagination via GitHub API Link headers), enriching each repo dict in-place with dependents, contributors, last commit/release dates, open PR count, commit count, git submodules, and npm data (package name, npm organization, deprecation, downloads, maintainers). After all repos are fetched, calls `update_npmjs_dependencies()` to resolve cross-repo npm dependency relationships (including monorepo subpackages). Finally calls `write_ods()` to produce `sheets/unfoldingword_repos.ods` directly using the ODF XML format (no odfpy write API — raw XML zipped).

- **`UpdateNpmData.py`** — discovers all packages in the configured npm orgs (`NPM_ORG_NAMES`: `unfoldingword`, `oce-editor-tools`) via `fetch_npmjs_modules_for_all_orgs()`, then re-fetches npm registry data (maintainers, broken status, npm organization, deprecation status, downloads, publish date) for every package recorded in `sheets/unfoldingword_repos.ods`. Saves packages present in an npm org but missing from the ODS to `sheets/missing_modules.json`. Rewrites both sheets in place. Also recomputes `npmjs used by` by inverting the `npmjs uses` graph already stored in the ODS. Run after `GitHubRepositoryFetcher.py` to refresh npm data without repeating all GitHub API calls.

- **`SheetToCSVConverter.py`** — reads `sheets/unfoldingword_repos.ods` via pandas/odf and writes one CSV per sheet (`sheets/Repositories.csv`, `sheets/JavaScript TypeScript.csv`).

- **`FetchMarkedReposSheetFromGithub.py`** — downloads the unfoldingWord tagged-repos Google Sheet as an ODS file and saves it to `sheets/marked_repos.ods`. Uses personal OAuth via `google-auth-oauthlib`. On first run, opens a browser for authentication and saves the token to `.google_token.json`; subsequent runs refresh silently. Requires `GOOGLE_SHEET_ID` in `.env` and `credentials.json` (OAuth Desktop app credential) in the project root. Both files are git-ignored.

- **`FetchNetlifySites.py`** — queries the Netlify API for all sites in the unfoldingWord account (`NETLIFY_ACCOUNT_SLUG = "unfoldingWord"`) and writes `sheets/netlify_sites.csv`. Requires `NETLIFY_TOKEN` in `.env`. Paginates via `page`/`per_page` query parameters; falls back to listing all accessible sites if the account slug returns 404. Each row includes site name, id, url, custom domain, repo url/branch, framework, build command, auto-deploy status, publish/create/update timestamps, and state. Prefix columns defined in `NETLIFY_PREFIX_COLUMNS` (for manual review tags) are prepended to every row as empty strings.

- **`CatagorizeRepos.py`** — reads the `Repositories` sheet from `sheets/unfoldingword_repos.ods`, runs `determine_github_classification()` and `determine_npmjs_classification()` on every row, appends four columns (`classification`, `classification reason`, `npmjs classification`, `npmjs classification reason`), sorts by classification priority, and writes `sheets/categorized_repos.csv` and `sheets/categorized_repos.ods`. Also writes a filtered `NPM Modules` sheet with npm-focused column ordering (`NPM_COLUMN_ORDER`), including a derived `npmjs url` column (`https://www.npmjs.com/package/<name>`), and a `Netlify` sheet sourced from `sheets/netlify_sites.csv` (or the previous Netlify sheet if the CSV is absent). The Netlify sheet gets `repo archived`, `Netlify Recommendation`, and `Netlify Recommendation Reason` columns prepended — `Netlify Recommendation` is produced by `determine_netlify_classification()` applying rules NL1–NL11. Manual review tag columns are merged from `sheets/marked_repos.ods`: repository tags (`Ask`, `Archive`, `Keep`, `Notes`) from the `Repositories` sheet, and npm-specific tags (`Ask-NPM`, `Deprecate-NPM`, `Keep-NPM`, `Notes-NPM`) from the `NPM Modules` sheet. Netlify prefix columns (`Ask`, `Keep Auto Builds`, `Disable Auto Builds`, `Remove Project`, `Notes`) are carried forward from the `Netlify` sheet of `marked_repos.ods`. GitHub classification labels (sort order): `Archive/Delete candidate`, `Manual review`, `Keep`, `Nothing to do`, `Protected private`. npm classification labels (sort order): `Deprecate npm package candidate`, `Repair npm package`, `Manual review`, `Nothing to do`. Rule logic (rule IDs like `A3`, `NM2`, `NL8`) is documented only as inline comments and docstrings inside `determine_github_classification()`, `determine_npmjs_classification()`, and `determine_netlify_classification()` in `CatagorizeRepos.py` — the standalone `ClassificationRules.md` and `Netlify.md` files those comments still reference were removed from the repo in earlier commits and no longer exist.

### Shared libraries

- **`lib/utilities.py`** — ODS/CSV I/O, low-level HTTP helpers, and data-manipulation utilities. Key contents:
  - `urlopen_with_retry()` — urllib wrapper with retry on transient network errors; used by both `lib/github_utils.py` and `lib/npm_utils.py`.
  - `load_env_file()` — loads `.env` key=value pairs into `os.environ`.
  - ODS I/O: `read_ods_sheet()` (raw XML parser), `read_ods_sheets()` / `write_ods_sheets()` / `write_rows_to_ods()` (pandas-based helpers), `update_ods_sheet_data()` (in-place sheet row replacement that preserves column widths).
  - `load_repository_data()` — loads the Repositories sheet from an ODS file and returns `(headers, list[dict])`, normalizing comma-separated cells to lists.
  - `write_list_to_csv()` — writes row dicts to a CSV, flattening list values to comma-separated strings.
  - `extract_npmjs_maintainer_names()` — extracts maintainer names/emails from npm package metadata; used by `UpdateNpmData.py` to populate `npmjs maintainers`.
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
  - `fetch_npmjs_modules_for_all_orgs(data_rows)` — calls `fetch_npmjs_org_packages()` for each org in `NPM_ORG_NAMES`, compares against existing ODS `data_rows`, and returns `(missing_modules, org_modules)`. Used by `UpdateNpmData.py`.
  - `fetch_all_npmjs_modules_for_orgs()` — similarly named but distinct: takes no args, just fetches and returns `{org_name: modules}` for every org in `NPM_ORG_NAMES` with no comparison against existing data. Used by `GitHubRepositoryFetcher.py` before the initial repository fetch.
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
- `CatagorizeRepos.py` comments cite rule IDs from `ClassificationRules.md` and `Netlify.md` (e.g. `# ClassificationRules.md Rule A3`, `# Netlify.md Rule NL8`). Both files were deleted from the repo; the rule text now lives only in those inline comments and the surrounding function docstrings — don't go looking for the markdown files.