## Spreadsheet column descriptions

The `write_ods` function writes the same columns to both spreadsheet tabs:

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