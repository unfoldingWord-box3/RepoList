# GitHub Repository Discovery Tools

Python scripts for collecting GitHub repository data (and associated npm data) on a set of organizations and for classifying the repositories based on usage and activity.  The goal is to help determine repositories that are no longer being used and may be archived and well as the npm releases that can be deprecated.

The process is in two parts (more detail in [Running](#running)):

1. Collecting GitHub repository data (and associated npm data) on a set of organizations.
2. Classifying the repositories based on usage and activity.

The advantage of this is that gathering the repository data is very slow. So only needs to be done infrequncently whenever new data needs to be collected. On the other hand, the classification process only needs to read the collected data from the generated spreadsheet and is very fast.  This allows the developer to rapidly iterate on classification rules.
The goal is to codify the process of collecting and classifying GitHub repositories.  This way we have deterministic and auditable results rather than just trusting AI to do the right thing.

## Prerequisites

- Python 3.11+
- A GitHub personal access token
- A Python virtual environment

## Setup

```bash
python -m virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt   # pandas odfpy
cp env.sample .env                # then add your GITHUB_TOKEN
```

- The token only needs read metadata permission on the target orgs.

### Generating a GitHub token

**To create a GitHub token:**

For this script, a **fine-grained personal access token** is usually best.

## Fine-grained token steps

1. Go to:

```plain text
https://github.com/settings/personal-access-tokens
```

2. Click **Generate new token**.

3. Give it a name, for example:

```plain text
Repo List Script
```

4. Set an expiration date.

5. Under **Resource owner**, choose the account (e.g. unfoldingWord).

6. Under **Repository access**, choose:

  - to include private repositories:

```plain text
All Repositories
```

  - or if you just want public repositories:

```plain text
Public Repositories
```


If you need access to private repositories in the organization, choose the specific organization/repositories instead.

7. For permissions, this script only needs read access to repository metadata. Use the minimum permissions available, such as:

```plain text
Metadata: Read-only
```


8. Click **Generate token**.

9. Copy the token immediately. GitHub will only show it once.

Then put it in your `.env` file:

```plain text
GITHUB_TOKEN=github_pat_your_token_here
```


The token is primarily needed to raise the GitHub API rate limit from 60 to 5,000 requests/hour. Since the target orgs are public, either option works.


## Caution
- `.env` file contains your GitHub token and should not be committed to a public repository. It is ignored by git by adding it to `.gitignore` to help prevent accidental committing of the file.


## Configuration

- In [GitHubRepositoryFetcher.py](GitHubRepositoryFetcher.py):
  - `ORG_NAMES` contains the names of the GitHub organizations to fetch data from.
  - `OUTPUT_FILE` is the path of the output ODS file (default: `sheets/unfoldingword_repos.ods`).

- If file `.env` is not present, Copy the sample environment file:

```
bash
cp env.sample .env
```
  - Then edit `.env` and put in your GitHub token.

## Running

### Generate the Repository Spreadsheet
_Note: This will take a while to run, but only needs to be done once a quarter or so._

Run:
```bash
python GitHubRepositoryFetcher.py
```
This generates an OpenDocument spreadsheet at:
```
sheets/unfoldingword_repos.ods
```

### Fetch Netlify Site Data

To pull current Netlify site data for the unfoldingWord account, run:
```bash
python FetchNetlifySites.py
```
Requires `NETLIFY_TOKEN` in your `.env` file (a Netlify personal access token with read access). This writes:
```
sheets/netlify_sites.csv
```
Run this before `CatagorizeRepos.py` so the Netlify sheet in `categorized_repos.ods` reflects current data.

### Refresh npm Data

To re-fetch npm registry data (downloads, publish date, deprecation status, broken status) without repeating the slow GitHub API calls, run:
```bash
python UpdateNpmData.py
```
This rewrites both sheets of `sheets/unfoldingword_repos.ods` in place and recomputes `npmjs used by` by inverting the `npmjs uses` graph already stored in the ODS. Packages present in the npm org but missing from the ODS are saved to `sheets/missing_modules.json`. Run this after `GitHubRepositoryFetcher.py` when only npm data needs refreshing.

### Classify Repositories

To classify every repository by activity and usage status and produce a categorized spreadsheet:
- First export the uW Google sheet `All our Github repos` as ods file and save to `sheets/tagged_repos.ods`. This preserves the `Ask`, `Archive`, `Keep`, `Notes`, `Ask-NPM`, `Deprecate-NPM`, `Keep-NPM`, `Notes-NPM`, and Netlify prefix columns when a new `categorized_repos.ods` is generated.
- Then run:
```bash
python CatagorizeRepos.py
```
This:
- reads the `Repositories` sheet from `sheets/unfoldingword_repos.ods`
- applies classification rules
- copies repository tags (`Ask`, `Archive`, `Keep`, `Notes`) from the `Repositories` sheet of `sheets/tagged_repos.ods`
- copies npm-specific tags (`Ask-NPM`, `Deprecate-NPM`, `Keep-NPM`, `Notes-NPM`) from the `NPM Modules` sheet of `sheets/tagged_repos.ods`
- carries forward Netlify prefix columns from the `Netlify` sheet of `sheets/tagged_repos.ods`
- writes `sheets/categorized_repos.csv` and `sheets/categorized_repos.ods` with three sheets:
  - `Repositories` — all repos with two sets of classification columns added:
    - `classification` / `classification reason` — GitHub repository lifecycle status
    - `npmjs classification` / `npmjs classification reason` — npm package lifecycle status (only for repositories with a published npm package)
  - `NPM Modules` — filtered to repos with an npm package, npm-focused column ordering
  - `Netlify` — sourced from `sheets/netlify_sites.csv` (or previous sheet if CSV is absent), with manual prefix columns carried forward

See [ClassificationRules.md](ClassificationRules.md) for the full rule set.

### Improving Classification Rules
If you make changes to the rules, update the `determine_github_classification` or `determine_npmjs_classification` functions and rerun `CatagorizeRepos.py` to update the output files.


### Export Spreadsheet Sheets to CSV
_Utility function that may be useful for other projects:_

To split the data in [sheets/unfoldingword_repos.ods](sheets/unfoldingword_repos.ods) into separate CSV files, run:
```bash
python SheetToCSVConverter.py
```

## Output

- [sheets/unfoldingword_repos.ods](sheets/unfoldingword_repos.ods) — generated spreadsheet containing repository data (sheets: `Repositories`, `JavaScript TypeScript`)
- [sheets/Repositories.csv](sheets/Repositories.csv) — all repositories exported from the spreadsheet
- [sheets/JavaScript TypeScript.csv](sheets/JavaScript%20TypeScript.csv) — JavaScript/TypeScript repositories exported from the spreadsheet
- [sheets/netlify_sites.csv](sheets/netlify_sites.csv) — Netlify site data for the unfoldingWord account
- [sheets/categorized_repos.csv](sheets/categorized_repos.csv) — categorized repositories exported as CSV
- [sheets/categorized_repos.ods](sheets/categorized_repos.ods) — repositories with classification columns added (sheets: `Repositories`, `NPM Modules`, `Netlify`)


## Additional Information

[SpreadsheetDocumentation.md](SpreadsheetDocumentation.md) – Documentation for the spreadsheet contents
[ClassificationRules.md](ClassificationRules.md) – Classification rules used by `CatagorizeRepos.py`
[CLAUDE.md](CLAUDE.md) – AI Documentation for RepoList
