# Spreadsheet column descriptions

## unfoldingword_repos.ods — column descriptions

- **Repositories** — all fetched repositories.
- **JavaScript TypeScript** — only repositories whose GitHub language is JavaScript or TypeScript.

| Column | Description |
|---|---|
| **repo name** | The GitHub repository name. For monorepo submodules, this may be formatted as `repo-name/package-name`. |
| **organization name** | The GitHub organization or owner login that owns the repository. |
| **language** | The primary language reported by GitHub for the repository. |
| **archived** | Whether the GitHub repository is archived. Usually `True` or `False`. |
| **is fork** | Whether the repository is a fork of another repository. Usually `True` or `False`. |
| **pushed at** | The timestamp of the most recent push recorded by GitHub. |
| **last commit date** | The date of the latest commit found on the repository’s default branch. |
| **last release date** | The publication date of the latest GitHub release. If no published date is available, the release creation date is used. |
| **open issues count** | The number of open issues reported by GitHub. Note that GitHub’s `open_issues_count` includes both issues and pull requests. |
| **open prs count** | The number of currently open pull requests in the repository. |
| **commit count** | The total number of commits on the repository's default branch. |
| **npmjs package name** | The npm package name found in the repository’s `package.json`, when available. |
| **npm is deprecated** | Whether the latest npm package version is marked as deprecated in the npm registry. Empty when no matching npm metadata was fetched. |
| **npmjs downloads last year** | The npm download count for the package over the `last-year` period. |
| **npmjs last published** | The publish timestamp of the latest npm package version. If no latest version is found, the most recent published version timestamp is used. |
| **npmjs used by** | A comma-separated list of local npm packages in the fetched repository set that depend on this package. |
| **npmjs uses** | A comma-separated list of local npm packages from the fetched repository set that this package depends on. |
| **github dependents** | A comma-separated list of GitHub repositories detected from the repository’s GitHub dependents page. |
| **github contributors** | A comma-separated list of contributor names, logins, or emails fetched from the GitHub contributors API. |
| **github release count** | The total number of GitHub releases found for the repository. |
| **github downloads** | The total number of downloads across all GitHub release assets for the repository. This is the sum of each release asset’s `download_count`. |
| **repo url** | The GitHub HTML URL for the repository. |
| **last edit date** | The repository’s `updated_at` timestamp from GitHub, representing the last time repository metadata changed. |

## Notes

- Empty cells usually mean that the value was not available, not applicable, or could not be fetched.
- npmjs columns refer to data from npmjs.com, the npm Registry.  Other columns are from github.
- npmjs-related columns are only populated for JavaScript and TypeScript repositories that have a `package.json` file and are not marked as private.
- npmjs registry data is only fetched when the npm package metadata appears to belong to one of the configured unfoldingWord GitHub organizations.
- `open issues count` comes from GitHub’s repository metadata and may include both issues and pull requests.
- `open prs count` is fetched separately from GitHub’s pull request API and represents only open pull requests.
- `github dependents` is detected from GitHub’s dependents page and may be incomplete if GitHub changes the page layout or limits visibility.
- `github release count` is fetched from GitHub releases and counts releases returned by the repository releases API.
- `github downloads` is fetched from GitHub releases and only counts release asset downloads. It does not include repository clones, source archive downloads, npm downloads, or other GitHub traffic metrics.
- `npmjs used by` and `npmjs uses` only describe relationships between packages found in the generated repository set. They do not include every package on npmjs.
- Date/time values are written in the format returned by GitHub or npmjs, usually ISO 8601 UTC timestamps.
- The **JavaScript TypeScript** sheet is a filtered view of the **Repositories** sheet, limited to repositories whose primary GitHub language is JavaScript or TypeScript.

---

## categorized_repos.csv / categorized_repos.ods — column descriptions

Produced by `CatagorizeRepos.py`. Extends the **Repositories** sheet of `unfoldingword_repos.ods` with additional columns. Tag columns are prepended from `tagged_repos.ods`, one derived column is inserted, and four classification columns are appended. The ODS also contains an **NPM Modules** sheet and a **Netlify** sheet.

### Repositories sheet additional columns

| Column | Description |
|---|---|
| **Ask** | Manual review tag from `tagged_repos.ods` (`Repositories` sheet). Non-empty when the repository has been flagged for a question or discussion. |
| **Archive** | Manual review tag from `tagged_repos.ods` (`Repositories` sheet). Non-empty when the repository has been marked for archival. |
| **Keep** | Manual review tag from `tagged_repos.ods` (`Repositories` sheet). Non-empty when the repository has been explicitly marked to keep active. |
| **Notes** | Manual notes from `tagged_repos.ods` (`Repositories` sheet). |
| **Ask-NPM** | npm-specific manual review tag from `tagged_repos.ods` (`NPM Modules` sheet). |
| **Deprecate-NPM** | npm-specific deprecation tag from `tagged_repos.ods` (`NPM Modules` sheet). |
| **Keep-NPM** | npm-specific keep tag from `tagged_repos.ods` (`NPM Modules` sheet). |
| **Notes-NPM** | npm-specific notes from `tagged_repos.ods` (`NPM Modules` sheet). |
| **is submodule of** | Comma-separated list of repositories (in `organization/repo-name` format) that reference this repository as a git submodule. Derived from the `git submodules` field by `add_submodule_relationships()`. Empty if not used as a submodule by any repository in the fetched set. |
| **repo full name** | The fully-qualified repository name in `organization/repo-name` format. |
| **repo url** | The GitHub HTML URL for the repository. |
| **repo full name2** | Duplicate of `repo full name`, placed immediately left of the `classification` column for quick reference when reviewing classifications. |
| **repo url2** | Duplicate of `repo url`, placed immediately left of the `classification` column for quick reference when reviewing classifications. |
| **classification** | The GitHub repository lifecycle label assigned by `determine_github_classification()`. Prefixed with a sort-rank digit (e.g. `0-Archive/Delete candidate`). See possible values below. |
| **classification reason** | A human-readable explanation of why the repository received its classification label. |
| **npmjs classification** | The npm package lifecycle label assigned by `determine_npmjs_classification()`. Empty for repositories with no published npm package. Prefixed with a sort-rank digit. See possible values below. |
| **npmjs classification reason** | A human-readable explanation of why the npm package received its classification label. |

### GitHub classification labels

Rules are applied in priority order; the first matching rule wins. The output value is prefixed with a sort-rank digit (e.g. `0-Archive/Delete candidate`).

| Label | Meaning |
|---|---|
| `Archive/Delete candidate` | Very old with no usage, downloads, or releases; old unmodified fork; obvious POC/demo with no dependents; or name suggests legacy/replaced content. |
| `Manual review` | High-risk or ambiguous: used as a git submodule, core product name, high issue/release/contributor count, recent metadata edit with old code, stale-but-used, stale package, stale/neglected, stale release process, or did not match any other rule. |
| `Keep` | Recently active (last commit within 12 months), locally used by another npm package, or externally used (GitHub dependents or ≥ 1,000 npm downloads in the last year). |
| `Nothing to do` | Repository is already archived, or npm package is already deprecated with a commit older than 24 months. |
| `Protected private` | No last commit date available — likely a private or protected repository with restricted access. |

### npm classification labels

Applied only to repositories that have a published npm package. Rules are applied in priority order; the first matching rule wins. The output value is prefixed with a sort-rank digit.

| Label | Meaning |
|---|---|
| `Deprecate npm package candidate` | Backed by an archived repository; or no detected local consumers, no GitHub dependents, and no npm downloads; or stale with low downloads; or name suggests obsolescence. |
| `Repair npm package` | Package metadata indicates a broken or misconfigured package on the npm registry. |
| `Manual review` | No npm package published; security-sensitive or build-tool name (auth, build, config, eslint, etc.); or low but nonzero usage with no detected local consumers. |
| `Nothing to do` | Package is already deprecated; not yet published; not owned by a configured uW npm org; or has local consumers, GitHub dependents, or ≥ 1,000 npm downloads. |

See [ClassificationRules.md](ClassificationRules.md) for the full rule definitions and recommended actions per label.

---

## netlify_sites.csv — column descriptions

Produced by `FetchNetlifySites.py`. Contains one row per Netlify site in the unfoldingWord account. Prefix columns (`Ask`, `Keep Auto Builds`, `Disable Auto Builds`, `Remove Project`, `Notes`) are prepended as empty strings for manual annotation.

| Column | Description |
|---|---|
| **Ask** | Manual review flag (empty in generated CSV; filled in `tagged_repos.ods`). |
| **Keep Auto Builds** | Manual tag (empty in generated CSV; filled in `tagged_repos.ods`). |
| **Disable Auto Builds** | Manual tag (empty in generated CSV; filled in `tagged_repos.ods`). |
| **Remove Project** | Manual tag (empty in generated CSV; filled in `tagged_repos.ods`). |
| **Notes** | Manual notes (empty in generated CSV; filled in `tagged_repos.ods`). |
| **name** | Netlify site name (subdomain slug). |
| **id** | Netlify site UUID. |
| **url** | The SSL/primary URL for the site. |
| **custom_domain** | Custom domain configured for the site, if any. |
| **account_name** | Display name of the Netlify account. |
| **account_slug** | Slug of the Netlify account. |
| **repo_url** | GitHub repository URL linked to the site's build settings. |
| **repo_branch** | Branch used for continuous deployment. |
| **framework** | Framework detected by Netlify (e.g. `gatsby`, `next`). |
| **build_command** | Build command configured in Netlify. |
| **auto_deploy** | `yes` if continuous deployment is enabled, `no` if stopped, empty if no repo is linked. |
| **published_at** | Timestamp of the most recent published deploy. |
| **created_at** | Timestamp when the site was created. |
| **updated_at** | Timestamp of the most recent site metadata update. |
| **state** | Netlify site state (e.g. `current`). |

The **Netlify** sheet in `categorized_repos.ods` is sourced from `sheets/netlify_sites.csv` (or from the previous `Netlify` sheet in `tagged_repos.ods` if the CSV is absent). Manual prefix column values are carried forward from the `Netlify` sheet of `tagged_repos.ods` by matching on site `id` or `name`.

---

## tagged_repos.ods — manual review tags

`tagged_repos.ods` is a hand-modified version of `categorized_repos.ods` used to carry manual decisions into the categorized output. It is read by `CatagorizeRepos.py` alongside `unfoldingword_repos.ods` and its tag columns are merged into `categorized_repos.ods` / `categorized_repos.csv`.

**Note:** `tagged_repos.ods` is not generated by any script in this project. It modified copy of `categorized_repos.ods` with notes and suggestions added manually.

### Repositories sheet

Must contain a **Repositories** sheet with at minimum a column to identify each repository (`repo full name`, or both `repo name` and `organization name`), plus any subset of the tag columns below. Rows with all tag columns empty are ignored.

| Column | Description |
|---|---|
| **repo full name** | Used to match rows to the fetched repository data. If absent, `repo name` and `organization name` are combined. |
| **Ask** | Free-text note flagging the repository for a question or discussion before a decision is made. |
| **Archive** | Free-text note or flag marking the repository as a candidate for archival. |
| **Keep** | Free-text note or flag marking the repository to keep active, overriding automatic classification signals. |
| **Notes** | General notes about the repository. |

**How matching works:** each row in the `Repositories` sheet is matched to a row in the fetched data by `repo full name` (preferred) or by combining `organization name` + `repo name`. Unmatched rows are silently skipped.

### NPM Modules sheet

The optional **NPM Modules** sheet carries npm-specific manual tags. Rows are matched using the same `repo full name` / `repo name` + `organization name` logic as the Repositories sheet.

| Column | Description |
|---|---|
| **repo full name** | Used to match rows to the fetched repository data. |
| **Ask-NPM** | Free-text note flagging the npm package for a question or discussion. |
| **Deprecate-NPM** | Free-text note or flag marking the npm package as a deprecation candidate. |
| **Keep-NPM** | Free-text note or flag marking the npm package to keep active. |
| **Notes-NPM** | General notes about the npm package. |

### Netlify sheet

The optional **Netlify** sheet carries manual prefix column values for Netlify sites. Rows are matched to the generated `sheets/netlify_sites.csv` data using the first available stable identifier (`id`, `name`, `url`, etc.).

| Column | Description |
|---|---|
| **Ask** | Free-text note flagging the site for a question or discussion. |
| **Keep Auto Builds** | Flag to keep automatic builds enabled. |
| **Disable Auto Builds** | Flag to disable automatic builds. |
| **Remove Project** | Flag marking the site as a candidate for removal. |
| **Notes** | General notes about the site. |
